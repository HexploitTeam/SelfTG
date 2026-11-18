"""`!translate` -- keyless translation with a real fallback chain.

What was wrong before
---------------------
The module used ``googletrans``, whose ``Translator.translate`` is a *coroutine*
in the versions this project resolves. The old code called it inside
``asyncio.to_thread`` and then read ``result.text``/``result.src``, so the command
returned "'coroutine' object has no attribute 'text'" every single time. It was
broken in the repository, not just fragile.

What it does now
----------------
Calls the same free, keyless Google endpoint googletrans wraps
(``translate.googleapis.com/translate_a/single``) directly with ``aiohttp`` -- no
third-party wrapper, no extra dependency, and a real timeout. If that endpoint
throttles or changes, the text is retried against MyMemory, which is also free
and keyless and accepts ``autodetect`` as the source language.

Both providers are best effort: Google's endpoint is undocumented (it can
throttle per IP) and MyMemory's anonymous tier is roughly 5k characters/day.
"""
import logging
from urllib.parse import quote

from telethon import events

import Com.core.api as api

__HELP__ = (
    "!translate <lang_code> <text> → Translate text (e.g. !translate en سلام)\n"
    "Free and keyless: Google's public endpoint, MyMemory as fallback."
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.translate")

GTX_URL = "https://translate.googleapis.com/translate_a/single"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
MAX_CHARS = 4000


async def _google(text, dest):
    data = await api.fetch_json(
        GTX_URL,
        params={"client": "gtx", "sl": "auto", "tl": dest, "dt": "t", "q": text},
        provider="google-translate",
        timeout=10,
    )
    # Shape: [[["translated","source",...], ...], null, "detected-lang", ...]
    try:
        translated = "".join(part[0] for part in data[0] if part and part[0])
    except (IndexError, TypeError):
        translated = ""
    if not translated:
        raise api.APIError("empty translation", provider="google-translate")
    detected = data[2] if len(data) > 2 and isinstance(data[2], str) else "auto"
    return translated, detected, "google"


async def _mymemory(text, dest):
    data = await api.fetch_json(
        MYMEMORY_URL,
        params={"q": text, "langpair": f"autodetect|{dest}"},
        provider="mymemory",
        timeout=12,
    )
    translated = ((data.get("responseData") or {}).get("translatedText") or "").strip()
    if not translated or str(data.get("responseStatus")) not in ("200", "0"):
        raise api.APIError("no usable translation", provider="mymemory")
    return translated, "auto", "mymemory"


async def translate_text(text, dest):
    """Try Google's endpoint, then MyMemory. Raises APIError if both fail."""
    text = text[:MAX_CHARS]
    return await api.first_success([
        ("google", lambda: _google(text, dest)),
        ("mymemory", lambda: _mymemory(text, dest)),
    ])


def setup(client, my_id):
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!translate\s+(\S+)\s+([\s\S]+)$")
    )
    async def translate(event):
        lang = event.pattern_match.group(1)
        text = event.pattern_match.group(2).strip()
        try:
            translated, source, provider = await translate_text(text, lang)
        except api.APIError as exc:
            await _reply(
                event,
                f"❌ Translation failed ({exc}).\n"
                "Both endpoints are free and keyless, so this is throttling or an "
                "outage — retry in a minute.",
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("translate: unexpected failure")
            await _reply(event, f"❌ {type(exc).__name__}: {exc}")
            return

        await _reply(event, f"🌐 ({source} → {lang}, via {provider}):\n{translated}")

    async def _reply(event, text):
        try:
            await event.reply(text)
        except Exception:
            try:
                await event.edit(text)
            except Exception:
                log.info("translate: response could not be delivered")
