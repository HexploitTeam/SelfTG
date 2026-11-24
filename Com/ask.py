"""`!ask` -- the one command that calls a language model.

Why this one and not the others
-------------------------------
Every other fun command in this project is a table, a template or a string
transform, and those are better local: instant, free, impossible to rate limit.
`!ask` is the exception because the point is an answer to an arbitrary
question, which no table can give.

Providers
---------
Groq first, then Gemini, both on standing free tiers that do not require a card
(Groq's free plan is rate-limited per organisation; Google's free tier is
rate-limited per project). Keys live in Replit Secrets:

* ``GROQ_API_KEY`` -- https://console.groq.com/keys
* ``GEMINI_API_KEY`` -- https://aistudio.google.com/app/apikey

``GROQ_MODEL`` and ``ASK_GEMINI_MODEL`` override the model ids without touching
code. If no key is present the command says which secrets to add; nothing fails
at import, because one missing optional key must not take the self-bot down.

What is sent
------------
The question typed after the command, and a short system instruction. Never the
chat, never the replied message, never history: the provider sees one question
from the owner and nothing else. Gemini's free tier may use inputs to improve
its products (Groq's does not train on API inputs), which is another reason the
command does not forward anything but the typed text.

Spend control
-------------
A persisted bucket in ``mode/ask.json``: one question every ``COOLDOWN`` seconds
and at most ``DAILY_CAP`` a day, counted before the request so a double-tap
cannot spend twice. The file is small and written atomically; if it cannot be
written the command refuses instead of spending unmetered quota.
"""
import logging
import math
import os
import time
from datetime import date

from telethon import events

import Com.core.api as api
from Com.core import brand
from Com.core.reply import say
from Com.core.storage import load_json, save_json

__HELP__ = (
    "!ask <question> → Ask the free model; Groq first, Gemini as fallback\n"
    "Cooldown · 8s, 30 questions a day, persisted in mode/ask.json\n"
    "Only the typed question is sent. Chat history is never forwarded."
)
__CATEGORY__ = "AI"

log = logging.getLogger("selftg.ask")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

