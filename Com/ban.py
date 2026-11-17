# Com/ban.py
"""`!ban` family: permanent bans, temporary bans, kicks, unbans and lookups.

Design notes
------------
* Banning is done with ``client.edit_permissions(..., view_messages=False)``.
  There is no separate "ban" request in MTProto -- ``channels.editBanned`` with
  ``view_messages=True`` (i.e. *forbidden*) is what bans; ``until_date`` is the
  only per-user expiry mechanism Telegram offers.
* Telethon's ``edit_permissions`` raises
  ``ValueError('You must pass either a channel or a supergroup')`` for basic
  groups. Telegram's API genuinely cannot ban one member of a basic group (it
  only exposes chat-wide default permissions), so this module refuses with an
  explanation instead of pretending the ban worked.
* Telegram itself enforces temporary bans through ``until_date``, so a tempban
  keeps working while Replit sleeps or after a restart. ``mode/bans.json`` is
  only the bot's own ledger for ``!ban list`` / ``!ban info``; it is never used
  to re-apply a ban, because re-applying on boot would resurrect bans you had
  already lifted in the Telegram UI.
* Telegram treats an ``until_date`` shorter than 30 seconds (or longer than 366
  days) as *permanent*, so ``MIN_TEMPBAN_SECONDS`` is 60 for safety.
* Every handler is owner-only twice over: registered with
  ``from_users=my_id`` and guarded again inside the handler with
  ``event.out`` + ``event.sender_id == my_id``. That is the project's existing
  policy -- there is no "other admins may ban" path, and this change does not
  introduce one.
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from telethon import errors, events
from telethon.tl.types import Channel, Chat

from Com.durations import format_duration, looks_like_duration
from Com.durations import parse_duration as shared_parse_duration
from Com.storage import load_json, save_json

__HELP__ = (
    "!ban <user> [reason] → Permanently ban a user (reply or @username/ID)\n"
    "!ban temp <user> <duration> [reason] → Temporary ban, e.g. 10m, 2h, 7d\n"
    "!ban unban <user> [reason] → Lift a ban\n"
    "!ban kick <user> [reason] → Ban then immediately unban (they may rejoin)\n"
    "!ban list → Active bans tracked for this chat\n"
    "!ban info <user> → Ban status plus tracked reason/expiry\n"
    "Works in supergroups and channels where the account is admin."
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.ban")

BASE_DIR = "mode"
BAN_FILE = os.path.join(BASE_DIR, "bans.json")
os.makedirs(BASE_DIR, exist_ok=True)

# Telegram: until_date < 30s is treated as forever; > 366 days is also forever.
MIN_TEMPBAN_SECONDS = 60
MAX_TEMPBAN_SECONDS = 366 * 24 * 3600

class BanUnsupported(Exception):
    """The chat type or the account's rights make this action impossible."""


# ------------------------------
# Durations
# ------------------------------
# The grammar lives in Com/durations.py and is shared with !remind: one parser,
# one set of error messages, no duplicated regex. Only the bounds differ, because
# Telegram turns a ban shorter than 30s (or longer than 366 days) into a
# permanent one.
def parse_duration(text):
    """Parse a ban duration into seconds, enforcing 60s .. 366d."""
    try:
        return shared_parse_duration(
            text, minimum=MIN_TEMPBAN_SECONDS, maximum=MAX_TEMPBAN_SECONDS
        )
    except ValueError as exc:
        message = str(exc)
        if "minimum" in message:
            message += " (Telegram treats bans under 30s as permanent)"
        raise ValueError(message) from None


def _is_duration(text):
    return looks_like_duration(text)


def _utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ------------------------------
# Ledger
# ------------------------------
def _load_all():
    data = load_json(BAN_FILE, {})
    return data if isinstance(data, dict) else {}


def load_bans(chat_id):
    """Tracked bans for one chat: {user_id_str: entry}. Prunes expired ones."""
    data = _load_all()
    chat_key = str(chat_id)
    entries = data.get(chat_key)
    if not isinstance(entries, dict):
        return {}

    now = time.time()
    kept = {}
    for uid, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        until = entry.get("until")
        if until and float(until) <= now:
            continue  # Telegram already lifted it
        kept[uid] = entry

    if kept != entries:
        data[chat_key] = kept
        save_json(BAN_FILE, data)
    return kept


