"""`!trivia` -- a quiz question from two free, keyless trivia sources.

Open Trivia DB is primary: no account, no key, one request per ~5 seconds per
IP, and free session tokens that stop the same question repeating. The Trivia
API (`the-trivia-api.com`) is the fallback for when OpenTDB answers 429 / its
rate-limit code 5, or is unreachable; it needs no key either.

Three things the old version got wrong and this one does not:

* its category table mapped ``video-games`` to 32, which OpenTDB serves as
  "Cartoon & Animations"; the video-game category is 15. The table now matches
  ``api_category.php`` and also covers anime, comics, gadgets, vehicles and
  mythology;
* it "shuffled" options with ``sort(key=hash(...))``, which is stable inside one
  process, biased, and different after every restart. It is a real
  ``SystemRandom().shuffle()`` now;
* it only filtered by category. ``!trivia science hard`` works, with the same
  difficulty names on both providers.

The 5-second gate stays global because OpenTDB limits per client IP, not per
chat. It refuses the call instead of queueing, so the command answers "wait Ns"
rather than stalling the event loop.
"""
import asyncio
import html
import logging
import random
import time
from urllib.parse import unquote

from telethon import events

from Com.core import brand
from Com.core.reply import say
import Com.core.api as api
from Com.core.storage import load_json, save_json

