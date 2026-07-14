# Com/decodeqr.py
import aiohttp
from telethon import events
from io import BytesIO

__HELP__ = "!decodeqr → Decode a QR code from a replied image using a free API"
__CATEGORY__ = "Utilities"

def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!decodeqr"))
    async def decode_qr(event):
        try:
            if not event.is_reply:
                await event.reply("❌ Reply to an image containing a QR code.")
                return

            reply_msg = await event.get_reply_message()
            if not reply_msg.media:
                await event.reply("❌ The replied message has no media.")
                return

            bio = BytesIO()
            await reply_msg.download_media(file=bio)
            bio.seek(0)

            async with aiohttp.ClientSession() as session:
                data = aiohttp.FormData()
                data.add_field("file",
                               bio,
                               filename="qr.png",
                               content_type="image/png")

                async with session.post(
                        "https://api.qrserver.com/v1/read-qr-code/",
                        data=data) as resp:
                    if resp.status != 200:
                        await event.reply(
                            f"❌ API request failed with status {resp.status}")
                        return
                    result = await resp.json()

            # Parse the response
            decoded_texts = []
            for item in result:
                for symbol in item.get("symbol", []):
                    text = symbol.get("data")
                    if text:
                        decoded_texts.append(text)

            if not decoded_texts:
                await event.reply("❌ No QR code found in the image.")
                return

            await event.reply("🔓 Decoded QR Code:\n" +
                              "\n".join(decoded_texts))

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
