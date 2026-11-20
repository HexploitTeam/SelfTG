"""The owner bot: a second Telethon client that acts as the control surface.

Why a bot at all, and why in this process
-----------------------------------------
The self-bot runs silently and has no UI beyond `!commands`. A BotFather bot can
put inline buttons in front of the owner, which is the natural shape for
"inspect state, flip a switch, confirm a destructive action". It lives in the
same process as the self-bot for three reasons:

* a second Python process would duplicate the interpreter and every import
  (~80-100 MiB) on a 2 GiB free Repl, while a second Telethon client costs one
  socket and about a megabyte;
* the useful features need the *user* account (send as me, run a command, stop a
  live timer). In one process that is an ordinary function call through
  :mod:`Com.bot.interop`, not an IPC protocol;
* both sides then write the same JSON documents in one event loop, so there is
  no cross-process read-modify-write race on `mode/*.json`.

The bot never talks to Telegram on the user's behalf by itself: it queues an
action in `mode/runtime.json` and the self-bot executes it. If the token is
missing or invalid the self-bot keeps running; the bot reports why it is not
there instead of disappearing.

No Bot API library is added: Telethon already signs in with `bot_token`, and a
second framework would bring another HTTP stack, another polling loop and a
second source of truth for "who is the owner".
"""
import asyncio
import logging
import os
import time

from telethon import TelegramClient, events
from telethon.errors import (
    AccessTokenExpiredError,
    AccessTokenInvalidError,
    ApiIdInvalidError,
    AuthKeyUnregisteredError,
)
from telethon.sessions import StringSession

from Com.bot import kit
from Com.bot import interop, registry, ui as botui
from Com.core.net import ReplitConnection
from Com.core.storage import load_json as _load_json, save_json as _save_json

log = logging.getLogger("selftg.bot")

#------------------------------
#Configuration
#------------------------------

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
BOT_ENABLED = bool(BOT_TOKEN)
bot_client = None
OWNER_ID = None
BOT_USERNAME = None
BOT_LAST_ERROR = None

HEARTBEAT_SECONDS = 30
ALERT_SECONDS = 15
ALERT_COOLDOWN = 10 * 60
RECONNECT_BASE = 5
RECONNECT_MAX = 300

# Every registry key must be here
HANDLER_KEYS = ("home", "status", "diagnostics", "commands", "ping", "id",
                "version", "cancel")

BASE_DIR = "mode"
ENEMY_FILE = os.path.join(BASE_DIR, "Enemy.json")
# Lowercase: Linux is case-sensitive and the commands use these names
WARN_FILE = os.path.join(BASE_DIR, "warn.json")
MUTE_FILE = os.path.join(BASE_DIR, "mute.json")
ELIST_FILE = os.path.join(BASE_DIR, "EList.json")

LEGACY_STATE_FILES = (
    (os.path.join(BASE_DIR, "Warn.json"), WARN_FILE),
    (os.path.join(BASE_DIR, "Mute.json"), MUTE_FILE),
)

# Bare data from older buttons still resolves
LEGACY_ROUTES = {
    "stats": ("status",),
    "enemies": ("chats", "mod", 0),
    "warns": ("chats", "mod", 0),
    "mutes": ("chats", "mod", 0),
    "texts": ("chats", "mod", 0),
    "admin": ("chats", "mod", 0),
}
LEGACY_HINTS = {
    "add_enemy": "Use /add_enemy <chat_id> <user_id> [category]",
    "remove_enemy": "Use /remove_enemy <chat_id> <user_id>",
    "set_warn": "Use /set_warn <chat_id> <limit>",
    "add_mute": "Use /add_mute <chat_id> <user_id> [admin|manual]",
    "remove_mute": "Use /remove_mute <chat_id> <user_id>",
}


class BotAuthError(RuntimeError):
    """The token is wrong; retrying the same credential cannot help."""


#------------------------------
#Helpers
#------------------------------

def load_json(fpath):
    return _load_json(fpath, {})


def save_json(fpath, data):
    _save_json(fpath, data)