GROQ_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
GEMINI_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GROQ_MODEL = (os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b").strip()
GEMINI_MODEL = (os.getenv("ASK_GEMINI_MODEL") or "gemini-3.5-flash-lite").strip()

ASK_FILE = "mode/ask.json"
COOLDOWN = 8
DAILY_CAP = 30
MAX_QUESTION = 500
MAX_ANSWER = 1200

SYSTEM_PROMPT = (
    "You are the resident wit of a personal Telegram utility called Spooku Self. "
    "Answer the question directly and conversationally, in at most 700 characters. "
    "Plain text only: no markdown headings, no code fences, no URLs unless the "
    "question asks for one. Do not claim to remember earlier conversations or to "
    "have access to any chat."
)

if not (GROQ_KEY or GEMINI_KEY):
    log.warning("ask: no GROQ_API_KEY or GEMINI_API_KEY; !ask will explain what to set")


#------------------------------
#State
#------------------------------

class Cooldown(Exception):
    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__(f"cooldown {seconds}s")


class DailyCap(Exception):
    pass


class StoreError(Exception):
    pass


def _today():
    return date.today().isoformat()


def _state():
    data = load_json(ASK_FILE, {})
    return data if isinstance(data, dict) else {}


def _reserve():
    """Count this request before it is made; raise when it may not be made."""
    state = _state()
    if state.get("day") != _today():
        state = {"day": _today(), "used": 0, "last": 0}

    try:
        last = float(state.get("last") or 0)
        used = int(state.get("used") or 0)
    except (TypeError, ValueError):
        last, used = 0, 0

    remaining = COOLDOWN - (time.time() - last)
    if remaining > 0:
        raise Cooldown(max(1, math.ceil(remaining)))
    if used >= DAILY_CAP:
        raise DailyCap()

    state["day"] = _today()
    state["used"] = used + 1
    state["last"] = time.time()
    try:
        save_json(ASK_FILE, state)
    except Exception as exc:  # noqa: BLE001 - disk full, permissions, read-only repl
        log.warning("ask: could not persist the quota bucket (%s)", type(exc).__name__)
        raise StoreError() from None


#------------------------------
#Providers
#------------------------------

def _providers():
    chain = []
    if GROQ_KEY:
        chain.append(("groq", GROQ_MODEL))
    if GEMINI_KEY:
        chain.append(("gemini", GEMINI_MODEL))
    return chain


def _shape_error(provider, detail):
    return api.APIError(f"unexpected response ({detail})", provider=provider)


async def _ask_groq(question):
    data = await api.post_json(
        GROQ_URL,
        {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            "temperature": 0.8,
            "max_tokens": 300,
        },
        provider="groq",
        headers={"Authorization": f"Bearer {GROQ_KEY}"},
        timeout=30,
    )
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise _shape_error("groq", "no choices") from None
    return (text or "").strip()


async def _ask_gemini(question):
    data = await api.post_json(
        GEMINI_URL.format(model=GEMINI_MODEL),
        {
            "contents": [{"parts": [{"text": question}]}],
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "generationConfig": {"temperature": 0.8, "maxOutputTokens": 300},
        },
        provider="gemini",
        headers={"x-goog-api-key": GEMINI_KEY},
        timeout=30,
    )

    feedback = data.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        raise api.APIError(
            f"blocked by provider ({feedback['blockReason']})", provider="gemini"
        )

    candidates = data.get("candidates") or []
    if not candidates:
        raise _shape_error("gemini", "no candidates")
    candidate = candidates[0]
    if candidate.get("finishReason") in ("SAFETY", "RECITATION", "BLOCKLIST"):
        raise api.APIError(
            f"blocked by provider ({candidate['finishReason']})", provider="gemini"
        )
    parts = (candidate.get("content") or {}).get("parts") or []
    text = " ".join(part.get("text", "") for part in parts if part.get("text"))
    return text.strip()


async def _ask_chain(question):
    """Return (answer, provider label) or raise with every failure recorded."""
    failures = []
    for name, model in _providers():
        try:
            if name == "groq":
                answer = await _ask_groq(question)
            else:
                answer = await _ask_gemini(question)
        except api.RateLimited as exc:
            failures.append(f"{name}: rate limited")
            log.info("ask: %s rate limited (%s)", name, exc.describe())
            continue
        except api.APIError as exc:
            failures.append(exc.describe())
            log.info("ask: %s failed (%s)", name, exc.describe())
            continue
        except Exception as exc:  # noqa: BLE001 - one provider must not end the chain
            failures.append(f"{name}: {type(exc).__name__}")
            log.info("ask: %s crashed (%s)", name, type(exc).__name__)
            continue

        if answer:
            return answer, f"{name} · {model}"
        failures.append(f"{name}: empty answer")

    raise api.APIError("; ".join(failures) or "no provider configured")


#------------------------------
#Command
#------------------------------

def setup(client, my_id):

    async def _reply(event, body):
        if not await say(event, body, name="ask", parse_mode="html"):
            log.info("ask: could not deliver an answer")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!ask(?:\s+([\s\S]+))?$"))
    async def ask_cmd(event):
        question = " ".join((event.pattern_match.group(1) or "").split())
        if not question:
            await _reply(
                event,
                "💬 <b>Ask</b>\n"
                "Usage · <code>!ask why is the sky blue?</code>\n"
                "Only what you type is sent; replies and chat history are not.",
            )
            return
        if len(question) > MAX_QUESTION:
            question = question[:MAX_QUESTION].rstrip() + "…"

        if not _providers():
            await _reply(
                event,
                "❌ <b>!ask has no provider configured.</b>\n"
                "Add <code>GROQ_API_KEY</code> or <code>GEMINI_API_KEY</code> in "
                "Replit Secrets, then restart. Both are free tiers; no card is "
                "needed.",
            )
            return

        try:
            _reserve()
        except Cooldown as exc:
            await _reply(
                event,
                f"⏳ <b>Ask is cooling down</b> · try again in "
                f"<code>{exc.seconds}s</code>.",
            )
            return
        except DailyCap:
            await _reply(
                event,
                f"⏳ <b>Daily limit reached.</b>\n"
                f"<code>{DAILY_CAP}</code> questions today. The counter resets "
                "at midnight, local time.",
            )
            return
        except StoreError:
            await _reply(
                event,
                "❌ <b>Could not record the request.</b>\n"
                f"Check that <code>{brand.esc(ASK_FILE)}</code> is writable. "
                "Refusing to spend quota unmetered.",
            )
            return

        try:
            answer, label = await _ask_chain(question)
        except api.APIError as exc:
            await _reply(
                event,
                "❌ <b>No provider answered.</b>\n"
                f"<blockquote>{brand.esc(str(exc))[:700]}</blockquote>\n"
                "The quota bucket was still charged; try again after the cooldown.",
            )
            return

        if len(answer) > MAX_ANSWER:
            answer = answer[:MAX_ANSWER].rsplit(" ", 1)[0].rstrip() + "…"

        body = (
            "💬 <b>Ask</b>\n"
            f"<blockquote>{brand.esc(question)}</blockquote>\n\n"
            f"{brand.esc(answer)}\n\n"
            f"<i>{brand.esc(label)}</i>"
        )
        await _reply(event, body)
