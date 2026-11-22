"""!imgwatermark: stamp text onto a replied image with Pillow."""
from telethon import events
import Com.core.tgsend as tgsend
from Com.core import brand
from Com.core.reply import say
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import os

__HELP__ = "!imgwatermark <text> or reply → Add watermark text to an image"

os.makedirs("temp", exist_ok=True)


def setup(client, my_id):

    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!imgwatermark(?:\s+(.+))?"))
    async def imgwatermark(event):
        try:
            text = event.pattern_match.group(1)
            if not text and event.is_reply:
                reply_msg = await event.get_reply_message()
                text = reply_msg.text or reply_msg.message
            if not text:
                await say(event,
                          "❌ Provide watermark text or reply to a message "
                          "with text.",
                          name="imgwatermark")
                return

            if not event.is_reply:
                await say(event, "❌ Reply to an image to add a watermark.",
                          name="imgwatermark")
                return

            reply_msg = await event.get_reply_message()
            if not reply_msg.media:
                await say(event, "❌ Replied message has no media.",
                          name="imgwatermark")
                return

            bio = BytesIO()
            await reply_msg.download_media(file=bio)
            bio.seek(0)

            img = Image.open(bio).convert("RGBA")

            txt_layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(txt_layer)
            font_size = max(20, img.width // 15)
            font = ImageFont.truetype(
                "arial.ttf", font_size) if os.path.exists(
                    "arial.ttf") else ImageFont.load_default()

            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            x = img.width - text_width - 10
            y = img.height - text_height - 10

            draw.text((x, y), text, font=font,
                      fill=(255, 255, 255, 128))  # semi-transparent white

            watermarked = Image.alpha_composite(img, txt_layer)

            out_bio = BytesIO()
            watermarked.convert("RGB").save(out_bio, "JPEG")
            out_bio.seek(0)

            await client.send_file(await tgsend.peer(event),
                out_bio,
                caption=brand.sign(
                    f"💧 <b>Watermarked</b> · {brand.esc(text)}",
                    "imgwatermark"),
                reply_to=event.id, parse_mode="html")

        except Exception as e:
            await say(event,
                      f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="imgwatermark", parse_mode="html")
