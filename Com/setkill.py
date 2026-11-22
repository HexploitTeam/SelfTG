"""!setkill: send a message every N seconds until stopped, resumed after a restart."""
import os
import json
import asyncio
import logging
import random
from telethon import errors, events

from Com.core import brand, flood
from Com.core.reply import say
from Com.core.storage import save_json
import Com.core.tgsend as tgsend

__HELP__ = (
    "!setkill start <interval_seconds> [text] (reply optional) → Send a message every X seconds.\n"
    "   - If text is provided, that text is sent every interval.\n"
    "   - If no text, a random line from the main list is sent each time.\n"
    "   - If you reply to a message, the scheduled messages are replies to that message.\n"
    "   - Example: !setkill start 10 Hello (every 10s)\n"
    "   - Example: !setkill start 5 (random lines every 5s, reply to a message to reply to it)\n"
    "!setkill stop [id] → Stop the scheduled timer (by ID, or current chat if no ID).\n"
    "!setkill list → Show all active timers.\n"
    "!setkill status → Show info for the current chat's timer."
)
__CATEGORY__ = "Utilities"

BASE_DIR = "mode"
SETKILL_FILE = os.path.join(BASE_DIR, "setkill.json")
ELIST_FILE = os.path.join(BASE_DIR, "EList.json")
os.makedirs(BASE_DIR, exist_ok=True)

log = logging.getLogger("selftg.setkill")

active_timers = {}  # id -> asyncio.Task
timer_data = {}     # id -> settings

#------------------------------
#State
#------------------------------

