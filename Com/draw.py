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
import Com.core.tgsend as tgsend

from Com.core import brand
from Com.core.reply import say
import Com.core.api as api

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
        return None, (
            "<b>Image service is rate limiting this IP</b> — try again in "
            f"~<code>{wait}s</code>."
        )
    except api.APIError as exc:
        return None, f"<b>Image service unavailable.</b> {brand.esc(exc.describe())}"
    except Exception as exc:  # noqa: BLE001
        log.exception("draw: unexpected failure")
        return None, (
            f"<b>{brand.esc(type(exc).__name__)}</b> · {brand.esc(exc)}"
        )

    if not body:
        return None, "<b>Image service returned an empty response.</b>"
    if not body[:3] == b"\xff\xd8\xff" and not body[:8] == b"\x89PNG\r\n\x1a\n":
        # Pollinations returns a text error page when a prompt is refused.
        snippet = body[:200].decode("utf-8", errors="replace").strip()
        return None, (
            f"<b>Image service refused the request.</b> {brand.esc(snippet)}"
        )
    return body, None


def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!draw\s+([\s\S]+)$"))
    async def draw_cmd(event):
        prompt = (event.pattern_match.group(1) or "").strip()
        if not prompt:
            await say(
                event,
                "❌ <b>No prompt.</b> Example: <code>!draw a cat in space</code>",
                name="draw",
                parse_mode="html",
            )
            return

        await say(
            event,
            f"🎨 <b>Generating</b> · <code>{brand.esc(prompt)}</code> … (10-60s)",
            name="draw",
            parse_mode="html",
        )

        image_bytes, error = await generate_image(prompt)
        if error:
            await say(
                event,
                f"❌ {error}",
                name="draw",
                parse_mode="html",
            )
            return

        bio = BytesIO(image_bytes)
        bio.name = "generated.jpg"
        try:
            await client.send_file(
                await tgsend.peer(event),
                bio,
                caption=brand.sign(
                    f"🖼️ <b>{brand.esc(prompt)}</b>", "draw"
                ),
                parse_mode="html",
                reply_to=event.id,
            )
            await event.delete()
        except Exception as exc:  # noqa: BLE001
            log.exception("draw: could not send image")
            await say(
                event,
                f"❌ <b>Generated the image but could not send it.</b> "
                f"{brand.esc(exc)}",
                name="draw",
                parse_mode="html",
            )
