"""`!remind` -- durable reminders driven by the shared scheduler.

Durability model
----------------
Every reminder is stored with an absolute UTC epoch (``due_at``) in
``mode/reminders.json``. Nothing is held in an ``asyncio.sleep`` task, so:

* a Repl restart or sleep loses nothing;
* the single scheduler tick (``Com/core/scheduler.py``) notices overdue items and
  delivers them, prefixing anything that came due while the bot was offline
  with "missed while offline" instead of dropping it silently.

Delivery target
---------------
Reminders go to **Saved Messages** (`client.send_message('me', ...)`) because a
self-bot's reminders are for its owner. `!remind here …` delivers to the chat the
command was typed in instead.

Timezones
---------
`!remind at` needs the owner's timezone. It comes from `OWNER_TZ` (env) or from
`!remind tz <zone>` (stored in `mode/settings.json`). If neither is set the
command fails with instructions -- it never assumes UTC.
"""
import logging
import random
import time
from datetime import datetime, timedelta

import pytz
from telethon import events

import Com.core.registry as registry
from Com.core import confirm, scheduler
from Com.core.durations import format_duration, parse_duration
from Com.core.storage import load_store, save_json

log = logging.getLogger("selftg.remind")

REMINDER_FILE = "mode/reminders.json"
SETTINGS_FILE = "mode/settings.json"
SCHEMA_VERSION = 1
MAX_REMINDERS = 200
MAX_TEXT = 400
MIN_DELAY = 5
MAX_DELAY = 365 * 86400
LATE_GRACE = 60  # seconds of clock skew before "missed while offline" applies

SUBCOMMANDS = [
    ("!remind <duration> <text>", "one-shot reminder to Saved Messages"),
    ("!remind here <duration> <text>", "reminder to this chat instead"),
    ("!remind at <HH:MM> [YYYY-MM-DD] <text>", "absolute time in your timezone"),
    ("!remind at here <HH:MM> [YYYY-MM-DD] <text>", "same, delivered here"),
    ("!remind list", "pending reminders with ids and due times"),
    ("!remind cancel <id>", "cancel one reminder"),
    ("!remind clear", "cancel everything (asks for a token)"),
    ("!remind tz <zone>", "show or set your timezone (e.g. Asia/Tehran)"),
]

__HELP__ = registry.command(
    "remind", SUBCOMMANDS,
    "Durable reminders; stored on disk, delivered by the shared scheduler.",
    aliases=["!remind del <id>"],
)
__CATEGORY__ = "Utilities"

ACTION_CLEAR = "!remind clear"


#------------------------------
#State
#------------------------------

def _default():
    return {"next_id": 1, "items": []}


def _migrate_v2(raw):
    """v2 stored a bare list: [{id, chat_id, text, created, due}]."""
    items = []
    highest = 0
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        try:
            item = {
                "id": int(entry.get("id") or 0),
                "text": str(entry.get("text") or ""),
                "due_at": float(entry.get("due") or 0),
                "created_at": float(entry.get("created") or 0),
                "chat_id": entry.get("chat_id"),
            }
        except (TypeError, ValueError):
            continue
        highest = max(highest, item["id"])
        items.append(item)
    return {"next_id": highest + 1, "items": items}


def load_state():
    try:
        state = load_store(
            REMINDER_FILE, SCHEMA_VERSION, _default, migrations={0: _migrate_v2}
        )
    except Exception:  # noqa: BLE001
        log.exception("remind: could not read the store, starting empty")
        return _default()
    if not isinstance(state.get("items"), list):
        state["items"] = []
    state.setdefault("next_id", 1)
    return state


def save_state(state):
    try:
        save_json(REMINDER_FILE, state)
        return True
    except Exception:  # noqa: BLE001
        log.exception("remind: could not write the store")
        return False


def load_settings():
    try:
        data = load_store(SETTINGS_FILE, 1, lambda: {})
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(data):
    try:
        save_json(SETTINGS_FILE, data)
    except Exception:  # noqa: BLE001
        log.exception("remind: could not write settings")


def owner_timezone():
    """Return (tzinfo, name) or (None, None) when nothing is configured."""
    import os

    name = (os.getenv("OWNER_TZ") or "").strip() or load_settings().get("timezone")
    if not name:
        return None, None
    try:
        return pytz.timezone(name), name
    except Exception:  # noqa: BLE001
        log.warning("remind: invalid timezone %r", name)
        return None, None


