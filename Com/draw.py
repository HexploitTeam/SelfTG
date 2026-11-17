# Com/draw.py
"""`!draw` -- text-to-image through Pollinations' keyless Classic API.

Why this replaced Hugging Face
------------------------------
The old implementation required ``HF_API_TOKEN`` and called
``api-inference.huggingface.co`` with ``runwayml/stable-diffusion-v1-5``. Both
halves are gone: that model was removed from the free Inference API, and the
service now meters inference through paid credits, so a free Replit bot could
not rely on it.

Pollinations' Classic API (``image.pollinations.ai/prompt/<text>``) still serves
one image model with **no key, no signup and no payment**. It is best effort:
rate limited per IP, capped at 768x768, returns JPEG with a small logo, and can
refuse prompts. Every one of those cases is reported as a normal message; none
of them can raise into the Telethon client.
"""
import logging
import time
from io import BytesIO
from urllib.parse import quote

from telethon import events
import Com.tgsend as tgsend

import Com.api as api

__HELP__ = (
    "!draw <prompt> → Generate an image from a text prompt (Pollinations, no key)\n"
    "Example: !draw a cat wearing a hat"
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.draw")

IMAGE_URL = "https://image.pollinations.ai/prompt/{prompt}"
MAX_PROMPT = 500


async def generate_image(prompt):
    """Return (image_bytes, error_text). Never raises."""
    url = IMAGE_URL.format(prompt=quote(prompt[:MAX_PROMPT], safe=""))
    try:
        body = await api.fetch_bytes(
            url,
            params={"width": 768, "height": 768, "seed": int(time.time()) % 100000},
            provider="pollinations",
            timeout=90,   # diffusion on a shared queue can take 20-60s
            retries=0,
        )
    except api.RateLimited as exc:
        wait = exc.retry_after or 30
        return None, f"Image service is rate limiting this IP — try again in ~{wait}s."
    except api.APIError as exc:
        return None, f"Image service unavailable ({exc.describe()})."
    except Exception as exc:  # noqa: BLE001
        log.exception("draw: unexpected failure")
        return None, f"{type(exc).__name__}: {exc}"

    if not body:
        return None, "Image service returned an empty response."
    if not body[:3] == b"\xff\xd8\xff" and not body[:8] == b"\x89PNG\r\n\x1a\n":
        # Pollinations returns a text error page when a prompt is refused.
        snippet = body[:200].decode("utf-8", errors="replace").strip()
        return None, f"Image service refused the request: {snippet}"
    return body, None


def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!draw\s+([\s\S]+)$"))
    async def draw_cmd(event):
        prompt = (event.pattern_match.group(1) or "").strip()
        if not prompt:
            await _safe_edit(event, "❌ Please provide a prompt. Example: `!draw a cat in space`")
            return

        await _safe_edit(event, f"🎨 Generating: `{prompt}` … (10-60s)")

        image_bytes, error = await generate_image(prompt)
        if error:
            await _safe_edit(event, f"❌ {error}")
            return

        bio = BytesIO(image_bytes)
        bio.name = "generated.jpg"
        try:
            await client.send_file(await tgsend.peer(event),
                bio,
                caption=f"🖼️ {prompt}",
                reply_to=event.id,
            )
            await event.delete()
        except Exception as exc:  # noqa: BLE001
            log.exception("draw: could not send image")
            await _safe_edit(event, f"❌ Generated the image but could not send it: {exc}")

    async def _safe_edit(event, text):
        try:
            await event.edit(text)
        except Exception:
            try:
                await event.reply(text)
            except Exception:
                log.info("draw: response could not be delivered")
