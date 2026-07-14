# Com/f.py
from telethon import events
import os
import json
import asyncio
import random

__HELP__ = "!f → Manage and send random replies with IDs"
__CATEGORY__ = "Utilities"

F_FILE = "mode/f.json"
ID_FILE = "mode/f_id.txt"
os.makedirs("mode", exist_ok=True)

# Initialize JSON and ID file
if not os.path.exists(F_FILE):
    with open(F_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

if not os.path.exists(ID_FILE):
    with open(ID_FILE, "w", encoding="utf-8") as f:
        f.write("0")  # last ID

active_f_tasks = {}  # code_id: task


def setup(client, my_id):

    def load_items():
        with open(F_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_items(items):
        with open(F_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)

    def get_next_id():
        with open(ID_FILE, "r", encoding="utf-8") as f:
            last_id = int(f.read().strip())
        next_id = last_id + 1
        with open(ID_FILE, "w", encoding="utf-8") as f:
            f.write(str(next_id))
        return next_id

    # ------------------------
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

    # ------------------------
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

    # ------------------------
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
                    item = random.choice(items)
                    await reply_msg.reply(item["text"])
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    break

        t = asyncio.create_task(task())
        active_f_tasks[code_id] = t

    # ------------------------
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

    # ------------------------
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