def save_ban(chat_id, user_id, *, kind, reason, until=None):
    data = _load_all()
    chat_key = str(chat_id)
    entries = data.get(chat_key)
    if not isinstance(entries, dict):
        entries = {}
    entries[str(user_id)] = {
        "kind": kind,
        "reason": reason or "no reason given",
        "since": time.time(),
        "until": until,
    }
    data[chat_key] = entries
    save_json(BAN_FILE, data)


def drop_ban(chat_id, user_id):
    """Remove a tracked ban and return the entry that was removed."""
    data = _load_all()
    chat_key = str(chat_id)
    entries = data.get(chat_key) or {}
    entry = entries.pop(str(user_id), None)
    data[chat_key] = entries
    save_json(BAN_FILE, data)
    return entry


# ------------------------------
# Error text
# ------------------------------
def describe_error(exc):
    """Turn a Telethon/OS error into one actionable line."""
    if isinstance(exc, BanUnsupported):
        return str(exc)
    if isinstance(exc, ValueError) and "channel or a supergroup" in str(exc):
        return (
            "this chat is a basic group; Telegram's API only allows banning "
            "individual members in supergroups and channels. Convert the group "
            "to a supergroup first."
        )
    if isinstance(exc, errors.ChatAdminRequiredError):
        return "the account is not an admin here (or lacks the 'ban users' right)."
    if isinstance(exc, errors.UserAdminInvalidError):
        return "Telegram refuses this: the target is an admin/owner, or your admin rights are insufficient."
    if isinstance(exc, errors.ChannelInvalidError):
        return "Telegram says this chat ID is invalid; try again from inside the chat."
    if isinstance(exc, errors.UserIdInvalidError):
        return "Telegram rejected that user ID."
    if isinstance(exc, errors.PeerIdInvalidError):
        return "could not resolve that user; reply to one of their messages instead."
    if isinstance(exc, errors.UserNotParticipantError):
        return "that user is not a participant of this chat."
    if isinstance(exc, errors.ChatWriteForbiddenError):
        return "the account cannot post in this chat any more."
    if isinstance(exc, errors.ChannelPrivateError):
        return "this chat is private or the account was removed from it."
    if isinstance(exc, errors.FloodWaitError):
        return f"Telegram rate limit: wait {exc.seconds}s before trying again."
    if isinstance(exc, errors.RPCError):
        return f"Telegram error: {type(exc).__name__}: {exc}"
    return f"{type(exc).__name__}: {exc}"


# ------------------------------
# Command
# ------------------------------
HELP_TEXT = (
    "🛑 **Ban commands**\n"
    "• `!ban <user> [reason]` — permanent ban\n"
    "• `!ban temp <user> <10m|2h|7d> [reason]` — temporary ban\n"
    "• `!ban unban <user> [reason]` — lift a ban\n"
    "• `!ban kick <user> [reason]` — ban then unban\n"
    "• `!ban list` — bans tracked in this chat\n"
    "• `!ban info <user>` — live status + tracked details\n"
    "_<user>_ is a reply, @username or numeric ID. Supergroups/channels only."
)


