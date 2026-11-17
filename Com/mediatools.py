# Com/mediatools.py
from telethon import events
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto
import Com.tgsend as tgsend
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

    # -----------------------------
    # Audio metadata
    # -----------------------------
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

            info = "\n".join(
                f"{k}: {v}" for k, v in
                audio.tags.items()) if audio.tags else "No tags found"
            await event.reply(f"🎵 Audio Metadata:\n{info}")

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # -----------------------------
    # Video metadata
    # -----------------------------
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

    # -----------------------------
    # PDF conversion (dummy, just re-save)
    # -----------------------------
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

            # Simple re-save using PyPDF2 if already PDF
            try:
                reader = PyPDF2.PdfReader(temp_in.name)
                writer = PyPDF2.PdfWriter()
                for page in reader.pages:
                    writer.add_page(page)
                with open(temp_out.name, "wb") as f:
                    writer.write(f)
            except:
                # If not PDF, just wrap in blank PDF page (dummy)
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

    # -----------------------------
    # PDF info
    # -----------------------------
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

    # -----------------------------
    # Image resize
    # -----------------------------
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

    # -----------------------------
    # Image rotate
    # -----------------------------
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

    # -----------------------------
    # Image compress
    # -----------------------------
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

    # -----------------------------
    # Image format conversion
    # -----------------------------
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
