"""!ocr: image text extraction, local Tesseract first and the OCR.space API second."""
import asyncio
import base64
import logging
import os
import shutil
from io import BytesIO
from telethon import events
import Com.core.tgsend as tgsend

import Com.core.api as api

log = logging.getLogger("selftg.ocr")

__HELP__ = "!ocr (reply to image) → Extract text from an image using local Tesseract (if installed) or OCR.space API."
__CATEGORY__ = "Utilities"

def has_tesseract():
    return shutil.which("tesseract") is not None

try:
    import pytesseract
    from PIL import Image
    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False

OCR_API_URL = "https://api.ocr.space/parse/image"
# OCR.space's documented free key for light use is "helloworld" (25k calls/month,
# no card). Set OCR_SPACE_API_KEY in Secrets to use your own free key instead.
OCR_API_KEY = (os.getenv("OCR_SPACE_API_KEY") or "helloworld").strip()

#------------------------------
#Backends
#------------------------------

async def ocr_local(image_data):
    """Extract text using local Tesseract."""
    if not HAS_PYTESSERACT:
        return None, "pytesseract not installed. Install: pip install pytesseract pillow"
    if not has_tesseract():
        return None, "Tesseract binary not found. Install: nix-env -iA nixpkgs.tesseract"
    try:
        img = Image.open(BytesIO(image_data))
        text = pytesseract.image_to_string(img)
        return text.strip(), None
    except Exception as e:
        return None, f"Local OCR error: {e}"

async def ocr_api(image_data, language="eng"):
    """OCR.space free tier, via the shared HTTP layer.

    The old version opened a fresh session per attempt, retried 502s blindly and
    never distinguished a quota error from a bad image: OCR.space answers 200
    with ``IsErroredOnProcessing``/``ErrorMessage`` when the key is throttled, so
    the message now says so instead of "No text found".
    """
    payload = {
        "base64Image": "data:image/png;base64," + base64.b64encode(image_data).decode("utf-8"),
        "language": language,
        "isOverlayRequired": False,
        "detectOrientation": True,
        "scale": True,
        "OCREngine": 2,
    }
    try:
        data = await api.post_json(
            OCR_API_URL,
            payload,
            provider="ocr.space",
            headers={"apikey": OCR_API_KEY},
            timeout=35,
            retries=1,
        )
    except api.RateLimited as exc:
        wait = exc.retry_after or 60
        return None, f"OCR.space rate limit reached — retry in ~{wait}s"
    except api.APIError as exc:
        return None, f"OCR.space unavailable ({exc.describe()})"

    if data.get("IsErroredOnProcessing"):
        message = data.get("ErrorMessage") or "Unknown error"
        if isinstance(message, list):
            message = "; ".join(str(part) for part in message)
        lowered = str(message).lower()
        if "rate limit" in lowered or "quota" in lowered or "exceeded" in lowered:
            return None, f"OCR.space quota/rate limit: {message}"
        return None, f"OCR error: {message}"

    parsed = data.get("ParsedResults") or []
    if not parsed:
        return None, "No text found in the image."
    text = (parsed[0].get("ParsedText") or "").strip()
    return text, None

#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!ocr$"))
    async def ocr_handler(event):
        if not event.is_reply:
            await event.reply("❌ Reply to an image to extract text.")
            return

        reply_msg = await event.get_reply_message()
        if not reply_msg.media:
            await event.reply("❌ The replied message has no media.")
            return

        try:
            bio = BytesIO()
            await reply_msg.download_media(file=bio)
            bio.seek(0)
            image_data = bio.read()
        except Exception as e:
            await event.reply(f"❌ Failed to download image: {e}")
            return

        await event.edit("🔍 OCR in progress...")

        text, error = await ocr_local(image_data)
        if text:
            await output_result(event, client, text)
            return
        # Keep the local reason: the failure message used to print the *API*
        # error twice, because the second call had already overwritten `error`.
        local_error = error
        log.info("ocr: local attempt failed (%s)", error)

        text, error = await ocr_api(image_data)
        if text:
            await output_result(event, client, text)
            return
        await event.edit(f"❌ OCR failed.\nLocal: {local_error}\nAPI: {error}")

async def output_result(event, client, text):
    if not text:
        await event.edit("❌ No text detected.")
        return
    output = f"📝 **Extracted Text:**\n\n{text}"
    if len(output) > 4000:
        import io
        bio = io.BytesIO(text.encode('utf-8'))
        bio.name = "ocr_result.txt"
        await client.send_file(await tgsend.peer(event), bio, caption="📝 OCR Result")
        await event.delete()
    else:
        await event.edit(output)