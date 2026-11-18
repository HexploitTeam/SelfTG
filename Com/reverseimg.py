"""!reverseimg: upload a replied image to catbox and link a reverse image search."""
from telethon import events
import aiohttp
import os

__HELP__ = "!reverseimg [google|yandex|tineye] (reply to image) → Reverse image search"
__CATEGORY__ = "Utilities"


async def upload_to_catbox(file_path):
    """Upload a file to catbox.moe and return the public URL."""
    try:
        async with aiohttp.ClientSession() as session:
            with open(file_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("reqtype", "fileupload")
                data.add_field("fileToUpload", f, filename=os.path.basename(file_path))
                async with session.post("https://catbox.moe/user/api.php", data=data) as resp:
                    if resp.status == 200:
                        url = await resp.text()
                        return url.strip()
                    return None
    except Exception:
        return None


def setup(client, my_id):
    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!reverseimg(?:\s+(\w+))?$"))
    async def reverseimg(event):
        try:
            service = (event.pattern_match.group(1) or "google").lower()

            if not event.is_reply:
                await event.reply(
                    "❌ Reply to an image or sticker to use reverse search.")
                return

            reply_msg = await event.get_reply_message()
            if not reply_msg.media:
                await event.reply("❌ That’s not an image or file.")
                return

            file_path = await client.download_media(reply_msg,
                                                    file="temp_reverseimg")
            if not file_path:
                await event.reply("❌ Failed to download media.")
                return

            url = await upload_to_catbox(file_path)
            os.remove(file_path)

            if not url:
                await event.reply(
                    "❌ Failed to upload image to hosting service.\n"
                    "Try a smaller image or use a different service.")
                return

            if service == "google":
                link = f"https://lens.google.com/uploadbyurl?url={url}"
                service_name = "Google Lens"
            elif service == "yandex":
                link = f"https://yandex.com/images/search?rpt=imageview&url={url}"
                service_name = "Yandex Images"
            elif service == "tineye":
                link = f"https://tineye.com/search?url={url}"
                service_name = "TinEye"
            else:
                await event.reply(
                    "❌ Invalid service. Use google / yandex / tineye.")
                return

            await event.reply(
                f"🔍 Reverse Image Search ({service_name}):\n{link}")
            await event.delete()  # remove command message

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")