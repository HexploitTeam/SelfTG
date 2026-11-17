# Com/shorturl.py
"""`!shorturl` -- keyless link shortening with a fallback.

Previously: TinyURL only, and Bitly behind an account-bound token that was the
sole path whenever the user typed "bitly".

Now: TinyURL first, is.gd second (both free, keyless, no signup). Bitly stays
available but only when ``BITLY_TOKEN`` is present, and it is now a preference
rather than a hard dependency -- if it fails, the keyless providers still answer.
The log file is written through ``Com.storage.save_json`` so a Replit restart
mid-write can no longer truncate it.
"""
import logging
import os
from urllib.parse import quote

from telethon import events

import Com.api as api
from Com.storage import load_json, save_json

__HELP__ = (
    "!shorturl <link> or reply → Shorten a URL (TinyURL → is.gd, both keyless)\n"
    "!shorturl bitly <link> → Use Bitly instead (needs BITLY_TOKEN in Secrets)"
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.shorturl")

BITLY_TOKEN = os.getenv("BITLY_TOKEN")
LOG_FILE = "mode/shorturl/shorturl_log.json"
os.makedirs("mode", exist_ok=True)

TINYURL_API = "https://tinyurl.com/api-create.php"
ISGD_API = "https://is.gd/create.php"
BITLY_API = "https://api-ssl.bitly.com/v4/shorten"


async def tinyurl(url):
    text = await api.fetch_text(
        TINYURL_API, params={"url": url}, provider="tinyurl", timeout=10
    )
    text = text.strip()
    if not text.startswith("http"):
        raise api.APIError("did not return a short link", provider="tinyurl")
    return text


async def isgd(url):
    text = await api.fetch_text(
        ISGD_API,
        params={"format": "simple", "url": url},
        provider="is.gd",
        timeout=10,
    )
    text = text.strip()
    if not text.startswith("http"):
        raise api.APIError("did not return a short link", provider="is.gd")
    return text


async def bitly(url):
    if not BITLY_TOKEN:
        raise api.APIError("BITLY_TOKEN is not set", provider="bitly")
    data = await api.post_json(
        BITLY_API,
        {"long_url": url},
        provider="bitly",
        headers={"Authorization": f"Bearer {BITLY_TOKEN}"},
        timeout=10,
    )
    link = data.get("link")
    if not link:
        raise api.APIError("did not return a short link", provider="bitly")
    return link


async def shorten(url, service="auto"):
    if service == "bitly":
        attempts = [("bitly", lambda: bitly(url))]
    else:
        attempts = [("tinyurl", lambda: tinyurl(url)), ("is.gd", lambda: isgd(url))]
    return await api.first_success(attempts)


def log_url(original, short, service):
    """Append to the log, tolerating a corrupt or missing file."""
    data = load_json(LOG_FILE, [])
    if not isinstance(data, list):
        data = []
    data.append({"original": original, "short": short, "service": service})
    try:
        save_json(LOG_FILE, data[-500:])  # keep the log bounded
    except Exception:  # noqa: BLE001 - logging must never break the command
        log.info("shorturl: could not write log entry")


def setup(client, my_id):
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!shorturl(?:\s+(\S+))?(?:\s+(\S+))?")
    )
    async def shorturl(event):
        first = event.pattern_match.group(1)
        second = event.pattern_match.group(2)

        service = "auto"
        url = first
        if first and first.lower() in ("tinyurl", "isgd", "is.gd", "bitly"):
            service = "bitly" if first.lower() == "bitly" else "auto"
            url = second

        if not url and event.is_reply:
            reply = await event.get_reply_message()
            url = (reply.raw_text or "").strip() if reply else ""

        if not url:
            await _reply(event, "❌ Provide a URL or reply to a message containing one.")
            return

        if not url.lower().startswith("http"):
            url = "https://" + url

        try:
            short_link = await shorten(url, service)
        except api.APIError as exc:
            await _reply(
                event,
                f"❌ Could not shorten that link.\nProviders tried: {exc}",
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("shorturl: unexpected failure")
            await _reply(event, f"❌ {type(exc).__name__}: {exc}")
            return

        await _reply(event, f"🔗 {short_link}")
        log_url(url, short_link, service)

    async def _reply(event, text):
        try:
            await event.reply(text)
        except Exception:
            try:
                await event.edit(text)
            except Exception:
                log.info("shorturl: response could not be delivered")
