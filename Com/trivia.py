# Com/trivia.py
"""`!trivia` -- a group-friendly quiz question from the free Open Trivia DB.

Open Trivia DB needs no account, no key and no payment. Its published limits are
one request every ~5 seconds per IP, so this module enforces a local 5s gate and
reports the wait instead of hammering the endpoint. Session tokens (also free)
stop the same question repeating; when the token expires the module silently
requests a fresh one.
"""
import asyncio
import html
import logging
import time
from urllib.parse import unquote

from telethon import events

import Com.api as api
from Com.storage import load_json, save_json

__HELP__ = (
    "!trivia → Ask a random multiple-choice question in this chat\n"
    "!trivia <category> → Same, from a category (general, books, film, music,\n"
    "   science, computers, maths, sports, geography, history, animals)\n"
    "The answer is revealed by editing the question after 20 seconds."
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.trivia")

API_URL = "https://opentdb.com/api.php"
TOKEN_URL = "https://opentdb.com/api_token.php"
TOKEN_FILE = "mode/trivia_token.json"

REVEAL_DELAY = 20
MIN_INTERVAL = 5.0  # Open Trivia DB asks for ~1 request / 5s per IP

CATEGORIES = {
    "general": 9, "books": 10, "film": 11, "music": 12,
    "theatre": 13, "tv": 14, "video-games": 32, "board-games": 16,
    "science": 17, "computers": 18, "maths": 19, "math": 19,
    "sports": 21, "geography": 22, "history": 23, "politics": 24,
    "art": 25, "celebrities": 26, "animals": 27,
}

_last_call = 0.0


def _decode(value):
    return html.unescape(unquote(value or ""))


async def _get_token(force_new=False):
    """Return a session token, requesting one only when needed."""
    if not force_new:
        stored = load_json(TOKEN_FILE, {})
        token = stored.get("token") if isinstance(stored, dict) else None
        if token:
            return token
    data = await api.fetch_json(
        TOKEN_URL, params={"command": "request"}, provider="opentdb token", timeout=10
    )
    token = data.get("token")
    if not token:
        return None
    save_json(TOKEN_FILE, {"token": token, "created": time.time()})
    return token


async def fetch_question(category=None):
    """Return a normalised question dict, retrying once with a fresh token."""
    global _last_call
    wait = MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        raise api.RateLimited(
            f"local 5s gate, wait {int(wait) + 1}s", provider="opentdb",
            retry_after=int(wait) + 1,
        )

    params = {"amount": 1, "type": "multiple", "encode": "url3986"}
    category_id = CATEGORIES.get((category or "").strip().lower())
    if category_id:
        params["category"] = category_id

    token = await _get_token()
    if token:
        params["token"] = token

    _last_call = time.monotonic()
    data = await api.fetch_json(
        API_URL, params=params, provider="opentdb", timeout=12, retries=0
    )
    code = data.get("response_code")

    # 3 = token exhausted, 4 = token expired: both mean "fetch a new token".
    if code in (3, 4):
        token = await _get_token(force_new=True)
        if token:
            params["token"] = token
        _last_call = time.monotonic()
        data = await api.fetch_json(
            API_URL, params=params, provider="opentdb", timeout=12, retries=0
        )
        code = data.get("response_code")

    if code == 5:
        raise api.RateLimited("provider reports rate limiting", provider="opentdb", retry_after=6)
    if code == 1:
        raise api.APIError("not enough questions for that category", provider="opentdb")
    if code != 0:
        raise api.APIError(f"unexpected response code {code}", provider="opentdb")

    results = data.get("results") or []
    if not results:
        raise api.APIError("empty result", provider="opentdb")

    item = results[0]
    answers = [_decode(a) for a in item.get("incorrect_answers", [])]
    correct = _decode(item.get("correct_answer"))
    options = answers + [correct]
    # Deterministic-but-varied shuffle without importing random state elsewhere.
    options.sort(key=lambda value: (hash(value + correct) & 0xFFFF))
    return {
        "category": _decode(item.get("category")),
        "difficulty": _decode(item.get("difficulty")),
        "question": _decode(item.get("question")),
        "correct": correct,
        "options": options,
    }


def render(question, revealed=False):
    letters = "ABCD"
    lines = [
        f"🎲 **Trivia** · {question['category']} · _{question['difficulty']}_",
        "",
        question["question"],
        "",
    ]
    for index, option in enumerate(question["options"][:4]):
        marker = "✅" if revealed and option == question["correct"] else f"**{letters[index]}**"
        lines.append(f"{marker}) {option}")
    lines.append("")
    if revealed:
        lines.append(f"Answer: **{question['correct']}**")
    else:
        lines.append(f"_Answer in {REVEAL_DELAY}s…_")
    return "\n".join(lines)


def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!trivia(?:\s+([\w-]+))?$"))
    async def trivia_cmd(event):
        category = (event.pattern_match.group(1) or "").strip().lower() or None
        if category and category not in CATEGORIES:
            await _safe_edit(
                event,
                "❌ Unknown category. Try one of: "
                + ", ".join(sorted(CATEGORIES)),
            )
            return

        try:
            question = await fetch_question(category)
        except api.RateLimited as exc:
            wait = exc.retry_after or 6
            await _safe_edit(event, f"⏳ Trivia is cooling down — try again in {wait}s.")
            return
        except api.APIError as exc:
            await _safe_edit(
                event, f"❌ Could not fetch a question ({exc.describe()}). Try again shortly."
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("trivia: unexpected failure")
            await _safe_edit(event, f"❌ {type(exc).__name__}: {exc}")
            return

        await _safe_edit(event, render(question))
        await asyncio.sleep(REVEAL_DELAY)
        try:
            await event.edit(render(question, revealed=True))
        except Exception as exc:  # noqa: BLE001 - message may be gone
            log.info("trivia: could not reveal answer (%s)", type(exc).__name__)

    async def _safe_edit(event, text):
        try:
            await event.edit(text)
        except Exception:
            try:
                await event.reply(text)
            except Exception:
                log.info("trivia: response could not be delivered")