def setup(client, my_id):

    async def _say(event, text):
        """Edit the command message in place, falling back to a reply."""
        try:
            await event.edit(text)
        except Exception:
            try:
                await event.reply(text)
            except Exception:
                log.info("could not deliver ban response: %s", text.splitlines()[0])

    async def _chat(event):
        chat = await event.get_chat()
        if isinstance(chat, Chat):
            raise BanUnsupported(
                "this is a basic group; Telegram's API only allows banning "
                "individual members in supergroups and channels. Convert the "
                "group to a supergroup and retry."
            )
        if not isinstance(chat, Channel):
            raise BanUnsupported("this is not a group or channel, so there is nobody to ban.")
        return chat

    async def _resolve(event, token):
        """Resolve a reply / @username / numeric ID into (entity, id)."""
        token = (token or "").strip()
        if not token:
            if event.is_reply:
                reply = await event.get_reply_message()
                if reply and reply.sender_id:
                    return await client.get_entity(reply.sender_id), reply.sender_id
            raise BanUnsupported(
                "who? reply to their message, or pass @username / numeric ID."
            )
        if token.isdigit() or (token.startswith("-") and token[1:].isdigit()):
            user_id = int(token)
            return await client.get_entity(user_id), user_id
        entity = await client.get_entity(token.lstrip("@"))
        user_id = getattr(entity, "id", None)
        if user_id is None:
            raise BanUnsupported(f"could not resolve {token!r} to a user.")
        return entity, user_id

    async def _label(entity, user_id):
        username = getattr(entity, "username", None)
        name = " ".join(
            part for part in (getattr(entity, "first_name", None),
                              getattr(entity, "last_name", None)) if part
        )
        if username:
            return f"@{username}"
        if name:
            return f"{name} (ID {user_id})"
        return f"ID {user_id}"

    async def _live_state(chat, entity):
        """True/False = Telegram's current view, None = could not check."""
        try:
            permissions = await client.get_permissions(chat, entity)
        except errors.UserNotParticipantError:
            return False, "not a participant"
        except Exception as exc:  # noqa: BLE001 - status display must not fail
            return None, f"could not query ({type(exc).__name__})"
        view_messages = getattr(permissions, "view_messages", None)
        if view_messages is None:
            return None, "Telegram did not report view_messages"
        return (view_messages is False), "banned" if view_messages is False else "not banned"

    # ---------- subcommands ----------
    async def cmd_ban(event, token, rest, kind="ban"):
        chat = await _chat(event)
        entity, user_id = await _resolve(event, token)
        name = await _label(entity, user_id)
        reason = rest.strip() or "no reason given"

        if kind == "temp":
            duration_raw, _, reason = rest.strip().partition(" ")
            seconds = parse_duration(duration_raw)
            reason = reason.strip() or "no reason given"
            until = time.time() + seconds
            await client.edit_permissions(
                chat, entity, until_date=timedelta(seconds=seconds),
                view_messages=False,
            )
            save_ban(chat.id, user_id, kind="tempban", reason=reason, until=until)
            await _say(
                event,
                f"⏳ **Temporary ban** — {name}\n"
                f"Duration: {format_duration(seconds)}\n"
                f"Expires: {_utc(until)}\n"
                f"Reason: {reason}\n"
                "Telegram enforces the expiry itself, so it survives restarts.",
            )
            return

        await client.edit_permissions(chat, entity, view_messages=False)
        save_ban(chat.id, user_id, kind="ban", reason=reason)
        await _say(
            event,
            f"🛑 **Banned** — {name}\nReason: {reason}",
        )

    async def cmd_unban(event, token, rest):
        chat = await _chat(event)
        entity, user_id = await _resolve(event, token)
        name = await _label(entity, user_id)

        tracked = drop_ban(chat.id, user_id)
        await client.edit_permissions(chat, entity)  # all rights back to default
        reason = rest.strip() or (tracked or {}).get("reason")
        suffix = f"\n(was: {reason})" if reason else ""
        await _say(event, f"✅ **Unbanned** — {name}{suffix}")

    async def cmd_kick(event, token, rest):
        chat = await _chat(event)
        entity, user_id = await _resolve(event, token)
        name = await _label(entity, user_id)
        reason = rest.strip() or "no reason given"

        # Kick == ban immediately followed by an unban. Telegram drops the
        # member on the first call and the second restores their rights, so they
        # can be re-invited (but are not auto-rejoined).
        await client.edit_permissions(chat, entity, view_messages=False)
        await client.edit_permissions(chat, entity)
        drop_ban(chat.id, user_id)
        await _say(event, f"👢 **Kicked** — {name}\nReason: {reason}")

    async def cmd_list(event):
        chat = await _chat(event)
        entries = load_bans(chat.id)
        if not entries:
            await _say(event, "📭 No bans tracked for this chat.")
            return

        lines = ["📋 **Bans tracked for this chat** (Telegram enforces them):"]
        for user_id, entry in sorted(entries.items(), key=lambda kv: kv[1].get("since", 0)):
            try:
                entity = await client.get_entity(int(user_id))
                name = await _label(entity, int(user_id))
            except Exception:
                name = f"ID {user_id}"
            if entry.get("until"):
                when = f"until {_utc(float(entry['until']))}"
            else:
                when = "permanent"
            lines.append(f"• {name} — {when} — {entry.get('reason', 'no reason given')}")
            if len(lines) >= 40:
                lines.append("• … (truncated)")
                break
        await _say(event, "\n".join(lines))

    async def cmd_info(event, token):
        chat = await _chat(event)
        entity, user_id = await _resolve(event, token)
        name = await _label(entity, user_id)

        tracked = load_bans(chat.id).get(str(user_id))
        banned, state = await _live_state(chat, entity)

        lines = [f"🔎 **Ban info** — {name}", f"Telegram says: {state}"]
        if tracked:
            lines.append(f"Tracked: {tracked.get('kind', 'ban')}")
            lines.append(f"Reason: {tracked.get('reason', 'no reason given')}")
            if tracked.get("since"):
                lines.append(f"Since: {_utc(float(tracked['since']))}")
            if tracked.get("until"):
                remaining = float(tracked["until"]) - time.time()
                lines.append(
                    f"Expires: {_utc(float(tracked['until']))} "
                    f"({format_duration(remaining)} left)"
                )
            else:
                lines.append("Expires: never")
        else:
            lines.append("Tracked: no record (ban may predate the bot or be manual)")
        if banned is False and tracked:
            lines.append("⚠️ Not currently restricted; `!ban list` will drop this entry.")
        await _say(event, "\n".join(lines))

    # ---------- router ----------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!ban(?:\s+([\s\S]*))?$"))
    async def ban_router(event):
        # Second owner check: `from_users` is per-client state, this is per-event.
        if not event.out or event.sender_id != my_id:
            return

        args = (event.pattern_match.group(1) or "").strip()
        try:
            if not args:
                await _say(event, HELP_TEXT)
                return

            head, _, rest = args.partition(" ")
            sub = head.lower()

            if sub == "list":
                await cmd_list(event)
                return
            if sub == "temp":
                token, _, remainder = rest.strip().partition(" ")
                if not token:
                    await _say(event, "Usage: `!ban temp <user> <10m|2h|7d> [reason]`")
                    return
                # Reply form: `!ban temp 10m spamming` in reply to the target.
                # The first word is a duration, so the target has to be the reply.
                if event.is_reply and _is_duration(token):
                    await cmd_ban(
                        event, "", token + (" " + remainder if remainder else ""),
                        kind="temp",
                    )
                    return
                if not remainder.strip():
                    await _say(event, "Usage: `!ban temp <user> <10m|2h|7d> [reason]`")
                    return
                await cmd_ban(event, token, remainder, kind="temp")
                return
            if sub == "unban":
                token, _, remainder = rest.strip().partition(" ")
                if not token:
                    await _say(event, "Usage: `!ban unban <user> [reason]`")
                    return
                await cmd_unban(event, token, remainder)
                return
            if sub == "kick":
                token, _, remainder = rest.strip().partition(" ")
                if not token:
                    await _say(event, "Usage: `!ban kick <user> [reason]`")
                    return
                await cmd_kick(event, token, remainder)
                return
            if sub == "info":
                token = rest.strip()
                if not token and not event.is_reply:
                    await _say(event, "Usage: `!ban info <user>`")
                    return
                await cmd_info(event, token)
                return

            # `!ban <user> [reason]`
            await cmd_ban(event, head, rest, kind="ban")

        except errors.FloodWaitError as exc:
            await _say(
                event,
                f"⏳ Telegram rate limit: wait {exc.seconds}s. "
                "The ban was not applied.",
            )
        except errors.RPCError as exc:
            log.warning("ban: RPC failure %s", type(exc).__name__)
            await _say(event, f"❌ {describe_error(exc)}")
        except (BanUnsupported, ValueError) as exc:
            await _say(event, f"❌ {describe_error(exc)}")
        except Exception as exc:  # noqa: BLE001 - a handler must never die silently
            log.exception("ban: unexpected failure")
            await _say(event, f"❌ {type(exc).__name__}: {exc}")
