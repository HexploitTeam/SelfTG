# Com/fileinfo.py
from telethon import events
import hashlib
import os
import datetime

__HELP__ = "!fileinfo (reply) → Get detailed info about a replied file (size, type, hashes, etc.)"
__CATEGORY__ = "Utilities"


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!fileinfo$"))
    async def fileinfo(event):
        if not event.is_reply:
            await event.reply("❌ Reply to a file to get its info.")
            return

        reply_msg = await event.get_reply_message()
        if not reply_msg.media:
            await event.reply("❌ The replied message doesn’t contain a file.")
            return

        try:
            file = reply_msg.file
            if not file:
                await event.reply("❌ No file information found.")
                return

            # Download file temporarily to calculate hashes
            path = await reply_msg.download_media(file="./temp_fileinfo")
            md5_hash = sha1_hash = sha256_hash = "N/A"
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    data = f.read()
                    md5_hash = hashlib.md5(data).hexdigest()
                    sha1_hash = hashlib.sha1(data).hexdigest()
                    sha256_hash = hashlib.sha256(data).hexdigest()
                os.remove(path)

            # Human-readable size
            def human_size(size):
                if size is None:
                    return "Unknown"
                for unit in ["B", "KB", "MB", "GB", "TB"]:
                    if size < 1024:
                        return f"{size:.2f} {unit}"
                    size /= 1024
                return f"{size:.2f} PB"

            # Format message
            msg = "📂 **File Information**\n\n"
            if file.name:
                msg += f"**Name:** `{file.name}`\n"
            if file.size:
                msg += f"**Size:** {human_size(file.size)} ({file.size} bytes)\n"
            if file.mime_type:
                msg += f"**MIME Type:** `{file.mime_type}`\n"
            if file.id:
                msg += f"**File ID:** `{file.id}`\n"
            if reply_msg.date:
                msg += f"**Upload Date:** `{reply_msg.date.strftime('%Y-%m-%d %H:%M:%S')}`\n"

            # Try to extract document-specific fields
            if hasattr(reply_msg.media, "document"):
                doc = reply_msg.media.document
                if hasattr(doc, "dc_id"):
                    msg += f"**Data Center ID:** `{doc.dc_id}`\n"
                if hasattr(doc, "mime_type"):
                    msg += f"**MIME Type (Doc):** `{doc.mime_type}`\n"

            # Media specific info
            if file.width and file.height:
                msg += f"**Dimensions:** {file.width}×{file.height}\n"
            if file.duration:
                duration = str(datetime.timedelta(seconds=file.duration))
                msg += f"**Duration:** {duration}\n"

            # Hashes
            msg += "\n🔑 **Hashes:**\n"
            msg += f"MD5: `{md5_hash}`\n"
            msg += f"SHA1: `{sha1_hash}`\n"
            msg += f"SHA256: `{sha256_hash}`\n"

            await event.reply(msg)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
