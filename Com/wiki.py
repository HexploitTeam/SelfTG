"""`!wiki` -- Wikipedia summaries with a DuckDuckGo Instant Answer fallback.

Both providers are free and keyless:
  * Wikipedia REST ``page/summary`` -- no key, no hard quota, but asks clients to
    be polite; results are cached here for an hour.
  * DuckDuckGo Instant Answer API -- no key, low undocumented limits, used only
    when Wikipedia has no article or is unreachable.
"""
import logging
from urllib.parse import quote

from telethon import events

from Com.core import brand
from Com.core.reply import say
import Com.core.api as api

__HELP__ = (
    "!wiki <term> → Wikipedia summary (optional language first: !wiki fa تهران)\n"
    "Example: !wiki Alan Turing   |   !wiki de Berlin"
)
__CATEGORY__ = "Information"

log = logging.getLogger("selftg.wiki")

SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
DUCK_URL = "https://api.duckduckgo.com/"

MAX_CHARS = 900
SOURCE_LINE = "\n\n<i>%s</i>"


def _clean(text):
    text = (text or "").strip()
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 1].rstrip() + "…"
    return text


async def _wikipedia(lang, term):
    data = await api.fetch_json(
        SUMMARY_URL.format(lang=lang, title=quote(term.replace(" ", "_"), safe="")),
        provider=f"wikipedia({lang})",
        cache_ttl=3600,
        timeout=10,
        headers={"Accept": "application/json"},
    )
    extract = _clean(data.get("extract"))
    if not extract:
        raise api.APIError("no article text", provider=f"wikipedia({lang})")

    lines = [f"📚 <b>{brand.esc(data.get('title', term))}</b>"]
    if data.get("description"):
        lines.append(f"<i>{brand.esc(data['description'])}</i>")
    lines.append("")
    lines.append(brand.esc(extract))
    if data.get("type") == "disambiguation":
        lines.append("\n⚠️ This is a disambiguation page — try a more specific term.")
    page = ((data.get("content_urls") or {}).get("desktop") or {}).get("page")
    lines.append(
        SOURCE_LINE
        % brand.esc("Wikipedia · " + page if page else "Wikipedia")
    )
    return "\n".join(lines)


async def _duckduckgo(term):
    data = await api.fetch_json(
        DUCK_URL,
        params={"q": term, "format": "json", "no_html": 1, "skip_disambig": 1},
        provider="duckduckgo",
        cache_ttl=1800,
        timeout=10,
    )
    abstract = _clean(data.get("AbstractText"))
    if not abstract:
        raise api.APIError("no instant answer", provider="duckduckgo")
    heading = data.get("Heading") or term
    lines = [f"🦆 <b>{brand.esc(heading)}</b>", "", brand.esc(abstract)]
    url = data.get("AbstractURL")
    if url:
        lines.append(SOURCE_LINE % brand.esc("DuckDuckGo · " + url))
    return "\n".join(lines)


async def lookup(lang, term):
    return await api.first_success([
        (f"wikipedia({lang})", lambda: _wikipedia(lang, term)),
        ("duckduckgo", lambda: _duckduckgo(term)),
    ])


def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!wiki(?:\s+([\s\S]+))?$"))
    async def wiki_cmd(event):
        args = (event.pattern_match.group(1) or "").strip()
        if not args:
            await say(
                event,
                "Usage: <code>!wiki &lt;term&gt;</code> "
                "(optional language code first)",
                name="wiki",
                parse_mode="html",
            )
            return

        lang = "en"
        term = args
        head, _, rest = args.partition(" ")
        if len(head) == 2 and head.isalpha() and rest.strip():
            lang, term = head.lower(), rest.strip()

        try:
            text = await lookup(lang, term)
        except api.APIError as exc:
            await say(
                event,
                f"❌ <b>Nothing found for</b> {brand.esc(term)} "
                f"({brand.esc(exc)}).\n"
                "Both Wikipedia and DuckDuckGo came back empty or rate limited.",
                name="wiki",
                parse_mode="html",
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("wiki: unexpected failure")
            await say(
                event,
                f"❌ <b>{brand.esc(type(exc).__name__)}</b> · {brand.esc(exc)}",
                name="wiki",
                parse_mode="html",
            )
            return
        await say(event, text, name="wiki", parse_mode="html")
