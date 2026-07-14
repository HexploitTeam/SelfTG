# Com/imgwatermark.py
from telethon import events
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
            # Get watermark text
            text = event.pattern_match.group(1)
            if not text and event.is_reply:
                reply_msg = await event.get_reply_message()
                text = reply_msg.text or reply_msg.message
            if not text:
                await event.reply(
                    "❌ Provide watermark text or reply to a message with text."
                )
                return

            # Check if the command is a reply to an image
            if not event.is_reply:
                await event.reply("❌ Reply to an image to add a watermark.")
                return

            reply_msg = await event.get_reply_message()
            if not reply_msg.media:
                await event.reply("❌ Replied message has no media.")
                return

            # Download image to memory
            bio = BytesIO()
            await reply_msg.download_media(file=bio)
            bio.seek(0)

            # Open image
            img = Image.open(bio).convert("RGBA")

            # Create watermark layer
            txt_layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(txt_layer)
            font_size = max(20, img.width // 15)
            font = ImageFont.truetype(
                "arial.ttf", font_size) if os.path.exists(
                    "arial.ttf") else ImageFont.load_default()

            # Calculate text size using textbbox()
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            # Position: bottom-right corner
            x = img.width - text_width - 10
            y = img.height - text_height - 10

            # Draw text
            draw.text((x, y), text, font=font,
                      fill=(255, 255, 255, 128))  # semi-transparent white

            # Combine original image with watermark
            watermarked = Image.alpha_composite(img, txt_layer)

            # Save to BytesIO
            out_bio = BytesIO()
            watermarked.convert("RGB").save(out_bio, "JPEG")
            out_bio.seek(0)

            # Send watermarked image
            await client.send_file(
                event.chat_id,
                out_bio,
                caption=f"💧 Watermarked Image with text: {text}",
                reply_to=event.id)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
