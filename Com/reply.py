# Com/reply.py
import os
import json
from telethon import events

FILE = "mode/reply.json"
os.makedirs("mode", exist_ok=True)

def load_data():
    if not os.path.exists(FILE):
        return {"enabled": False, "target_chat": None, "target_msg": None}
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"enabled": False, "target_chat": None, "target_msg": None}

def save_data(data):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

async def copy_message(client, event, target_chat, target_msg):
    msg = event.message
    text = msg.text or msg.raw_text or ""
    media = msg.media

    if media:
        file_bytes = await client.download_media(media, bytes)
        if file_bytes:
            await client.send_message(
                target_chat,
                text,
                file=file_bytes,
                reply_to=target_msg
            )
        else:
            await client.send_message(
                target_chat,
                text or "(media could not be copied)",
                reply_to=target_msg
            )
    else:
        await client.send_message(
            target_chat,
            text,
            reply_to=target_msg
        )

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id))
    async def auto_reply(event):
        # Ignore commands
        if event.raw_text and event.raw_text.startswith("!"):
            return

        data = load_data()
        if not data.get("enabled", False):
            return

        target_chat = data.get("target_chat")
        target_msg = data.get("target_msg")
        if not target_chat or not target_msg:
            return

        # IGNORE messages that are already replies to the target (prevents loop)
        if event.message.reply_to_msg_id == target_msg:
            return

        # Delete the original message
        try:
            await event.delete()
        except Exception:
            pass

        # Send a copy as a reply to the target
        try:
            await copy_message(client, event, target_chat, target_msg)
        except Exception:
            pass

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!reply on$"))
    async def reply_on(event):
        if not event.is_reply:
            await event.edit("❌ You must reply to a message to set it as target.")
            return

        reply = await event.get_reply_message()
        data = load_data()
        data["enabled"] = True
        data["target_chat"] = event.chat_id
        data["target_msg"] = reply.id
        save_data(data)
        await event.edit(f"✅ Auto‑reply enabled. Target message: {reply.id}")
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!reply off$"))
    async def reply_off(event):
        data = load_data()
        data["enabled"] = False
        save_data(data)
        await event.edit("❌ Auto‑reply disabled.")
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!reply status$"))
    async def reply_status(event):
        data = load_data()
        status = "ON" if data["enabled"] else "OFF"
        target = f"Message {data['target_msg']}" if data["target_msg"] else "None"
        await event.edit(
            f"**Status:** {status}\n"
            f"**Target:** {target}"
        )