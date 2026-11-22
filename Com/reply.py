"""!reply: mirror the owner's messages as replies to one target message."""
import os
from telethon import events

from Com.core import brand
from Com.core.reply import say
from Com.core.storage import cached_json, save_json

__HELP__ = (
    "!reply on (reply to a message) → Mirror everything you say in this chat as a "
    "reply to that message, then delete the original.\n"
    "!reply off → Stop mirroring\n"
    "!reply status → Show current mirror target"
)
__CATEGORY__ = "Utilities"

FILE = "mode/reply.json"
# Cap for copied attachments
MAX_COPY_BYTES = 20 * 1024 * 1024
os.makedirs("mode", exist_ok=True)

def load_data():
    # Per-message path: cached (Com/core/storage.py)
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
                brand.sign(
                    f"⚠️ <b>Skipped a {size // (1024 * 1024)} MB attachment</b>\n"
                    f"<i>auto-copy limit is "
                    f"{MAX_COPY_BYTES // (1024 * 1024)} MB</i>",
                    "reply",
                ),
                parse_mode="html",
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

        # Stops the loop
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
            await say(
                event,
                "❌ <b>You must reply to a message</b> to set it as target.",
                name="reply", parse_mode="html",
            )
            return

        reply = await event.get_reply_message()
        data = load_data()
        data["enabled"] = True
        data["target_chat"] = event.chat_id
        data["target_msg"] = reply.id
        save_data(data)
        await say(
            event,
            "✅ <b>Auto-reply enabled</b> · target "
            f"<code>{reply.id}</code>",
            name="reply", parse_mode="html",
        )
        try:
            await event.delete()
        except Exception:
            pass

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!reply off$"))
    async def reply_off(event):
        data = load_data()
        data["enabled"] = False
        save_data(data)
        await say(event, "❌ <b>Auto-reply disabled.</b>", name="reply",
                  parse_mode="html")
        try:
            await event.delete()
        except Exception:
            pass

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!reply status$"))
    async def reply_status(event):
        data = load_data()
        status = "ON" if data["enabled"] else "OFF"
        target = (
            f"<code>{data['target_msg']}</code>"
            if data["target_msg"] else "none"
        )
        await say(
            event,
            f"🔁 <b>Auto-reply</b> · <code>{status}</code>\n"
            f"Target · {target}",
            name="reply", parse_mode="html",
        )