def migrate_legacy_state():
    """Copy data from the old CamelCase state files once, without clobbering."""
    for legacy_path, current_path in LEGACY_STATE_FILES:
        if not os.path.exists(legacy_path) or os.path.exists(current_path):
            continue
        legacy_data = _load_json(legacy_path, None)
        if legacy_data is None:
            continue
        save_json(current_path, legacy_data)
        log.info("[BOT] migrated legacy state %s -> %s", legacy_path, current_path)


async def send_inline(chat_id, text, buttons=None, reply_to=None):
    """Send a message through the bot client with inline buttons.

    Imported by Com/inline.py (which used to import a function that never
    existed here, so that module silently failed to load). Returns True on
    success so callers can fall back to a plain self-bot message.
    """
    if bot_client is None:
        return False
    try:
        await bot_client.send_message(
            chat_id, text, buttons=buttons or None, reply_to=reply_to
        )
        return True
    except Exception as exc:  # noqa: BLE001 - caller falls back to plain text
        log.warning("[BOT] send_inline failed: %s", exc)
        return False


def get_bot_status():
    """One line for !botstatus and !panel; never raises."""
    if not BOT_ENABLED:
        return (
            "❌ Bot disabled: BOT_TOKEN is not set. Create a bot with @BotFather "
            "and add its token under Replit Secrets."
        )
    if bot_client is None:
        detail = f" Last error: {BOT_LAST_ERROR}" if BOT_LAST_ERROR else ""
        return f"⏳ Bot connecting… (token exists){detail}"
    if not bot_client.is_connected():
        return "⚠️ Bot disconnected; reconnecting."
    return f"✅ Bot running as @{BOT_USERNAME or '?'} (owner {OWNER_ID})"


#------------------------------
#Handlers
#------------------------------

