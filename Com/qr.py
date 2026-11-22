"""!qr: generate a QR code image from text."""
from telethon import events
import qrcode
from io import BytesIO

from Com.core import brand
from Com.core.reply import say

__HELP__ = "!qr <text> → Generate a QR code from the given text"
__CATEGORY__ = "Utilities"

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

            await event.reply(
                file=bio,
                caption=brand.sign("🔳 <b>QR code</b>", "qr"),
                parse_mode="html",
            )
        except Exception as e:
            await say(
                event,
                f"❌ <b>QR failed.</b> {brand.esc(e)}",
                name="qr",
                parse_mode="html",
            )
