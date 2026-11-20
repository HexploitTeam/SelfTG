"""!reply: mirror the owner's messages as replies to one target message."""
import os
from telethon import events

from Com.core.storage import cached_json, save_json

__HELP__ = (
    "!reply on (reply to a message) → Mirror everything you say in this chat as a "
    "reply to that message, then delete the original.\n"
    "!reply off → Stop mirroring\n"
    "!reply status → Show current mirror target"
)
__CATEGORY__ = "Utilities"

FILE = "mode/reply.json"
# Cap for attachments copied by the mirror; the old code downloaded whole files
# into RAM with no limit, which is fatal in a small Replit container.
MAX_COPY_BYTES = 20 * 1024 * 1024
os.makedirs("mode", exist_ok=True)

def load_data():
    # This runs for every message the account sees (the mirror is a catch-all
    # handler), so it goes through the shared mtime-validated cache: one parse
    # after a write, none otherwise (Com/core/storage.py).
    return cached_json(FILE, {"enabled": False, "target_chat": None, "target_msg": None})

def save_data(data):
    save_json(FILE, data)

async def copy_message(client, event, target_chat, target_msg):
    msg = event.message
    text = msg.text or msg.raw_text or ""
    media = msg.media

    if media:
        size = getattr(getattr(msg, "file", None), "size", None)
        if size and size > MAX_COPY_BYTES:
            await client.send_message(
                target_chat,
                f"⚠️ Skipped a {size // (1024 * 1024)} MB attachment "
                f"(auto-copy limit is {MAX_COPY_BYTES // (1024 * 1024)} MB).",
                reply_to=target_msg,
            )
            return
        file_bytes = await msg.download_media(file=bytes)
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
        if event.raw_text and event.raw_text.startswith("!"):
            return

        data = load_data()
        if not data.get("enabled", False):
            return

        target_chat = data.get("target_chat")
        target_msg = data.get("target_msg")
        if not target_chat or not target_msg:
            return

        # Ignore copies that are already replies to the target; this is what stops a loop
        if event.message.reply_to_msg_id == target_msg:
            return

        try:
            await event.delete()
        except Exception:
            pass

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