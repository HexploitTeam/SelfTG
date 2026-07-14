# Com/reverseimg.py
from telethon import events
import aiohttp
import os

__HELP__ = "!reverseimg [google|yandex|tineye] (reply to image) → Reverse image search"
__CATEGORY__ = "Utilities"

TELEGRAPH_API = "https://telegra.ph/upload"


async def upload_to_telegraph(file_path):
    try:
        async with aiohttp.ClientSession() as session:
            with open(file_path, "rb") as f:
                form = aiohttp.FormData()
                form.add_field("file", f, filename=os.path.basename(file_path))
                async with session.post(TELEGRAPH_API, data=form) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    if isinstance(data, list) and "src" in data[0]:
                        return "https://telegra.ph" + data[0]["src"]
    except Exception:
        return None
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

            # Download file temporarily
            file_path = await client.download_media(reply_msg,
                                                    file="temp_reverseimg")
            if not file_path:
                await event.reply("❌ Failed to download media.")
                return

            # Upload to Telegraph
            url = await upload_to_telegraph(file_path)
            os.remove(file_path)

            if not url:
                await event.reply("❌ Failed to upload image to Telegraph.")
                return

            # Generate search link
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

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