def load_list():
    if not os.path.exists(ELIST_FILE):
        return []
    try:
        with open(ELIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def load_timers():
    if not os.path.exists(SETKILL_FILE):
        return {"next_id": 1, "timers": []}
    try:
        with open(SETKILL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"next_id": 1, "timers": []}

def save_timers(data):
    save_json(SETKILL_FILE, data)

#------------------------------
#Timer job
#------------------------------

async def run_timer(client, timer_id, chat_id, interval, text, reply_to):
    """Scheduled task that sends a message every `interval` seconds.

    The interval is jittered by ±15 %: a timer firing on exactly `interval` for
    hours is a machine-perfect pattern, which is what anti-spam looks at. While
    the shared breaker is open (see Com/core/flood.py) the timer pauses instead
    of sending into the penalty.
    """
    while True:
        await asyncio.sleep(max(1.0, interval * random.uniform(0.85, 1.15)))
        if timer_id not in active_timers:
            break

        left = flood.cooldown_left()
        if left:
            log.info("[setkill] timer %s paused for %ds (flood breaker)",
                     timer_id, left)
            await asyncio.sleep(min(left, 60))
            continue

        # Get text
        if text:
            msg_text = text
        else:
            lines = load_list()
            if lines:
                msg_text = random.choice(lines)["text"]
            else:
                msg_text = "(no texts available)"
        try:
            # Stored id: resolve per send (Com/core/tgsend.py)
            await client.send_message(await tgsend.resolve(client, chat_id),
                                      msg_text, reply_to=reply_to)
        except flood.FLOOD_ERRORS as exc:
            left = flood.note_flood(exc.seconds)
            log.warning("[setkill] timer %s hit FLOOD_WAIT %ss", timer_id, exc.seconds)
            if left:
                # Repeated floods stop the timer
                await stop_timer(timer_id)
                try:
                    await client.send_message(
                        await tgsend.resolve(client, chat_id), flood.describe(left))
                except Exception:  # noqa: BLE001 - the timer is already stopped
                    pass
                break
            await asyncio.sleep(min(exc.seconds, 300))
            continue
        except Exception as e:
            log.info("[setkill] timer %s stopped: %s", timer_id, e)
            # Failed send: stop the timer
            await stop_timer(timer_id)
            break

async def stop_timer(timer_id):
    """Cancel the task and remove from data."""
    if timer_id in active_timers:
        active_timers[timer_id].cancel()
        try:
            await active_timers[timer_id]
        except asyncio.CancelledError:
            pass
        del active_timers[timer_id]
    data = load_timers()
    data["timers"] = [t for t in data["timers"] if t["id"] != timer_id]
    save_timers(data)
    if timer_id in timer_data:
        del timer_data[timer_id]

#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    # Resume timers on startup
    async def resume_timers():
        data = load_timers()
        for t in data["timers"]:
            task = asyncio.create_task(
                run_timer(client, t["id"], t["chat_id"], t["interval"], t.get("text"), t.get("reply_to"))
            )
            active_timers[t["id"]] = task
            timer_data[t["id"]] = t

    asyncio.create_task(resume_timers())

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!setkill start\s+(\d+)(?:\s+(.+))?$"))
    async def setkill_start(event):
        try:
            interval = int(event.pattern_match.group(1))
            if interval < 1:
                await say(
                    event, "❌ Interval must be at least 1 second.", name="setkill"
                )
                return
            text = event.pattern_match.group(2)  # may be None
            if text:
                if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
                    text = text[1:-1]

            # Determine reply target
            reply_to = None
            if event.is_reply:
                reply_msg = await event.get_reply_message()
                reply_to = reply_msg.id

            # Create new timer
            data = load_timers()
            new_id = data["next_id"]
            data["next_id"] += 1
            timer_entry = {
                "id": new_id,
                "chat_id": event.chat_id,
                "interval": interval,
                "text": text,
                "reply_to": reply_to
            }
            data["timers"].append(timer_entry)
            save_timers(data)

            # Start the task
            task = asyncio.create_task(
                run_timer(client, new_id, event.chat_id, interval, text, reply_to)
            )
            active_timers[new_id] = task
            timer_data[new_id] = timer_entry

            await say(
                event,
                f"✅ <b>Timer started</b> · ID <code>{new_id}</code>\n"
                f"<b>Interval</b> · <code>{interval}s</code>\n"
                f"<b>Text</b> · {brand.esc(text or 'random')}",
                name="setkill",
                parse_mode="html",
            )
            await event.delete()
        except ValueError:
            await say(
                event,
                "❌ <b>Invalid interval.</b> Use "
                "<code>!setkill start &lt;seconds&gt; [text]</code>.",
                name="setkill",
                parse_mode="html",
            )
        except Exception as e:
            await say(
                event,
                f"❌ <b>Setkill failed.</b> {brand.esc(e)}",
                name="setkill",
                parse_mode="html",
            )

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!setkill stop(?:\s+(\d+))?$"))
    async def setkill_stop(event):
        timer_id = event.pattern_match.group(1)
        if timer_id:
            timer_id = int(timer_id)
            if timer_id not in active_timers:
                await say(
                    event,
                    f"❌ <b>Timer {timer_id} not found.</b>",
                    name="setkill",
                    parse_mode="html",
                )
                return
            await stop_timer(timer_id)
            await say(
                event,
                f"✅ <b>Timer stopped</b> · ID <code>{timer_id}</code>",
                name="setkill",
                parse_mode="html",
            )
            await event.delete()
        else:
            chat_id = event.chat_id
            data = load_timers()
            found = None
            for t in data["timers"]:
                if t["chat_id"] == chat_id:
                    found = t["id"]
                    break
            if found is None:
                await say(
                    event, "❌ No timer running for this chat.", name="setkill"
                )
                return
            await stop_timer(found)
            await say(
                event, "✅ <b>Timer for this chat stopped.</b>", name="setkill",
                parse_mode="html",
            )
            await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!setkill list$"))
    async def setkill_list(event):
        data = load_timers()
        if not data["timers"]:
            await say(event, "📭 No active timers.", name="setkill")
            return
        lines = ["📋 <b>Active Timers</b>"]
        for t in data["timers"]:
            lines.append(
                f"• <b>ID</b> <code>{t['id']}</code> · "
                f"<b>Chat</b> <code>{t['chat_id']}</code> · "
                f"<b>Interval</b> <code>{t['interval']}s</code>\n"
                f"  <b>Text</b> · {brand.esc(t.get('text') or 'random')} · "
                f"<b>Reply</b> · {brand.esc(t.get('reply_to') or 'No')}"
            )
        await say(event, "\n".join(lines), name="setkill", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!setkill status$"))
    async def setkill_status(event):
        chat_id = event.chat_id
        data = load_timers()
        found = None
        for t in data["timers"]:
            if t["chat_id"] == chat_id:
                found = t
                break
        if found is None:
            await say(event, "📭 No timer running for this chat.", name="setkill")
            return
        lines = [
            "⏱ <b>Timer Status</b>",
            f"<b>ID</b> · <code>{found['id']}</code>",
            f"<b>Interval</b> · <code>{found['interval']}s</code>",
            f"<b>Text</b> · {brand.esc(found.get('text') or 'random')}",
            f"<b>Reply to</b> · {brand.esc(found.get('reply_to') or 'No')}",
        ]
        await say(event, "\n".join(lines), name="setkill", parse_mode="html")