"""Media metadata commands and the image/PDF manipulation commands."""
from telethon import events
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto
import Com.core.tgsend as tgsend
from io import BytesIO
from PIL import Image
import asyncio
import os
import tempfile
import PyPDF2
import mutagen

__HELP__ = (
    "!audiometa → Extract metadata from a replied audio file.\n"
    "!videometa → Extract metadata from a replied video.\n"
    "!convertpdf → Convert a replied document to PDF.\n"
    "!pdfinfo → Show PDF file info (pages, author, size).\n"
    "!imgresize <width>x<height> → Resize replied image.\n"
    "!imgrotate <deg> → Rotate replied image.\n"
    "!imgcompress → Compress replied image to smaller size.\n"
    "!imgformat <format> → Convert replied image to another format (PNG/JPG).")


# Telegram rejects a text message over 4096 characters, and ID3/APE tags can
# carry far more than that: embedded lyrics (USLT), long comments, and tags whose
# value is the raw cover image. `!audiometa` used to join every value into one
# string, so a normally-tagged file failed with "Message was too long".
MAX_FIELD_CHARS = 200     # one tag value, so a single field cannot eat the budget
MAX_BODY_CHARS = 3500     # whole listing; leaves room for the header and footer


def short_tag_value(value):
    """Render one mutagen tag value as a short single-line string.

    Tags are not always strings: multi-value frames arrive as lists, and picture
    frames (APIC) are raw bytes that would blow up both the message and the log.
    """
    if isinstance(value, (list, tuple)):
        parts = [short_tag_value(item) for item in value]
        text = ", ".join(part for part in parts if part)
    elif isinstance(value, (bytes, bytearray)):
        text = f"<{len(value)} bytes>"
    else:
        text = str(value)
    # NULs and newlines come from malformed frames; one tag must stay one line.
    text = text.replace("\x00", " ").replace("\r", " ").replace("\n", " ").strip()
    if len(text) > MAX_FIELD_CHARS:
        text = text[:MAX_FIELD_CHARS] + "…"
    return text


def format_audio_tags(tags):
    """Body of the !audiometa reply, bounded to what Telegram will accept."""
    if not tags:
        return "No tags found"
    lines = []
    used = 0
    omitted = 0
    for key, value in tags.items():
        line = f"{key}: {short_tag_value(value)}"
        if used + len(line) + 1 > MAX_BODY_CHARS:
            omitted += 1
            continue
        lines.append(line)
        used += len(line) + 1
    if omitted:
        lines.append(f"… {omitted} more tag(s) omitted, message too long")
    return "\n".join(lines) or "No tags found"