def _register_handlers(client, owner_id):
    ctx = botui.Ctx(client, owner_id)

    async def _is_owner(event):
        return event.sender_id == owner_id

    async def _home(event):
        await kit.send(ctx, botui.home_screen())
        flow = kit.active_flow(owner_id)
        if flow:
            # A flow survives a restart
            await event.respond(
                f"▶️ Unfinished flow <code>{kit.h(flow.get('name', '?'))}</code> is "
                "still waiting for a message. Send it, or /cancel.",
                parse_mode="html",
            )

    async def _status_cmd(event):
        await kit.send(ctx, botui.status_screen())

    async def _diagnostics_cmd(event):
        await kit.send(ctx, botui.diag_screen())

    async def _commands_cmd(event):
        await kit.send(ctx, botui.commands_screen())

    async def _ping_cmd(event):
        started = time.monotonic()
        message = await event.respond("🏓 …")
        elapsed = int((time.monotonic() - started) * 1000)
        try:
            await message.edit(f"🏓 pong in {elapsed} ms")
        except Exception:  # noqa: BLE001 - an edit failure is not a ping failure
            log.debug("bot: ping edit failed", exc_info=True)

    async def _id_cmd(event):
        await event.respond(
            "🆔 <b>Ids</b>\n"
            f"Owner: <code>{owner_id}</code>\n"
            f"Chat: <code>{event.chat_id}</code>\n"
            f"Sender: <code>{event.sender_id}</code>\n"
            f"Bot: @{kit.h(BOT_USERNAME or '?')}",
            parse_mode="html",
            # Inline-only clipboard button; the ids are copied, not retyped
            buttons=kit.markup([[
                kit.copy_btn("📋 Copy chat id", str(event.chat_id)),
            ]]),
        )

    async def _version_cmd(event):
        self_info = interop.load_runtime().get("selfbot", {})
        await event.respond(
            "🏷 <b>Version</b>\n"
            f"Bot boot: <code>{kit.h(interop.BOOT_ID)}</code>\n"
            f"Self-bot boot: <code>{kit.h(self_info.get('boot_id', '?'))}</code>\n"
            f"Pid: <code>{os.getpid()}</code>\n"
            f"Commands in registry: {len(registry.COMMANDS)}\n"
            f"Bot uptime: {kit.age(time.time() - interop.started_at())}",
            parse_mode="html",
        )

    async def _cancel_cmd(event):
        kit.clear_flow(owner_id)
        await event.respond("Flow cancelled. /start for the menu.")

    handlers = {
        "home": _home,
        "status": _status_cmd,
        "diagnostics": _diagnostics_cmd,
        "commands": _commands_cmd,
        "ping": _ping_cmd,
        "id": _id_cmd,
        "version": _version_cmd,
        "cancel": _cancel_cmd,
    }
    missing = [key for key in registry.keys() if key not in handlers]
    if missing or set(handlers) != set(HANDLER_KEYS):
        log.error("bot: registry handlers do not match (missing=%s, extra=%s)",
                  missing, sorted(set(handlers) - set(HANDLER_KEYS)))
    name_to_key = {name: key for name, _d, _c, key in registry.COMMANDS}

    @client.on(events.NewMessage(pattern=r"^/([A-Za-z]+)(?:@[A-Za-z0-9_]+)?$"))
    async def slash_cmd(event):
        if not await _is_owner(event):
            return
        key = name_to_key.get(event.pattern_match.group(1).lower())
        if key is None:
            return
        handler = handlers.get(key)
        if handler is None:
            log.error("bot: /%s maps to unknown handler %s",
                      event.pattern_match.group(1), key)
            await event.respond("That command is registered but not wired.")
            return
        await handler(event)

    @client.on(events.CallbackQuery)
    async def callback_handler(event):
        answered = False
        try:
            if event.sender_id != owner_id:
                answered = await kit.answer(event, "Not your bot.", alert=True)
                return
            try:
                route = kit.parse_cb(event.data or b"")
            except ValueError:
                legacy = event.data.decode("utf-8", errors="replace")
                route = LEGACY_ROUTES.get(legacy)
                if route is None:
                    hint = LEGACY_HINTS.get(legacy)
                    if hint:
                        answered = await kit.answer(event, hint, alert=True)
                    else:
                        # Dead button: replace the message
                        await kit.edit(event, botui.home_screen())
                        answered = await kit.answer(
                            event, "This menu is out of date.", alert=True
                        )
                    return
            await botui.dispatch(ctx, event, route)
        except Exception:  # noqa: BLE001 - a crash here would leave a spinner
            log.exception("bot: callback failed")
        finally:
            if not answered:
                await kit.answer(event)

    @client.on(events.NewMessage)
    async def text_handler(event):
        if event.sender_id != owner_id:
            return
        text = event.raw_text or ""
        if text.startswith("/"):
            return
        try:
            await botui.on_text(ctx, event)
        except Exception:  # noqa: BLE001 - never let a flow kill the bot
            log.exception("bot: text flow failed")
            await event.respond("❌ That step failed; /cancel and try again.")

    # Scriptable interface to the same state the buttons edit
    @client.on(events.NewMessage(pattern=r"^/add_enemy\s+(-?\d+)\s+(\d+)(?:\s+(\w+))?(?:\s+(.+))?$"))
    async def add_enemy_cmd(event):
        if not await _is_owner(event):
            return
        chat_id = event.pattern_match.group(1)
        user_id = int(event.pattern_match.group(2))
        category = event.pattern_match.group(3) or "default"
        custom_text = event.pattern_match.group(4) or ""
        enemies = load_json(ENEMY_FILE)
        if not isinstance(enemies, dict):
            enemies = {}
        if chat_id not in enemies:
            enemies[chat_id] = []
        if any(u.get("user_id") == user_id for u in enemies[chat_id]):
            await event.respond(f"User {user_id} already in enemy list.")
            return
        enemies[chat_id].append(
            {"user_id": user_id, "category": category, "custom_text": custom_text}
        )
        save_json(ENEMY_FILE, enemies)
        await event.respond(f"✅ Added enemy: Chat {chat_id}, User {user_id}")

    @client.on(events.NewMessage(pattern=r"^/remove_enemy\s+(-?\d+)\s+(\d+)$"))
    async def remove_enemy_cmd(event):
        if not await _is_owner(event):
            return
        chat_id = event.pattern_match.group(1)
        user_id = int(event.pattern_match.group(2))
        enemies = load_json(ENEMY_FILE)
        if not isinstance(enemies, dict) or chat_id not in enemies:
            await event.respond(f"Chat {chat_id} not found.")
            return
        new_users = [u for u in enemies[chat_id] if u.get("user_id") != user_id]
        if len(new_users) == len(enemies[chat_id]):
            await event.respond(f"User {user_id} not found.")
            return
        enemies[chat_id] = new_users
        save_json(ENEMY_FILE, enemies)
        await event.respond(f"✅ Removed enemy: Chat {chat_id}, User {user_id}")

    @client.on(events.NewMessage(pattern=r"^/set_warn\s+(-?\d+)\s+(\d+)$"))
    async def set_warn_cmd(event):
        if not await _is_owner(event):
            return
        chat_id = event.pattern_match.group(1)
        limit = int(event.pattern_match.group(2))
        warns = load_json(WARN_FILE)
        if not isinstance(warns, dict):
            warns = {}
        if chat_id not in warns:
            warns[chat_id] = {"limit": limit, "warnings": {}}
        else:
            warns[chat_id]["limit"] = limit
        save_json(WARN_FILE, warns)
        await event.respond(f"✅ Warn limit for chat {chat_id} set to {limit}")

    @client.on(events.NewMessage(pattern=r"^/add_mute\s+(-?\d+)\s+(\d+)(?:\s+(\w+))?$"))
    async def add_mute_cmd(event):
        if not await _is_owner(event):
            return
        chat_id = event.pattern_match.group(1)
        user_id = int(event.pattern_match.group(2))
        mode = event.pattern_match.group(3) or "admin"
        mutes = load_json(MUTE_FILE)
        if not isinstance(mutes, dict):
            mutes = {}
        if chat_id not in mutes:
            mutes[chat_id] = []
        if any(u.get("user_id") == user_id for u in mutes[chat_id]):
            await event.respond(f"User {user_id} already muted.")
            return
        mutes[chat_id].append({"user_id": user_id, "mode": mode})
        save_json(MUTE_FILE, mutes)
        await event.respond(f"✅ Muted: Chat {chat_id}, User {user_id}")

    @client.on(events.NewMessage(pattern=r"^/remove_mute\s+(-?\d+)\s+(\d+)$"))
    async def remove_mute_cmd(event):
        if not await _is_owner(event):
            return
        chat_id = event.pattern_match.group(1)
        user_id = int(event.pattern_match.group(2))
        mutes = load_json(MUTE_FILE)
        if not isinstance(mutes, dict) or chat_id not in mutes:
            await event.respond(f"Chat {chat_id} not found.")
            return
        new_users = [u for u in mutes[chat_id] if u.get("user_id") != user_id]
        if len(new_users) == len(mutes[chat_id]):
            await event.respond(f"User {user_id} not found.")
            return
        mutes[chat_id] = new_users
        save_json(MUTE_FILE, mutes)
        await event.respond(f"✅ Unmuted: Chat {chat_id}, User {user_id}")


