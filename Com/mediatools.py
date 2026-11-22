"""Media metadata commands and the image/PDF manipulation commands."""
from telethon import events
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto
import Com.core.tgsend as tgsend
from Com.core import brand
from Com.core.reply import say
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


# 4096 is Telegram's limit; tags can carry megabytes
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
    # NULs and newlines come from malformed frames
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
        line = (f"<b>{brand.esc(key)}</b> · "
                f"{brand.esc(short_tag_value(value))}")
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

    async def download_reply(event, command):
        if not event.is_reply:
            await say(event, "❌ Please reply to a file or image.",
                      name=command)
            return None
        reply = await event.get_reply_message()
        if not reply.media:
            await say(event, "❌ Replied message has no media.", name=command)
            return None
        bio = BytesIO()
        await reply.download_media(file=bio)
        bio.seek(0)
        return bio, reply

    # Audio metadata
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!audiometa$"))
    async def audiometa(event):
        try:
            result = await download_reply(event, "audiometa")
            if not result:
                return
            bio, reply = result

            audio = mutagen.File(bio)
            if not audio:
                await say(event, "❌ Could not read audio metadata.",
                          name="audiometa")
                return

            await say(event,
                      f"🎵 <b>Audio Metadata</b>\n{format_audio_tags(audio.tags)}",
                      name="audiometa", parse_mode="html")

        except Exception as e:
            await say(event, f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="audiometa", parse_mode="html")

    # Video metadata
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!videometa$"))
    async def videometa(event):
        try:
            result = await download_reply(event, "videometa")
            if not result:
                return
            bio, reply = result

            temp_file = tempfile.NamedTemporaryFile(delete=False)
            temp_file.write(bio.read())
            temp_file.close()

            # Off the loop: decoding is slow
            duration, width, height, fps = await asyncio.to_thread(
                probe_video, temp_file.name
            )
            info = (f"Duration · <code>{duration:.2f} sec</code>\n"
                    f"Resolution · <code>{width}x{height}</code>\n"
                    f"FPS · <code>{fps}</code>")
            await say(event, f"🎬 <b>Video Metadata</b>\n{info}",
                      name="videometa", parse_mode="html")
            os.remove(temp_file.name)

        except Exception as e:
            await say(event, f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="videometa", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!convertpdf$"))
    async def convertpdf(event):
        try:
            result = await download_reply(event, "convertpdf")
            if not result:
                return
            bio, reply = result

            temp_in = tempfile.NamedTemporaryFile(delete=False)
            temp_in.write(bio.read())
            temp_in.close()

            temp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_out.close()

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

            await client.send_file(
                await tgsend.peer(event),
                temp_out.name,
                caption=brand.sign("📄 <b>Converted to PDF</b>", "convertpdf"),
                reply_to=reply.id, parse_mode="html")
            os.remove(temp_in.name)
            os.remove(temp_out.name)

        except Exception as e:
            await say(event, f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="convertpdf", parse_mode="html")

    # PDF info
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!pdfinfo$"))
    async def pdfinfo(event):
        try:
            result = await download_reply(event, "pdfinfo")
            if not result:
                return
            bio, reply = result

            temp_file = tempfile.NamedTemporaryFile(delete=False)
            temp_file.write(bio.read())
            temp_file.close()

            reader = PyPDF2.PdfReader(temp_file.name)
            pages = len(reader.pages)
            metadata = reader.metadata
            info = f"Pages · <b>{pages}</b>"
            for k, v in metadata.items():
                # k[1:] drops the leading /
                info += f"\n{brand.esc(k[1:])} · <code>{brand.esc(v)}</code>"

            await say(event, f"📄 <b>PDF Info</b>\n{info}",
                      name="pdfinfo", parse_mode="html")
            os.remove(temp_file.name)

        except Exception as e:
            await say(event, f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="pdfinfo", parse_mode="html")

    # Image resize
    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!imgresize\s+(\d+)x(\d+)$"))
    async def imgresize(event):
        try:
            w, h = int(event.pattern_match.group(1)), int(
                event.pattern_match.group(2))
            result = await download_reply(event, "imgresize")
            if not result:
                return
            bio, reply = result

            img = Image.open(bio)
            img = img.resize((w, h))
            out = BytesIO()
            img.save(out, format=img.format)
            out.seek(0)
            await client.send_file(
                await tgsend.peer(event),
                out,
                caption=brand.sign(
                    f"🖼 <b>Image resized</b> · <code>{w}x{h}</code>",
                    "imgresize"),
                reply_to=reply.id, parse_mode="html")

        except Exception as e:
            await say(event, f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="imgresize", parse_mode="html")

    # Image rotate
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!imgrotate\s+(\d+)$"))
    async def imgrotate(event):
        try:
            deg = int(event.pattern_match.group(1))
            result = await download_reply(event, "imgrotate")
            if not result:
                return
            bio, reply = result

            img = Image.open(bio)
            img = img.rotate(deg, expand=True)
            out = BytesIO()
            img.save(out, format=img.format)
            out.seek(0)
            await client.send_file(
                await tgsend.peer(event),
                out,
                caption=brand.sign(
                    f"🖼 <b>Image rotated</b> · <code>{deg}°</code>",
                    "imgrotate"),
                reply_to=reply.id, parse_mode="html")

        except Exception as e:
            await say(event, f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="imgrotate", parse_mode="html")

    # Image compress
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!imgcompress$"))
    async def imgcompress(event):
        try:
            result = await download_reply(event, "imgcompress")
            if not result:
                return
            bio, reply = result

            img = Image.open(bio)
            out = BytesIO()
            img.save(out, format=img.format, optimize=True, quality=70)
            out.seek(0)
            await client.send_file(
                await tgsend.peer(event),
                out,
                caption=brand.sign("🖼 <b>Image compressed</b>", "imgcompress"),
                reply_to=reply.id, parse_mode="html")

        except Exception as e:
            await say(event, f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="imgcompress", parse_mode="html")

    # Image format conversion
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!imgformat\s+(\w+)$"))
    async def imgformat(event):
        try:
            fmt = event.pattern_match.group(1).upper()
            result = await download_reply(event, "imgformat")
            if not result:
                return
            bio, reply = result

            img = Image.open(bio)
            out = BytesIO()
            img.save(out, format=fmt)
            out.seek(0)
            await client.send_file(
                await tgsend.peer(event),
                out,
                caption=brand.sign(
                    f"🖼 <b>Image converted</b> · <code>{fmt}</code>",
                    "imgformat"),
                reply_to=reply.id, parse_mode="html")

        except Exception as e:
            await say(event, f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="imgformat", parse_mode="html")
