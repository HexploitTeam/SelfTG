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
from Com.core import brand
from Com.core.reply import say

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
            await _reply(event, "❌ <b>Reply to an image containing a QR code.</b>")
            return

        reply = await event.get_reply_message()
        if not reply or not reply.media:
            await _reply(event, "❌ <b>The replied message has no media.</b>")
            return

        bio = BytesIO()
        try:
            await reply.download_media(file=bio)
        except Exception as exc:  # noqa: BLE001
            await _reply(event, f"❌ Could not download the image · {brand.esc(exc)}")
            return
        bio.seek(0)

        try:
            decoded = await decode(bio.read())
        except api.RateLimited as exc:
            wait = exc.retry_after or 30
            await _reply(
                event,
                f"⏳ <b>QR service is rate limiting this IP</b> · retry in ~"
                f"<code>{wait}s</code>.",
            )
            return
        except api.APIError as exc:
            await _reply(event, f"❌ QR decode failed · {brand.esc(exc.describe())}")
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("decodeqr: unexpected failure")
            await _reply(event, f"❌ <code>{brand.esc(type(exc).__name__)}</code> · {brand.esc(exc)}")
            return

        if not decoded:
            await _reply(event, "❌ <b>No QR code found in that image.</b>")
            return
        await _reply(
            event,
            "🔓 <b>Decoded QR code</b>\n"
            + "\n".join(f"<code>{brand.esc(item)}</code>" for item in decoded),
        )

    async def _reply(event, text):
        # Edit-then-reply is shared: see Com/core/reply.py.
        await say(event, text, name="decodeqr", parse_mode="html")