def _fmt_due(ts, tz):
    if tz is not None:
        try:
            return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M %Z")
        except Exception:  # noqa: BLE001
            pass
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))


#------------------------------
#Scheduler job
#------------------------------

async def tick(client):
    """Deliver every reminder whose due_at has passed."""
    state = load_state()
    now = time.time()
    due = [item for item in state["items"] if float(item.get("due_at", 0)) <= now]
    if not due:
        return

    remaining = [item for item in state["items"] if item not in due]
    state["items"] = remaining
    save_state(state)

    startup = scheduler.started_at() or now
    tz, _ = owner_timezone()

    for item in due:
        due_at = float(item.get("due_at", 0))
        late = due_at < (startup - LATE_GRACE)
        prefix = (
            f"⏰ **Missed while offline** (was due {_fmt_due(due_at, tz)})\n"
            if late
            else "⏰ **Reminder**\n"
        )
        target = item.get("chat_id") or "me"
        try:
            await client.send_message(target, f"{prefix}{item.get('text', '')}")
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "remind: could not deliver #%s to %s (%s)",
                item.get("id"), target, type(exc).__name__,
            )


#------------------------------
#Parsing helpers
#------------------------------

def parse_at_time(tokens, tz):
    """'18:30 [YYYY-MM-DD] rest…' -> (due_epoch, text). Raises ValueError."""
    if tz is None:
        raise ValueError(
            "no timezone configured — set OWNER_TZ in Replit Secrets or run "
            "`!remind tz Asia/Tehran` first"
        )
    if not tokens:
        raise ValueError("usage: !remind at <HH:MM> [YYYY-MM-DD] <text>")

    raw_time = tokens[0]
    try:
        hour, minute = (int(part) for part in raw_time.split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError(f"{raw_time!r} is not a time like 18:30") from None

    index = 1
    date_part = None
    if len(tokens) > 1 and "-" in tokens[1] and len(tokens[1]) >= 8:
        date_part = tokens[1]
        index = 2

    now = datetime.now(tz)
    if date_part:
        try:
            year, month, day = (int(part) for part in date_part.split("-"))
            naive = datetime(year, month, day, hour, minute)
        except (ValueError, TypeError):
            raise ValueError(f"{date_part!r} is not a date like 2026-11-20") from None
    else:
        naive = datetime(now.year, now.month, now.day, hour, minute)
        if naive < now.replace(tzinfo=None):
            naive += timedelta(days=1)  # "at 09:00" means tomorrow if it has passed

    try:
        due = tz.localize(naive, is_dst=None)
    except Exception:
        raise ValueError("that local time is ambiguous or does not exist in your timezone") from None

    text = " ".join(tokens[index:]).strip()
    if not text:
        raise ValueError("what should I remind you about?")
    return due.timestamp(), text


def setup(client, my_id):
    scheduler.register("remind", tick)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!remind(?:\s+([\s\S]*))?$"))
    async def remind_cmd(event):
        if not event.out or event.sender_id != my_id:
            return

        args = (event.pattern_match.group(1) or "").strip()
        if not args:
            await _say(event, "📖 " + __HELP__)
            return

        head, _, rest = args.partition(" ")
        sub = head.lower()
        rest = rest.strip()

        try:
            if sub == "list":
                await _cmd_list(event)
            elif sub in ("cancel", "del", "delete", "rm"):
                await _cmd_cancel(event, rest)
            elif sub == "clear":
                await _cmd_clear(event, rest)
            elif sub == "tz":
                await _cmd_tz(event, rest)
            elif sub == "at":
                await _cmd_at(event, rest)
            elif sub == "here":
                await _cmd_duration(event, rest, here=True)
            else:
                await _cmd_duration(event, args, here=False)
        except Exception:  # noqa: BLE001
            log.exception("remind: command failed")
            await _say(event, "❌ Reminder command failed; see the Replit log.")

    async def _cmd_duration(event, args, here):
        duration_raw, _, text = args.partition(" ")
        if not duration_raw:
            await _say(event, "Usage: `!remind <10m|2h|1d> <text>`")
            return
        try:
            seconds = parse_duration(duration_raw, minimum=MIN_DELAY, maximum=MAX_DELAY)
        except ValueError as exc:
            await _say(event, f"❌ {exc}")
            return
        if not text.strip():
            await _say(event, "Usage: `!remind <duration> <text>` — e.g. `!remind 10m tea`")
            return
        await _store(event, seconds, text.strip(), here)

    async def _cmd_at(event, rest):
        tokens = rest.split()
        here = False
        if tokens and tokens[0].lower() == "here":
            here = True
            tokens = tokens[1:]
        tz, tz_name = owner_timezone()
        try:
            due_at, text = parse_at_time(tokens, tz)
        except ValueError as exc:
            await _say(event, f"❌ {exc}")
            return
        delay = due_at - time.time()
        if delay < 0:
            await _say(event, "❌ That time is in the past.")
            return
        await _store(event, None, text, here, due_at=due_at, tz_used=tz_name)

    async def _store(event, seconds, text, here, due_at=None, tz_used=None):
        state = load_state()
        if len(state["items"]) >= MAX_REMINDERS:
            await _say(event, f"❌ {MAX_REMINDERS} reminders are already pending.")
            return

        if due_at is None:
            due_at = time.time() + seconds
        item_id = int(state["next_id"])
        state["next_id"] = item_id + 1
        state["items"].append({
            "id": item_id,
            "text": text[:MAX_TEXT],
            "due_at": due_at,
            "created_at": time.time(),
            "chat_id": event.chat_id if here else None,
        })
        if not save_state(state):
            await _say(event, "❌ Could not save the reminder (storage unavailable).")
            return

        tz, _ = owner_timezone()
        when = _fmt_due(due_at, tz)
        left = max(0, due_at - time.time())
        where = "this chat" if here else "Saved Messages"
        extra = f" · timezone {tz_used}" if tz_used else ""
        await _say(
            event,
            f"⏰ Reminder `#{item_id}` in {format_duration(left)} ({when}) → {where}{extra}\n"
            f"_{text[:120]}_",
        )

    async def _cmd_list(event):
        state = load_state()
        if not state["items"]:
            await _say(event, "📭 No pending reminders.")
            return
        tz, _ = owner_timezone()
        lines = ["⏰ **Pending reminders**"]
        for item in sorted(state["items"], key=lambda entry: float(entry.get("due_at", 0))):
            left = max(0, float(item["due_at"]) - time.time())
            where = "here" if item.get("chat_id") else "Saved Messages"
            lines.append(
                f"• `#{item['id']}` in {format_duration(left)} "
                f"({_fmt_due(float(item['due_at']), tz)}, {where}) — {item.get('text', '')[:80]}"
            )
        await _say(event, "\n".join(lines))

    async def _cmd_cancel(event, rest):
        raw = rest.strip().lstrip("#")
        if not raw.isdigit():
            await _say(event, "Usage: `!remind cancel <id>` (see `!remind list`)")
            return
        target = int(raw)
        state = load_state()
        kept = [item for item in state["items"] if int(item.get("id", -1)) != target]
        if len(kept) == len(state["items"]):
            await _say(event, f"❌ No pending reminder `#{target}`.")
            return
        state["items"] = kept
        save_state(state)
        await _say(event, f"✅ Reminder `#{target}` cancelled.")

    async def _cmd_clear(event, rest):
        if confirm.check(event.chat_id, ACTION_CLEAR, rest):
            state = load_state()
            count = len(state["items"])
            state["items"] = []
            save_state(state)
            await _say(event, f"🗑️ Cancelled {count} reminder(s).")
            return
        if rest.strip().lower().startswith("confirm"):
            await _say(event, "❌ Wrong or expired token. Run `!remind clear` again.")
            return
        prompt = confirm.request(
            event.chat_id, ACTION_CLEAR, "This cancels every pending reminder."
        )
        await _say(event, prompt)

    async def _cmd_tz(event, rest):
        if not rest:
            tz, name = owner_timezone()
            await _say(
                event,
                f"🕐 Timezone: `{name}`" if tz else
                "🕐 No timezone set. Use `!remind tz Asia/Tehran` or set OWNER_TZ.",
            )
            return
        try:
            pytz.timezone(rest)
        except Exception:  # noqa: BLE001
            await _say(event, f"❌ `{rest}` is not a known timezone (e.g. Asia/Tehran, Europe/Berlin).")
            return
        settings = load_settings()
        settings["timezone"] = rest
        settings.setdefault("_version", 1)
        save_settings(settings)
        await _say(event, f"🕐 Timezone set to `{rest}`.")

    async def _say(event, text):
        try:
            await event.edit(text)
        except Exception:
            try:
                await event.reply(text)
            except Exception:
                log.info("remind: response could not be delivered")
