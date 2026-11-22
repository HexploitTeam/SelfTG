"""!fileinfo: size, MIME type and hashes for a replied document."""
from telethon import events
from Com.core import brand
from Com.core.reply import say
import hashlib
import os
import datetime

__HELP__ = "!fileinfo (reply) → Get detailed info about a replied file (size, type, hashes, etc.)"
__CATEGORY__ = "Utilities"


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!fileinfo$"))
    async def fileinfo(event):
        if not event.is_reply:
            await say(event, "❌ Reply to a file to get its info.",
                      name="fileinfo")
            return

        reply_msg = await event.get_reply_message()
        if not reply_msg.media:
            await say(event, "❌ The replied message doesn’t contain a file.",
                      name="fileinfo")
            return

        try:
            file = reply_msg.file
            if not file:
                await say(event, "❌ No file information found.",
                          name="fileinfo")
                return

            path = await reply_msg.download_media(file="./temp_fileinfo")
            md5_hash = sha1_hash = sha256_hash = "N/A"
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    data = f.read()
                    md5_hash = hashlib.md5(data).hexdigest()
                    sha1_hash = hashlib.sha1(data).hexdigest()
                    sha256_hash = hashlib.sha256(data).hexdigest()
                os.remove(path)

            def human_size(size):
                if size is None:
                    return "Unknown"
                for unit in ["B", "KB", "MB", "GB", "TB"]:
                    if size < 1024:
                        return f"{size:.2f} {unit}"
                    size /= 1024
                return f"{size:.2f} PB"

            msg = "📂 <b>File Information</b>"
            if file.name:
                msg += f"\nName · <code>{brand.esc(file.name)}</code>"
            if file.size:
                msg += (f"\nSize · <b>{human_size(file.size)}</b> · "
                        f"<code>{file.size} bytes</code>")
            if file.mime_type:
                msg += f"\nMIME type · <code>{brand.esc(file.mime_type)}</code>"
            if file.id:
                msg += f"\nFile ID · <code>{brand.esc(file.id)}</code>"
            if reply_msg.date:
                stamp = reply_msg.date.strftime('%Y-%m-%d %H:%M:%S')
                msg += f"\nUploaded · <code>{stamp}</code>"

            # Try to extract document-specific fields
            if hasattr(reply_msg.media, "document"):
                doc = reply_msg.media.document
                if hasattr(doc, "dc_id"):
                    msg += f"\nData center · <code>{doc.dc_id}</code>"
                if hasattr(doc, "mime_type"):
                    msg += (f"\nDocument MIME · "
                            f"<code>{brand.esc(doc.mime_type)}</code>")

            # Media specific info
            if file.width and file.height:
                msg += (f"\nDimensions · <b>{file.width}×{file.height}</b>")
            if file.duration:
                duration = str(datetime.timedelta(seconds=file.duration))
                msg += f"\nDuration · <code>{duration}</code>"

            # Hashes
            msg += (f"\n\n🔑 <b>Hashes</b>\n"
                    f"MD5 · <code>{md5_hash}</code>\n"
                    f"SHA1 · <code>{sha1_hash}</code>\n"
                    f"SHA256 · <code>{sha256_hash}</code>")

            await say(event, msg, name="fileinfo", parse_mode="html")

        except Exception as e:
            await say(event,
                      f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="fileinfo", parse_mode="html")