def probe_video(path):
    """Return (duration, width, height, fps) for a local video file.

    moviepy is imported here rather than at module load: it drags in numpy and
    ffmpeg bindings (~40 MB RSS) that only !videometa ever needs. 2.x dropped
    the `moviepy.editor` module, so import the top-level name first.
    """
    try:
        from moviepy import VideoFileClip
    except ImportError:
        from moviepy.editor import VideoFileClip
    clip = VideoFileClip(path)
    try:
        return clip.duration, clip.w, clip.h, clip.fps
    finally:
        clip.close()


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):

    async def download_reply(event):
        if not event.is_reply:
            await event.reply("❌ Please reply to a file or image.")
            return None
        reply = await event.get_reply_message()
        if not reply.media:
            await event.reply("❌ Replied message has no media.")
            return None
        bio = BytesIO()
        await reply.download_media(file=bio)
        bio.seek(0)
        return bio, reply

    # Audio metadata
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!audiometa$"))
    async def audiometa(event):
        try:
            result = await download_reply(event)
            if not result:
                return
            bio, reply = result

            audio = mutagen.File(bio)
            if not audio:
                await event.reply("❌ Could not read audio metadata.")
                return

            await event.reply(f"🎵 Audio Metadata:\n{format_audio_tags(audio.tags)}")

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # Video metadata
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!videometa$"))
    async def videometa(event):
        try:
            result = await download_reply(event)
            if not result:
                return
            bio, reply = result

            temp_file = tempfile.NamedTemporaryFile(delete=False)
            temp_file.write(bio.read())
            temp_file.close()

            # Decoding runs off the event loop; on 0.5 vCPU it is slow enough
            # to look like the bot died.
            duration, width, height, fps = await asyncio.to_thread(
                probe_video, temp_file.name
            )
            info = (f"Duration: {duration:.2f} sec\n"
                    f"Resolution: {width}x{height}\n"
                    f"FPS: {fps}")
            await event.reply(f"🎬 Video Metadata:\n{info}")
            os.remove(temp_file.name)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # PDF conversion (dummy, just re-save)
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!convertpdf$"))
    async def convertpdf(event):
        try:
            result = await download_reply(event)
            if not result:
                return
            bio, reply = result

            temp_in = tempfile.NamedTemporaryFile(delete=False)
            temp_in.write(bio.read())
            temp_in.close()

            temp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_out.close()

            # Rebuild page by page; anything PyPDF2 cannot read falls to the blank-page path
            try:
                reader = PyPDF2.PdfReader(temp_in.name)
                writer = PyPDF2.PdfWriter()
                for page in reader.pages:
                    writer.add_page(page)
                with open(temp_out.name, "wb") as f:
                    writer.write(f)
            except:
                writer = PyPDF2.PdfWriter()
                writer.add_blank_page(width=595, height=842)
                with open(temp_out.name, "wb") as f:
                    writer.write(f)

            await client.send_file(await tgsend.peer(event),
                                   temp_out.name,
                                   caption="📄 Converted to PDF",
                                   reply_to=reply.id)
            os.remove(temp_in.name)
            os.remove(temp_out.name)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # PDF info
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!pdfinfo$"))
    async def pdfinfo(event):
        try:
            result = await download_reply(event)
            if not result:
                return
            bio, reply = result

            temp_file = tempfile.NamedTemporaryFile(delete=False)
            temp_file.write(bio.read())
            temp_file.close()

            reader = PyPDF2.PdfReader(temp_file.name)
            pages = len(reader.pages)
            metadata = reader.metadata
            info = f"Pages: {pages}\n"
            for k, v in metadata.items():
                info += f"{k[1:]}: {v}\n"  # remove leading /

            await event.reply(f"📄 PDF Info:\n{info}")
            os.remove(temp_file.name)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # Image resize
    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!imgresize\s+(\d+)x(\d+)$"))
    async def imgresize(event):
        try:
            w, h = int(event.pattern_match.group(1)), int(
                event.pattern_match.group(2))
            result = await download_reply(event)
            if not result:
                return
            bio, reply = result

            img = Image.open(bio)
            img = img.resize((w, h))
            out = BytesIO()
            img.save(out, format=img.format)
            out.seek(0)
            await client.send_file(await tgsend.peer(event),
                                   out,
                                   caption=f"🖼 Image resized to {w}x{h}",
                                   reply_to=reply.id)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # Image rotate
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!imgrotate\s+(\d+)$"))
    async def imgrotate(event):
        try:
            deg = int(event.pattern_match.group(1))
            result = await download_reply(event)
            if not result:
                return
            bio, reply = result

            img = Image.open(bio)
            img = img.rotate(deg, expand=True)
            out = BytesIO()
            img.save(out, format=img.format)
            out.seek(0)
            await client.send_file(await tgsend.peer(event),
                                   out,
                                   caption=f"🖼 Image rotated {deg}°",
                                   reply_to=reply.id)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # Image compress
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!imgcompress$"))
    async def imgcompress(event):
        try:
            result = await download_reply(event)
            if not result:
                return
            bio, reply = result

            img = Image.open(bio)
            out = BytesIO()
            img.save(out, format=img.format, optimize=True, quality=70)
            out.seek(0)
            await client.send_file(await tgsend.peer(event),
                                   out,
                                   caption="🖼 Image compressed",
                                   reply_to=reply.id)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # Image format conversion
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!imgformat\s+(\w+)$"))
    async def imgformat(event):
        try:
            fmt = event.pattern_match.group(1).upper()
            result = await download_reply(event)
            if not result:
                return
            bio, reply = result

            img = Image.open(bio)
            out = BytesIO()
            img.save(out, format=fmt)
            out.seek(0)
            await client.send_file(await tgsend.peer(event),
                                   out,
                                   caption=f"🖼 Image converted to {fmt}",
                                   reply_to=reply.id)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
