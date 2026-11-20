"""`!afk` -- away status with auto-replies to incoming private messages.

Scope model
-----------
There are two kinds of AFK state in one file:

* **global** (`!afk [reason]`) -- applies to incoming **DMs only**;
* **per-chat** (`!afk here [reason]`) -- applies to that one chat, which is how
  you opt a group in. Groups are never auto-replied to by default.

Auto-clear policy (single, consistent rule):
* the global state is cleared by **any** message the owner sends, in any chat;
* a per-chat state is cleared by a message the owner sends **in that chat**.
Commands (anything starting with `!`) never clear the state, otherwise `!afk`
would immediately clear itself.

Cooldowns are persisted in `mode/afk.json` (one auto-reply per sender per hour),
so restarting the Repl does not let a chatty contact be answered again.
"""
import logging
import time

from telethon import errors, events
import Com.core.tgsend as tgsend

import Com.core.registry as registry
from Com.core import flood
from Com.core import scheduler
from Com.core.reply import say
from Com.core.storage import load_store, save_json

log = logging.getLogger("selftg.afk")

AFK_FILE = "mode/afk.json"
SCHEMA_VERSION = 1
COOLDOWN_SECONDS = 3600
DEFAULT_REASON = "Away from keyboard — I'll reply when I'm back."

SUBCOMMANDS = [
    ("!afk [reason]", "set a global AFK (auto-replies to DMs)"),
    ("!afk here [reason]", "set AFK for this chat only (groups stay off by default)"),
    ("!afk off", "clear the global AFK and this chat's AFK"),
    ("!afk off all", "clear every AFK entry"),
    ("!afk status", "show state, reason and since-when"),
    ("!afk list", "list per-chat AFK entries and active cooldowns"),
]

__HELP__ = registry.command(
    "afk", SUBCOMMANDS,
    "Away status: auto-replies once per sender per hour.",
    aliases=["!afk back"],
)
__CATEGORY__ = "Utilities"


#------------------------------
#State
#------------------------------

def _default():
    return {"global": None, "chats": {}, "cooldowns": {}, "pause_until": 0}


def load_state():
    """Never raises: an unreadable store means 'not AFK'."""
    try:
        state = load_store(AFK_FILE, SCHEMA_VERSION, _default)
    except Exception:  # noqa: BLE001
        log.exception("afk: could not read state, treating as off")
        return _default()
    for key, empty in (("chats", {}), ("cooldowns", {})):
        if not isinstance(state.get(key), dict):
            state[key] = empty
    return state


def save_state(state):
    try:
        save_json(AFK_FILE, state)
    except Exception:  # noqa: BLE001
        log.exception("afk: could not persist state")


def set_global(reason):
    state = load_state()
    state["global"] = {"reason": reason, "since": time.time()}
    save_state(state)
    return state["global"]


def set_chat(chat_id, reason):
    state = load_state()
    state["chats"][str(chat_id)] = {"reason": reason, "since": time.time()}
    save_state(state)
    return state["chats"][str(chat_id)]


def clear_scope(chat_id=None, everything=False):
    state = load_state()
    if everything:
        state["global"] = None
        state["chats"] = {}
    else:
        state["global"] = None
        if chat_id is not None:
            state["chats"].pop(str(chat_id), None)
    save_state(state)
    return state


def _cooldown_ok(state, chat_id, sender_id, now=None):
    now = now or time.time()
    key = f"{chat_id}:{sender_id}"
    last = float(state["cooldowns"].get(key, 0) or 0)
    return (now - last) >= COOLDOWN_SECONDS, key


def _mark_cooldown(state, key, now=None):
    state["cooldowns"][key] = now or time.time()
    save_state(state)


def _human_ago(seconds):
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


#------------------------------
#Scheduler job
#------------------------------

async def tick(client=None):
    """Expire old cooldowns and lift an automatic pause after a flood wait."""
    state = load_state()
    now = time.time()
    cutoff = now - (COOLDOWN_SECONDS * 2)
    stale = [key for key, stamp in state["cooldowns"].items() if float(stamp) < cutoff]
    changed = bool(stale)
    for key in stale:
        state["cooldowns"].pop(key, None)
    if state.get("pause_until") and float(state["pause_until"]) <= now:
        state["pause_until"] = 0
        changed = True
    if changed:
        save_state(state)


