"""`!decodeqr` -- decode a QR code from a replied image.

Uses api.qrserver.com, which is free and needs no key. The endpoint is small and
can throttle bursty use, so the call goes through ``Com.api`` (timeout, one
retry on 5xx, explicit 429 handling) and the reply says what happened rather
than surfacing an exception.
"""
import logging
from io import BytesIO

import aiohttp
from telethon import events

import Com.core.api as api

__HELP__ = "!decodeqr → Decode a QR code from a replied image (free, keyless API)"
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.decodeqr")

DECODE_URL = "https://api.qrserver.com/v1/read-qr-code/"


async def decode(image_bytes):
    """Return the decoded strings. Raises APIError on failure."""
    form = aiohttp.FormData()
    form.add_field("file", image_bytes, filename="qr.png", content_type="image/png")
    body = await api.post_form(
        DECODE_URL, form, provider="qrserver", timeout=20, retries=1
    )
    try:
        import json

        payload = json.loads(body)
    except ValueError:
        raise api.APIError("returned invalid JSON", provider="qrserver") from None

    decoded = []
    for item in payload:
        for symbol in item.get("symbol", []):
            text = symbol.get("data")
            if text:
                decoded.append(text)
    return decoded


def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!decodeqr$"))
    async def decode_qr(event):
        if not event.is_reply:
            await _reply(event, "❌ Reply to an image containing a QR code.")
            return

        reply = await event.get_reply_message()
        if not reply or not reply.media:
            await _reply(event, "❌ The replied message has no media.")
            return

        bio = BytesIO()
        try:
            await reply.download_media(file=bio)
        except Exception as exc:  # noqa: BLE001
            await _reply(event, f"❌ Could not download the image: {exc}")
            return
        bio.seek(0)

        try:
            decoded = await decode(bio.read())
        except api.RateLimited as exc:
            wait = exc.retry_after or 30
            await _reply(event, f"⏳ QR service is rate limiting this IP — retry in ~{wait}s.")
            return
        except api.APIError as exc:
            await _reply(event, f"❌ QR decode failed ({exc.describe()}).")
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("decodeqr: unexpected failure")
            await _reply(event, f"❌ {type(exc).__name__}: {exc}")
            return

        if not decoded:
            await _reply(event, "❌ No QR code found in that image.")
            return
        await _reply(event, "🔓 Decoded QR Code:\n" + "\n".join(decoded))

    async def _reply(event, text):
        try:
            await event.reply(text)
        except Exception:
            try:
                await event.edit(text)
            except Exception:
                log.info("decodeqr: response could not be delivered")
