# Com/ocr.py
import aiohttp
import asyncio
import base64
import subprocess
import shutil
from io import BytesIO
from telethon import events

__HELP__ = "!ocr (reply to image) → Extract text from an image using local Tesseract (if installed) or OCR.space API."
__CATEGORY__ = "Utilities"

# Check if Tesseract is installed
def has_tesseract():
    return shutil.which("tesseract") is not None

# Try to import pytesseract if available
try:
    import pytesseract
    from PIL import Image
    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False

OCR_API_URL = "https://api.ocr.space/parse/image"

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

async def ocr_api(image_data, language="eng", retries=3):
    """Use OCR.space API with retries."""
    image_base64 = base64.b64encode(image_data).decode('utf-8')
    payload = {
        "base64Image": f"data:image/png;base64,{image_base64}",
        "language": language,
        "isOverlayRequired": False,
        "detectOrientation": True,
        "scale": True,
        "OCREngine": 2,
    }
    headers = {
        "Content-Type": "application/json",
        "apikey": "helloworld"
    }
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(OCR_API_URL, json=payload, headers=headers, timeout=30) as resp:
                    if resp.status != 200:
                        # If it's 502, retry after delay
                        if resp.status == 502 and attempt < retries-1:
                            await asyncio.sleep(2)
                            continue
                        return None, f"API returned HTTP {resp.status}"
                    data = await resp.json()
                    if data.get("IsErroredOnProcessing"):
                        error = data.get("ErrorMessage", "Unknown error")
                        return None, f"OCR error: {error}"
                    parsed = data.get("ParsedResults", [])
                    if not parsed:
                        return None, "No text found in the image."
                    text = parsed[0].get("ParsedText", "").strip()
                    return text, None
        except asyncio.TimeoutError:
            if attempt < retries-1:
                await asyncio.sleep(2)
                continue
            return None, "API request timed out"
        except Exception as e:
            if attempt < retries-1:
                await asyncio.sleep(2)
                continue
            return None, f"API error: {e}"
    return None, "All API retries failed"

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

        # Download image
        try:
            bio = BytesIO()
            await reply_msg.download_media(file=bio)
            bio.seek(0)
            image_data = bio.read()
        except Exception as e:
            await event.reply(f"❌ Failed to download image: {e}")
            return

        await event.edit("🔍 OCR in progress...")

        # Try local first
        text, error = await ocr_local(image_data)
        if text:
            await output_result(event, client, text)
            return
        else:
            print(f"[OCR] Local failed: {error}")

        # Fallback to API
        text, error = await ocr_api(image_data)
        if text:
            await output_result(event, client, text)
            return
        else:
            await event.edit(f"❌ OCR failed.\nLocal: {error}\nAPI: {error}")
            return

async def output_result(event, client, text):
    if not text:
        await event.edit("❌ No text detected.")
        return
    output = f"📝 **Extracted Text:**\n\n{text}"
    if len(output) > 4000:
        import io
        bio = io.BytesIO(text.encode('utf-8'))
        bio.name = "ocr_result.txt"
        await client.send_file(event.chat_id, bio, caption="📝 OCR Result")
        await event.delete()
    else:
        await event.edit(output)