#------------------------------
#Background tasks
#------------------------------

async def _heartbeat_loop(client):
    while True:
        interop.touch_bot(client, BOT_USERNAME, connected=client.is_connected())
        # Bound botstate.json without another task
        try:
            removed = kit.prune()
            if removed:
                log.info("[BOT] pruned %d expired flow/token(s)", removed)
        except Exception:  # noqa: BLE001 - housekeeping must not stop the heartbeat
            log.debug("[BOT] could not prune bot state", exc_info=True)
        await asyncio.sleep(HEARTBEAT_SECONDS)


async def _alert_loop(ctx):
    """Deliver self-bot events, and say once when the self-bot goes quiet."""
    last_stale_alert = 0.0
    while True:
        await asyncio.sleep(ALERT_SECONDS)
        try:
            if not kit.settings().get("alerts", True):
                continue
            for event in interop.pending_events():
                await ctx.client.send_message(
                    ctx.owner_id, f"🔔 {event.get('text', '')}", parse_mode="html"
                )
                interop.ack_event(event.get("id"))
            if not interop.is_online("selfbot"):
                now = time.time()
                if now - last_stale_alert > ALERT_COOLDOWN:
                    last_stale_alert = now
                    await ctx.client.send_message(
                        ctx.owner_id,
                        "⚠️ The self-bot has not written a heartbeat for over "
                        f"{interop.HEARTBEAT_STALE}s. Check the Replit log; "
                        "queued actions will wait.",
                    )
            else:
                last_stale_alert = 0.0
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - alerts must never kill the bot
            log.exception("bot: alert loop failed")


