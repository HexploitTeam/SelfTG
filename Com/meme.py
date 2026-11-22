"""`!meme` -- classic meme templates captioned through memegen.link.

memegen.link is a stateless URL generator: no key, no account, no rate limit
worth tracking, and the image is built from the URL. That makes it a better fit
for the free tier than scraping a random meme from Reddit, where the result can
be huge, unstable or not safe for every chat.

Twelve templates are curated locally, with their real line counts read from
`api.memegen.link/templates`, so `!meme list` is a fixed list rather than a
90 KB download per call. Picking a template is optional: with none, one of the
two-line templates is chosen at random.

The image itself is fetched through `Com/core/api.py` and sent as a file; the
message body is a signed caption, never a bare URL.
"""
import logging
import random
from io import BytesIO
from urllib.parse import quote

from telethon import events

import Com.core.api as api
import Com.core.tgsend as tgsend
from Com.core import brand
from Com.core.reply import say

__HELP__ = (
    "!meme <top text> | <bottom text> → Caption a random template\n"
    "!meme <template> <top text> | <bottom text> → Pick the template\n"
    "!meme <template> <text> → One line, when the template needs one\n"
    "!meme list → Show the available templates and line counts\n"
    "Example: !meme drake writing docs | shipping without them"
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.meme")

IMAGE_URL = "https://api.memegen.link/images/{template}/{path}.png"
MAX_LINE = 120
MAX_BYTES = 5 * 1024 * 1024
IMAGE_WIDTH = 600

# id -> (label, number of text lines the template takes)
TEMPLATES = {
    "drake": ("Drakeposting", 2),
    "success": ("Success Kid", 2),
    "fine": ("This Is Fine", 2),
    "rollsafe": ("Roll Safe", 2),
    "both": ("Why Not Both?", 2),
    "spiderman": ("Spider-Man Pointing", 2),
    "woman-cat": ("Woman Yelling at a Cat", 2),
    "buzz": ("X, X Everywhere", 2),
    "grumpycat": ("Grumpy Cat", 2),
    "db": ("Distracted Boyfriend", 3),
    "pigeon": ("Is This a Pigeon?", 3),
    "gru": ("Gru's Plan", 4),
}

RANDOM_TEMPLATES = [name for name, (_, lines) in TEMPLATES.items() if lines == 2]

_IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF8", b"RIFF")


#------------------------------
#Encoding and rendering
#------------------------------

def encode_line(text):
    """memegen's path escaping: `_` for space, `__` for a literal underscore."""
    text = " ".join(str(text).split())[:MAX_LINE]
    # Underscores and dashes double first, or the space rule would eat them
    for old, new in (
        ("_", "__"), ("-", "--"), ("?", "~q"), ("&", "~a"), ("%", "~p"),
        ("#", "~h"), ("/", "~s"), ("\\", "~b"), ("<", "~l"), (">", "~g"),
        ('"', "''"),
    ):
        text = text.replace(old, new)
    return text.replace(" ", "_")


def build_url(template, lines):
    path = "/".join(encode_line(line) for line in lines)
    path = quote(f"{template}/{path}", safe="/-_.~")
    return IMAGE_URL.format(template=template, path=path)


def _is_image(body):
    return any(body.startswith(magic) for magic in _IMAGE_MAGIC)


def render_list():
    lines = ["🖼️ <b>Meme templates</b>", ""]
    for name, (label, count) in sorted(TEMPLATES.items(),
                                       key=lambda item: item[1][0]):
        lines.append(
            f"<code>{brand.esc(name)}</code> · {brand.esc(label)} "
            f"<i>({count} line{'s' if count != 1 else ''})</i>"
        )
    lines.append("")
    lines.append(
        "Usage · <code>!meme drake top text | bottom text</code>\n"
        "Without a template, a random two-line one is used."
    )
    return "\n".join(lines)


#------------------------------
#Image
#------------------------------

async def generate(template, lines):
    """Return (image_bytes, error_text). Never raises."""
    url = build_url(template, lines)
    try:
        body = await api.fetch_bytes(
            url,
            params={"width": IMAGE_WIDTH},
            provider="memegen",
            timeout=20,
            retries=0,
        )
    except api.RateLimited as exc:
        wait = exc.retry_after or 30
        return None, (
            "<b>Meme service is rate limiting this IP</b> — try again in "
            f"~<code>{wait}s</code>."
        )
    except api.APIError as exc:
        return None, f"<b>Meme service unavailable.</b> {brand.esc(exc.describe())}"
    except Exception as exc:  # noqa: BLE001
        log.exception("meme: unexpected failure")
        return None, f"<b>{brand.esc(type(exc).__name__)}</b> · {brand.esc(exc)}"

    if not body:
        return None, "<b>The meme service returned an empty response.</b>"
    if len(body) > MAX_BYTES:
        return None, "<b>The generated image was too large to send.</b>"
    if not _is_image(body):
        snippet = body[:200].decode("utf-8", errors="replace").strip()
        return None, (
            f"<b>The meme service returned something that is not an image.</b> "
            f"{brand.esc(snippet)}"
        )
    return body, None


#------------------------------
#Command
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!meme(?:\s+([\s\S]+))?$"))
    async def meme_cmd(event):
        raw = (event.pattern_match.group(1) or "").strip()
        if not raw or raw.lower() in ("help", "?"):
            await say(
                event,
                "📖 <b>Meme help</b>\n" + brand.esc(__HELP__),
                name="meme",
                parse_mode="html",
            )
            return
        if raw.lower() in ("list", "templates"):
            await say(event, render_list(), name="meme", parse_mode="html")
            return

        head, _, rest = raw.partition(" ")
        template = None
        if head.lower() in TEMPLATES:
            template = head.lower()
            text = rest.strip()
        else:
            text = raw

        if not text:
            await say(
                event,
                f"❌ <b>No caption text.</b> {brand.esc(TEMPLATES[template][0])} "
                "needs text.\nExample · <code>!meme "
                f"{brand.esc(template)} top text | bottom text</code>",
                name="meme",
                parse_mode="html",
            )
            return

        parts = [part.strip() for part in text.split("|", 1)]
        lines = [part for part in parts if part]
        if not lines:
            await say(
                event,
                "❌ <b>No caption text.</b> Example · "
                "<code>!meme top text | bottom text</code>",
                name="meme",
                parse_mode="html",
            )
            return

        if template is None:
            template = random.SystemRandom().choice(RANDOM_TEMPLATES)
        label = TEMPLATES[template][0]

        image, error = await generate(template, lines)
        if error:
            await say(event, f"❌ {error}", name="meme", parse_mode="html")
            return

        bio = BytesIO(image)
        bio.name = f"{template}.png"
        try:
            await client.send_file(
                await tgsend.peer(event),
                bio,
                caption=brand.sign(
                    f"🖼️ <b>{brand.esc(label)}</b> · "
                    f"<code>{brand.esc(template)}</code>",
                    "meme",
                ),
                parse_mode="html",
                reply_to=event.id,
            )
        except Exception as exc:  # noqa: BLE001 - the image is already built
            log.exception("meme: could not send the image")
            await say(
                event,
                f"❌ <b>Generated the meme but could not send it.</b> "
                f"{brand.esc(exc)}",
                name="meme",
                parse_mode="html",
            )
            return

        try:
            await event.delete()
        except Exception:  # noqa: BLE001
            log.info("meme: could not delete the command message")