__HELP__ = (
    "!trivia → Ask a random multiple-choice question in this chat\n"
    "!trivia <category> → Same, from a category (general, books, film, music,\n"
    "   science, computers, maths, sports, geography, history, animals, anime,\n"
    "   comics, gadgets, mythology, video-games, cartoons, …)\n"
    "!trivia <difficulty> → easy, medium or hard\n"
    "!trivia <category> <difficulty> → Both filters, in any order\n"
    "The answer is revealed by editing the question after 20 seconds."
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.trivia")

API_URL = "https://opentdb.com/api.php"
TOKEN_URL = "https://opentdb.com/api_token.php"
FALLBACK_URL = "https://the-trivia-api.com/api/questions"
TOKEN_FILE = "mode/trivia_token.json"

REVEAL_DELAY = 20
MIN_INTERVAL = 5.0  # Open Trivia DB asks for ~1 request / 5s per IP

# OpenTDB ids, checked against https://opentdb.com/api_category.php
CATEGORIES = {
    "general": 9, "books": 10, "film": 11, "movies": 11, "music": 12,
    "theatre": 13, "musicals": 13, "tv": 14, "video-games": 15,
    "videogames": 15, "board-games": 16, "science": 17, "computers": 18,
    "maths": 19, "math": 19, "mythology": 20, "sports": 21, "geography": 22,
    "history": 23, "politics": 24, "art": 25, "celebrities": 26,
    "animals": 27, "vehicles": 28, "comics": 29, "gadgets": 30, "anime": 31,
    "cartoons": 32,
}

DIFFICULTIES = ("easy", "medium", "hard")

# Canonical alias -> The Trivia API slug. Unmapped categories fall back to a
# random category there and the question says so.
FALLBACK_CATEGORIES = {
    "general": "general_knowledge", "books": "arts_and_literature",
    "film": "film_and_tv", "movies": "film_and_tv", "music": "music",
    "tv": "film_and_tv", "science": "science", "computers": "science",
    "maths": "science", "math": "science", "sports": "sport_and_leisure",
    "geography": "geography", "history": "history",
    "politics": "society_and_culture", "art": "arts_and_literature",
    "celebrities": "society_and_culture", "animals": "science",
    "anime": "film_and_tv", "cartoons": "film_and_tv",
}

_last_call = 0.0


def _decode(value):
    return html.unescape(unquote(value or ""))


#------------------------------
#Client helpers
#------------------------------

async def _get_token(force_new=False):
    """Return a session token, requesting one only when needed."""
    if not force_new:
        stored = load_json(TOKEN_FILE, {})
        token = stored.get("token") if isinstance(stored, dict) else None
        if token:
            return token
    data = await api.fetch_json(
        TOKEN_URL, params={"command": "request"}, provider="opentdb token",
        timeout=10,
    )
    if not isinstance(data, dict):
        raise api.APIError("token endpoint returned an unexpected payload",
                           provider="opentdb token")
    token = data.get("token")
    if not token:
        return None
    save_json(TOKEN_FILE, {"token": token, "created": time.time()})
    return token


def _shuffled(options):
    """Real shuffle; the old hash-sort was biased and changed per process."""
    rng = random.SystemRandom()
    rng.shuffle(options)
    return options


async def _opentdb(category, difficulty):
    params = {"amount": 1, "type": "multiple", "encode": "url3986"}
    category_id = CATEGORIES.get(category or "")
    if category_id:
        params["category"] = category_id
    if difficulty:
        params["difficulty"] = difficulty

    token = await _get_token()
    if token:
        params["token"] = token

    data = await api.fetch_json(
        API_URL, params=params, provider="opentdb", timeout=12, retries=0
    )
    if not isinstance(data, dict):
        raise api.APIError("unexpected payload", provider="opentdb")
    code = data.get("response_code")

    # 3 = token exhausted, 4 = token expired: both mean "fetch a new token".
    if code in (3, 4):
        token = await _get_token(force_new=True)
        if token:
            params["token"] = token
        data = await api.fetch_json(
            API_URL, params=params, provider="opentdb", timeout=12, retries=0
        )
        if not isinstance(data, dict):
            raise api.APIError("unexpected payload", provider="opentdb")
        code = data.get("response_code")

    if code == 5:
        raise api.RateLimited("provider reports rate limiting",
                              provider="opentdb", retry_after=6)
    if code == 1:
        raise api.APIError("not enough questions for that category",
                           provider="opentdb")
    if code != 0:
        raise api.APIError(f"unexpected response code {code}",
                           provider="opentdb")

    results = data.get("results") or []
    if not results:
        raise api.APIError("empty result", provider="opentdb")

    item = results[0]
    if not isinstance(item, dict):
        raise api.APIError("unexpected result shape", provider="opentdb")
    correct = _decode(item.get("correct_answer"))
    options = [_decode(answer) for answer in item.get("incorrect_answers") or []]
    if not correct or not options:
        raise api.APIError("incomplete question", provider="opentdb")

    return {
        "category": _decode(item.get("category")),
        "difficulty": _decode(item.get("difficulty")),
        "question": _decode(item.get("question")),
        "correct": correct,
        "options": _shuffled(options + [correct]),
        "source": "Open Trivia DB",
        "note": None,
    }


async def _trivia_api(category, difficulty):
    params = {"limit": 1}
    note = None
    slug = FALLBACK_CATEGORIES.get(category or "")
    if slug:
        params["categories"] = slug
    elif category:
        note = f"{category} is not a category on the fallback"
    if difficulty:
        params["difficulty"] = difficulty

    data = await api.fetch_json(
        FALLBACK_URL, params=params, provider="the-trivia-api",
        timeout=12, retries=0,
    )
    if not isinstance(data, list) or not data:
        raise api.APIError("empty or unexpected payload",
                           provider="the-trivia-api")
    item = data[0]
    if not isinstance(item, dict):
        raise api.APIError("unexpected result shape",
                           provider="the-trivia-api")

    correct = str(item.get("correctAnswer") or "").strip()
    incorrect = [str(answer) for answer in item.get("incorrectAnswers") or []]
    question = str(item.get("question") or "").strip()
    if not correct or not incorrect or not question:
        raise api.APIError("incomplete question", provider="the-trivia-api")

    return {
        "category": str(item.get("category") or "Trivia"),
        "difficulty": str(item.get("difficulty") or difficulty or "medium"),
        "question": question,
        "correct": correct,
        "options": _shuffled(incorrect + [correct]),
        "source": "The Trivia API",
        "note": note,
    }


async def fetch_question(category=None, difficulty=None):
    """Return a normalised question, OpenTDB first and the Trivia API second."""
    global _last_call
    wait = MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        raise api.RateLimited(
            f"local 5s gate, wait {int(wait) + 1}s", provider="opentdb",
            retry_after=int(wait) + 1,
        )
    _last_call = time.monotonic()

    first_error = None
    try:
        return await _opentdb(category, difficulty)
    except (api.APIError, api.RateLimited) as exc:
        first_error = exc
        log.info("trivia: OpenTDB failed (%s), trying fallback", exc.describe())
    except Exception as exc:  # noqa: BLE001 - a bad payload is not fatal
        first_error = api.APIError(type(exc).__name__, provider="opentdb")
        log.info("trivia: OpenTDB crashed (%s)", type(exc).__name__)

    try:
        return await _trivia_api(category, difficulty)
    except (api.APIError, api.RateLimited) as exc:
        raise api.APIError(
            f"OpenTDB: {first_error.describe()}; Trivia API: {exc.describe()}",
            provider="trivia",
        ) from None
    except Exception as exc:  # noqa: BLE001
        raise api.APIError(
            f"OpenTDB: {first_error.describe()}; Trivia API: "
            f"{type(exc).__name__}",
            provider="trivia",
        ) from None


#------------------------------
#Parsing
#------------------------------

def parse_filters(raw):
    """Turn 'science hard' into ('science', 'hard'); raise ValueError."""
    category = difficulty = None
    for token in (raw or "").lower().split():
        if token in CATEGORIES and category is None:
            category = token
        elif token in DIFFICULTIES and difficulty is None:
            difficulty = token
        else:
            raise ValueError(
                f"unknown filter {token!r}. Categories: "
                + ", ".join(sorted(set(CATEGORIES)))
                + "; difficulty: " + ", ".join(DIFFICULTIES)
            )
    return category, difficulty


#------------------------------
#Rendering
#------------------------------

def render(question, revealed=False):
    letters = "ABCD"
    lines = [
        f"🎲 <b>Trivia</b> · {brand.esc(question['category'])} · "
        f"<i>{brand.esc(question['difficulty'])}</i>",
        "",
        brand.esc(question["question"]),
        "",
    ]
    for index, option in enumerate(question["options"][:4]):
        marker = (
            "✅"
            if revealed and option == question["correct"]
            else f"<b>{letters[index]}</b>"
        )
        lines.append(f"{marker}) {brand.esc(option)}")
    lines.append("")
    if revealed:
        lines.append(f"<b>Answer</b> · {brand.esc(question['correct'])}")
    else:
        lines.append(f"<i>Answer in {REVEAL_DELAY}s…</i>")
    footer = f"<i>source: {brand.esc(question['source'])}"
    if question.get("note"):
        footer += f" · {brand.esc(question['note'])}"
    lines.append(footer + "</i>")
    return "\n".join(lines)


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!trivia(?:\s+([\s\S]+))?$"))
    async def trivia_cmd(event):
        raw = (event.pattern_match.group(1) or "").strip()
        try:
            category, difficulty = parse_filters(raw)
        except ValueError as exc:
            await say(
                event,
                f"❌ <b>Unknown filter.</b> {brand.esc(exc)}",
                name="trivia",
                parse_mode="html",
            )
            return

        try:
            question = await fetch_question(category, difficulty)
        except api.RateLimited as exc:
            wait = exc.retry_after or 6
            await say(
                event,
                f"⏳ <b>Trivia is cooling down</b> — try again in "
                f"<code>{wait}s</code>.",
                name="trivia",
                parse_mode="html",
            )
            return
        except api.APIError as exc:
            await say(
                event,
                f"❌ <b>Could not fetch a question.</b> "
                f"{brand.esc(exc.describe())}. Try again shortly.",
                name="trivia",
                parse_mode="html",
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("trivia: unexpected failure")
            await say(
                event,
                f"❌ <b>{brand.esc(type(exc).__name__)}</b> · {brand.esc(exc)}",
                name="trivia",
                parse_mode="html",
            )
            return

        await say(event, render(question), name="trivia", parse_mode="html")
        await asyncio.sleep(REVEAL_DELAY)
        try:
            await event.edit(
                brand.sign(render(question, revealed=True), "trivia"),
                parse_mode="html",
            )
        except Exception as exc:  # noqa: BLE001 - message may be gone
            log.info("trivia: could not reveal answer (%s)", type(exc).__name__)