def setup(client, my_id):
    scheduler.register("afk", tick)

    def _reply_to_message(record):
        reason = record.get("reason") or DEFAULT_REASON
        since = float(record.get("since", time.time()))
        return (
            f"🤖 I'm AFK: {reason}\n"
            f"_Set {_human_ago(time.time() - since)}._"
        )

    # commands
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!afk(?:\s+([\s\S]*))?$"))
    async def afk_cmd(event):
        if not event.out or event.sender_id != my_id:
            return
        args = (event.pattern_match.group(1) or "").strip()
        head, _, rest = args.partition(" ")
        head_l = head.lower()
        rest = rest.strip()

        try:
            if not args:
                record = set_global(DEFAULT_REASON)
                await _say(event, f"💤 AFK on (global, DMs only).\n_{record['reason']}_")
                return

            if head_l == "off" or head_l == "back":
                everything = rest.lower() in ("all", "everywhere")
                clear_scope(event.chat_id, everything=everything)
                await _say(
                    event,
                    "✅ AFK cleared everywhere." if everything else "✅ AFK cleared.",
                )
                return

            if head_l == "status":
                state = load_state()
                lines = []
                g = state.get("global")
                if g:
                    lines.append(
                        f"💤 Global AFK: {g['reason']} "
                        f"({_human_ago(time.time() - float(g['since']))})"
                    )
                else:
                    lines.append("Global AFK: off")
                mine = state["chats"].get(str(event.chat_id))
                if mine:
                    lines.append(
                        f"Here: {mine['reason']} "
                        f"({_human_ago(time.time() - float(mine['since']))})"
                    )
                else:
                    lines.append("Here: off")
                if state.get("pause_until"):
                    left = float(state["pause_until"]) - time.time()
                    if left > 0:
                        lines.append(f"⏳ Auto-replies paused by a flood wait ({int(left)}s left)")
                await _say(event, "\n".join(lines))
                return

            if head_l == "list":
                state = load_state()
                lines = []
                if state.get("global"):
                    g = state["global"]
                    lines.append(f"• global (DMs): {g['reason']}")
                for chat_id, record in state["chats"].items():
                    lines.append(
                        f"• chat `{chat_id}`: {record.get('reason')} "
                        f"({_human_ago(time.time() - float(record.get('since', 0)))})"
                    )
                lines.append(f"• active cooldowns: {len(state['cooldowns'])}")
                if not state.get("global") and not state["chats"]:
                    lines.insert(0, "📭 No AFK entries.")
                await _say(event, "\n".join(lines))
                return

            if head_l == "here":
                record = set_chat(event.chat_id, rest or DEFAULT_REASON)
                await _say(
                    event,
                    f"💤 AFK on for this chat only.\n_{record['reason']}_",
                )
                return

            record = set_global(args)
            await _say(event, f"💤 AFK on (global, DMs only).\n_{record['reason']}_")

        except Exception:  # noqa: BLE001
            log.exception("afk: command failed")
            await _say(event, "❌ AFK command failed; see the Replit log.")

    # auto-reply to incoming DMs
    @client.on(events.NewMessage(incoming=True))
    async def auto_reply(event):
        try:
            if event.out or not event.is_private:
                return
            sender = await event.get_sender()
            if sender is None or getattr(sender, "bot", False):
                return  # never answer bots

            state = load_state()
            if float(state.get("pause_until", 0) or 0) > time.time():
                return

            record = state.get("global")
            if record is None:
                return  # groups and un-opted chats stay silent

            allowed, key = _cooldown_ok(state, event.chat_id, event.sender_id)
            if not allowed:
                return

            await client.send_message(await tgsend.peer(event), _reply_to_message(record))
            _mark_cooldown(state, key)

        except flood.FLOOD_ERRORS as exc:
            # Obey FLOOD_WAIT once: stop replying globally
            state = load_state()
            state["pause_until"] = time.time() + exc.seconds
            save_state(state)
            log.warning("afk: flood wait %ss, auto-replies paused", exc.seconds)
        except (errors.UserIsBlockedError, errors.InputUserDeactivatedError) as exc:
            log.info("afk: cannot reply to that user (%s)", type(exc).__name__)
        except Exception:  # noqa: BLE001
            log.exception("afk: auto-reply failed")

    # auto-clear when the owner answers
    @client.on(events.NewMessage(outgoing=True))
    async def auto_clear(event):
        try:
            if not event.out or event.sender_id != my_id:
                return
            text = event.raw_text or ""
            if text.startswith("!"):
                return  # commands must not clear the state they just set

            state = load_state()
            changed = False
            if state.get("global"):
                state["global"] = None
                changed = True
            if state["chats"].pop(str(event.chat_id), None) is not None:
                changed = True
            if changed:
                save_state(state)
                log.info("afk: cleared because the owner wrote in %s", event.chat_id)
        except Exception:  # noqa: BLE001
            log.exception("afk: auto-clear failed")

    async def _say(event, text):
        # Com/core/reply.py
        await say(event, text, name="afk")
