"""!reverseimg: upload a replied image to catbox and link a reverse image search."""
from telethon import events
from Com.core import brand
from Com.core.reply import say
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
                await say(event,
                          "❌ Reply to an image or sticker to use reverse "
                          "search.",
                          name="reverseimg")
                return

            reply_msg = await event.get_reply_message()
            if not reply_msg.media:
                await say(event, "❌ That’s not an image or file.",
                          name="reverseimg")
                return

            file_path = await client.download_media(reply_msg,
                                                    file="temp_reverseimg")
            if not file_path:
                await say(event, "❌ Failed to download media.",
                          name="reverseimg")
                return

            url = await upload_to_catbox(file_path)
            os.remove(file_path)

            if not url:
                await say(event,
                          "❌ <b>Upload failed</b> · the hosting service "
                          "refused the image.\nTry a smaller image.",
                          name="reverseimg", parse_mode="html")
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
                await say(event,
                          "❌ Invalid service. Use <code>google</code> / "
                          "<code>yandex</code> / <code>tineye</code>.",
                          name="reverseimg", parse_mode="html")
                return

            await say(event,
                      f"🔍 <b>Reverse image search</b> · {brand.esc(service_name)}\n"
                      f"<code>{brand.esc(link)}</code>",
                      name="reverseimg", parse_mode="html")
            await event.delete()  # remove command message

        except Exception as e:
            await say(event, f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="reverseimg", parse_mode="html")