"""!f: random-reply lists and the interval task that sends them."""
from telethon import errors, events
import os
import asyncio
import logging
import random

from Com.core import flood
from Com.core.storage import cached_json, ensure_json_file, save_json

log = logging.getLogger("selftg.f")

__HELP__ = "!f → Manage and send random replies with IDs"
__CATEGORY__ = "Utilities"

F_FILE = "mode/f.json"
ID_FILE = "mode/f_id.txt"
os.makedirs("mode", exist_ok=True)

# Atomic first run
ensure_json_file(F_FILE, [])

if not os.path.exists(ID_FILE):
    with open(ID_FILE, "w", encoding="utf-8") as f:
        f.write("0")  # last ID

active_f_tasks = {}  # code_id: task


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):

    def load_items():
        # Re-read per message; cached (Com/core/storage.py)
        return cached_json(F_FILE, [])

    def save_items(items):
        save_json(F_FILE, items)

    def get_next_id():
        with open(ID_FILE, "r", encoding="utf-8") as f:
            last_id = int(f.read().strip())
        next_id = last_id + 1
        with open(ID_FILE, "w", encoding="utf-8") as f:
            f.write(str(next_id))
        return next_id

    # Add text
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!f\s+add$"))
    async def f_add(event):
        if not event.is_reply:
            await event.edit("❌ WRONG usage!\n!f add (reply to message)")
            return

        reply_msg = await event.get_reply_message()
        text = reply_msg.text
        if not text:
            await event.edit("❌ Replied message has no text!")
            return

        items = load_items()
        code_id = get_next_id()
        items.append({"id": code_id, "text": text})
        save_items(items)
        await event.edit(f"✅ Text saved. Code: {code_id}")

    # Delete text
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!f\s+del\s+(\d+)$"))
    async def f_del(event):
        del_id = int(event.pattern_match.group(1))
        items = load_items()
        found = False
        for i, item in enumerate(items):
            if item["id"] == del_id:
                items.pop(i)
                found = True
                break
        if found:
            save_items(items)
            await event.edit(f"✅ Deleted Code: {del_id}")
        else:
            await event.edit(f"❌ Code {del_id} not found!")

    # Start sending randomly
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!f\s+start$"))
    async def f_start(event):
        if not event.is_reply:
            await event.edit("❌ WRONG usage!\n!f start (reply to message)")
            return

        reply_msg = await event.get_reply_message()
        items = load_items()
        if not items:
            await event.edit("❌ f.json is empty!")
            return

        code_id = get_next_id()
        chat_id = event.chat_id
        await event.edit(f"✅ Started! Code: {code_id}")

        async def task():
            while True:
                try:
                    # This loop is a series that runs until stopped, so it obeys
                    # the shared gate and the breaker (Com/core/flood.py):
                    # jittered 5 s gaps instead of an exact clock, and a pause
                    # when the account is already being rate limited.
                    left = flood.cooldown_left()
                    if left:
                        await asyncio.sleep(min(left, 60))
                        continue
                    item = random.choice(items)
                    await reply_msg.reply(item["text"])
                    await flood.pace(chat_id, gap=5.0)
                except asyncio.CancelledError:
                    break
                except errors.FloodWaitError as exc:
                    left = flood.note_flood(exc.seconds)
                    log.warning("[f] code %s hit FLOOD_WAIT %ss", code_id, exc.seconds)
                    if left:
                        try:
                            await client.send_message(chat_id, flood.describe(left))
                        except Exception:  # noqa: BLE001 - already stopping
                            pass
                        break
                    await asyncio.sleep(min(exc.seconds, 300))
                except Exception as exc:  # noqa: BLE001 - never die silently
                    log.info("[f] code %s stopped: %s", code_id, exc)
                    break

        t = asyncio.create_task(task())
        active_f_tasks[code_id] = t

    # Stop sending
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!f\s+stop\s+(\d+)$"))
    async def f_stop(event):
        stop_id = int(event.pattern_match.group(1))
        task = active_f_tasks.get(stop_id)
        if task:
            task.cancel()
            del active_f_tasks[stop_id]
            await event.edit(
                f"✅ Stopped sending random replies for Code: {stop_id}")
        else:
            await event.edit(f"❌ No active task with Code: {stop_id}")

    # Fallback for wrong usage
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!f\b"))
    async def f_fallback(event):
        text = event.text.strip().lower()
        if not any(
                text.startswith(cmd)
                for cmd in ["!f add", "!f del", "!f start", "!f stop"]):
            await event.edit("❌ WRONG usage!\n"
                             "!f add (reply to message)\n"
                             "!f del <Code>\n"
                             "!f start (reply to message)\n"
                             "!f stop <Code>")
