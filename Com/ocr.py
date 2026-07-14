# Com/ocr.py
from telethon import events
from PIL import Image
import pytesseract
from io import BytesIO

__HELP__ = "!ocr → Extract text from a replied image"


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!ocr$"))
    async def ocr_handler(event):
        try:
            if not event.is_reply:
                await event.reply("❌ Reply to an image to extract text.")
                return

            reply_msg = await event.get_reply_message()
            if not reply_msg.media:
                await event.reply("❌ The replied message has no media.")
                return

            bio = BytesIO()
            await reply_msg.download_media(file=bio)
            bio.seek(0)
            img = Image.open(bio)

            text = pytesseract.image_to_string(img)
            if not text.strip():
                await event.reply("❌ No text detected in the image.")
            else:
                await event.reply(f"📝 Extracted Text:\n{text}")

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
