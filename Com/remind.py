# Com/remind.py
"""`!remind` -- one-shot reminders that survive Replit sleep and restarts.

No external API is involved at all: this is pure local scheduling, so there is no
quota, no key and nothing to be rate limited. Reminders live in
``mode/reminders.json`` with an absolute due timestamp, so a reminder set for
"2h" still fires 2h later even if the Repl slept or restarted in between (if the
process was asleep past the due time it fires as soon as it comes back).

The loop is a single background task that wakes every 15s, which costs
essentially nothing on Replit's CPU budget.
"""
import asyncio
import logging
import os
import re
import time

from telethon import events

from Com.storage import load_json, save_json

__HELP__ = (
    "!remind <duration> <text> → Ping this chat after the duration, e.g. 10m, 2h, 1d\n"
    "!remind list → Show pending reminders for this chat\n"
    "!remind del <id> → Cancel one reminder\n"
    "Reminders are stored on disk and survive restarts and Replit sleep."
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.remind")

REMINDER_FILE = "mode/reminders.json"
os.makedirs("mode", exist_ok=True)

TICK_SECONDS = 15
MAX_PER_CHAT = 50
MAX_TEXT = 400

UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)

_loop_task = None


# ------------------------------
# Pure helpers
# ------------------------------
def parse_delay(text):
    """'45s', '10m', '2h', '1d12h' -> seconds (5s .. 365d). Raises ValueError."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("no duration given")

    total = 0
    position = 0
    for match in _DURATION_RE.finditer(raw):
        if match.start() != position:
            raise ValueError(f"could not read {raw!r}; use forms like 10m, 2h, 1d")
        total += int(match.group(1)) * UNIT_SECONDS[match.group(2).lower()]
        position = match.end()

    if position != len(raw) or total <= 0:
        raise ValueError(f"could not read {raw!r}; use forms like 10m, 2h, 1d")
    if total < 5:
        raise ValueError("minimum reminder delay is 5s")
    if total > 365 * 86400:
        raise ValueError("maximum reminder delay is 365 days")
    return total


def format_delay(seconds):
    seconds = int(max(0, seconds))
    parts = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            value, seconds = divmod(seconds, size)
            parts.append(f"{value}{unit}")
    return " ".join(parts) or "0s"


def load_all():
    data = load_json(REMINDER_FILE, [])
    return data if isinstance(data, list) else []


def save_all(items):
    save_json(REMINDER_FILE, items)


def add_reminder(chat_id, text, seconds):
    items = load_all()
    mine = [item for item in items if item.get("chat_id") == chat_id]
    if len(mine) >= MAX_PER_CHAT:
        raise ValueError(f"you already have {MAX_PER_CHAT} pending reminders in this chat")

    reminder_id = int(time.time() * 1000) % 10_000_000
    existing_ids = {item.get("id") for item in items}
    while reminder_id in existing_ids:
        reminder_id += 1

    entry = {
        "id": reminder_id,
        "chat_id": chat_id,
        "text": text[:MAX_TEXT],
        "created": time.time(),
        "due": time.time() + seconds,
    }
    items.append(entry)
    save_all(items)
    return entry


def remove_reminder(reminder_id, chat_id=None):
    items = load_all()
    kept, removed = [], None
    for item in items:
        if item.get("id") == reminder_id and (
            chat_id is None or item.get("chat_id") == chat_id
        ):
            removed = item
            continue
        kept.append(item)
    if removed:
        save_all(kept)
    return removed


def due_reminders(now=None):
    now = now or time.time()
    return [item for item in load_all() if float(item.get("due", 0)) <= now]


# ------------------------------
# Scheduler
# ------------------------------
async def _scheduler(client):
    """Deliver due reminders forever; never let one failure kill the loop."""
    while True:
        try:
            due = due_reminders()
            if due:
                items = load_all()
                remaining = [item for item in items if item not in due]
                save_all(remaining)
                for item in due:
                    try:
                        await client.send_message(
                            item["chat_id"],
                            f"⏰ **Reminder** (#{item['id']})\n{item['text']}",
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "remind: could not deliver #%s (%s)",
                            item.get("id"), type(exc).__name__,
                        )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("remind: scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)


def setup(client, my_id):
    global _loop_task
    try:
        _loop_task = asyncio.create_task(_scheduler(client), name="selftg-reminders")
    except RuntimeError:  # no running loop (import-only smoke test)
        _loop_task = None

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!remind(?:\s+([\s\S]*))?$"))
    async def remind_cmd(event):
        args = (event.pattern_match.group(1) or "").strip()
        if not args:
            await _safe_edit(event, "📖 **Reminders**\n" + __HELP__)
            return

        head, _, rest = args.partition(" ")
        sub = head.lower()

        if sub == "list":
            mine = [item for item in load_all() if item.get("chat_id") == event.chat_id]
            if not mine:
                await _safe_edit(event, "📭 No pending reminders in this chat.")
                return
            lines = ["⏰ **Pending reminders**"]
            for item in sorted(mine, key=lambda entry: entry["due"]):
                left = max(0, float(item["due"]) - time.time())
                lines.append(
                    f"• `#{item['id']}` in {format_delay(left)} — {item['text']}"
                )
            await _safe_edit(event, "\n".join(lines))
            return

        if sub == "del" or sub == "delete" or sub == "cancel":
            raw_id = rest.strip().lstrip("#")
            if not raw_id.isdigit():
                await _safe_edit(event, "Usage: `!remind del <id>` (see `!remind list`)")
                return
            removed = remove_reminder(int(raw_id), event.chat_id)
            if not removed:
                await _safe_edit(event, f"❌ No reminder `#{raw_id}` in this chat.")
                return
            await _safe_edit(event, f"✅ Reminder `#{raw_id}` cancelled.")
            return

        # `!remind 10m text`
        seconds_text, _, text = rest.partition(" ")
        try:
            seconds = parse_delay(seconds_text)
        except ValueError as exc:
            await _safe_edit(event, f"❌ {exc}")
            return
        if not text.strip():
            await _safe_edit(event, "Usage: `!remind <duration> <text>` — e.g. `!remind 10m tea`")
            return

        try:
            entry = add_reminder(event.chat_id, text.strip(), seconds)
        except ValueError as exc:
            await _safe_edit(event, f"❌ {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("remind: could not store reminder")
            await _safe_edit(event, f"❌ Could not save the reminder: {type(exc).__name__}")
            return

        deliver_at = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(entry["due"])
        )
        await _safe_edit(
            event,
            f"⏰ Reminder `#{entry['id']}` set for {format_delay(seconds)} from now "
            f"(~{deliver_at} local time).",
        )

    async def _safe_edit(event, text):
        try:
            await event.edit(text)
        except Exception:
            try:
                await event.reply(text)
            except Exception:
                log.info("remind: response could not be delivered")