#------------------------------
#Lifecycle
#------------------------------

async def _run_once(owner_id):
    """Connect, register handlers and block until the socket is gone."""
    global bot_client, BOT_USERNAME, BOT_LAST_ERROR

    raw_api_id = (os.getenv("API_ID") or "").strip()
    api_hash = (os.getenv("API_HASH") or "").strip()
    if not raw_api_id or not api_hash:
        raise BotAuthError("API_ID/API_HASH are missing from Replit Secrets")
    try:
        api_id = int(raw_api_id)
    except ValueError:
        raise BotAuthError(
            f"API_ID must be numeric, got {raw_api_id!r}"
        ) from None

    # In-memory session: free Repls are public
    client = TelegramClient(StringSession(), api_id, api_hash,
                            connection=ReplitConnection,
                            # Same FLOOD_WAIT policy as the self-bot
                            flood_sleep_threshold=60)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            await client.sign_in(bot_token=BOT_TOKEN)
    except (AuthKeyUnregisteredError, AccessTokenExpiredError,
            AccessTokenInvalidError, ApiIdInvalidError) as exc:
        await client.disconnect()
        raise BotAuthError(
            f"BOT_TOKEN was rejected ({type(exc).__name__}). Revoke it with "
            "@BotFather /revoke, paste the new token into Replit Secrets and "
            "restart."
        ) from None
    except Exception as exc:  # noqa: BLE001 - network errors are retryable
        await client.disconnect()
        raise RuntimeError(f"could not connect: {type(exc).__name__}: {exc}") from None

    bot_client = client
    BOT_LAST_ERROR = None
    try:
        me = await client.get_me()
        BOT_USERNAME = getattr(me, "username", None)
        log.info("[BOT] running as @%s (owner %s)", BOT_USERNAME, owner_id)
        _register_handlers(client, owner_id)
        await registry.register(client)
        interop.touch_bot(client, BOT_USERNAME)

        ctx = botui.Ctx(client, owner_id)
        tasks = [
            asyncio.create_task(_heartbeat_loop(client), name="selftg-bot-heartbeat"),
            asyncio.create_task(_alert_loop(ctx), name="selftg-bot-alerts"),
        ]
        try:
            await client.run_until_disconnected()
            log.warning("[BOT] disconnected")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        bot_client = None
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


async def start_bot(owner_id):
    """Supervise the bot client for the lifetime of the self-bot process.

    One bad token must not restart forever, but a dropped socket must come back
    without a human touching the Repl, so auth failures end the loop and network
    failures back off.
    """
    global OWNER_ID, BOT_LAST_ERROR

    if not BOT_ENABLED:
        BOT_LAST_ERROR = "BOT_TOKEN is not set"
        log.warning(
            "[BOT] BOT_TOKEN is not set, so the owner bot is disabled. Create a "
            "bot with @BotFather, add BOT_TOKEN under Replit Secrets and restart. "
            "The self-bot keeps working without it."
        )
        return

    OWNER_ID = owner_id
    migrate_legacy_state()
    delay = RECONNECT_BASE
    while True:
        try:
            await _run_once(owner_id)
            delay = RECONNECT_BASE
        except BotAuthError as exc:
            BOT_LAST_ERROR = str(exc)
            log.error("[BOT] %s", exc)
            interop.notify(f"Owner bot stopped: {exc}")
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - retry with backoff
            BOT_LAST_ERROR = f"{type(exc).__name__}: {exc}"
            log.warning("[BOT] %s; retrying in %ds", BOT_LAST_ERROR, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, RECONNECT_MAX)
