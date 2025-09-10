# Com/qr.py
from telethon import events
import qrcode
from io import BytesIO

__HELP__ = "!qr <text> → Generate a QR code from the given text"


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!qr\s+(.+)"))
    async def qr(event):
        try:
            text = event.pattern_match.group(1)
            qr_img = qrcode.make(text)

            bio = BytesIO()
            bio.name = "qr.png"
            qr_img.save(bio, "PNG")
            bio.seek(0)

            await event.reply(file=bio)
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
