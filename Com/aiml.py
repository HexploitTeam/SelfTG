"""`!aiml` -- local text generation from an owner-supplied corpus.

The hard rule
-------------
This module never reads a Telegram message. The model is trained from
``data/markov_corpus.txt`` only: a file that ships with the repo (public-domain
prose) and that the owner can replace with any text they have the right to use.
Earlier versions built a per-chat model from ``client.iter_messages``; that was
removed because Telegram's terms forbid using platform data to train a model,
and a self-bot that scrapes the chats it can see is exactly that.

Keeping a corpus out of the chat also removes a privacy problem: the old
``ML/models/markov_<chat>.json`` files contained fragments of real messages.
They are no longer read, no longer written, and the directory is ignored.

Cost
----
The corpus is ~180 KB. A bigram table over it is a few megabytes, built once per
process on first use and rebuilt only when the file changes. Generation is a
walk over that table: no neural model, no inference server, no CPU spike.
"""
import logging
import os
import random
import re

from telethon import events

from Com.core import brand
from Com.core.reply import say
from ML.smart_markov import SmartMarkov

__HELP__ = (
    "!aiml generate [seed] → A sentence from the local corpus model\n"
    "!aiml train → Rebuild the model from data/markov_corpus.txt\n"
    "!aiml status → Corpus path, words, transitions\n"
    "!aiml reset → Drop the cached model; the next generate rebuilds it\n"
    "The corpus is a local file. Telegram messages are never used for training."
)
__CATEGORY__ = "AI"

log = logging.getLogger("selftg.aiml")

CORPUS_FILE = os.path.join("data", "markov_corpus.txt")
ORDER = 2
MAX_WORDS = 30
MAX_CHARS = 320
MAX_SEED = 60
MIN_WORDS = 300

_model = None
_model_mtime = None


class CorpusError(Exception):
    """The corpus is missing, unreadable or too small to generate from."""


#------------------------------
#Corpus loading
#------------------------------


def _sentences(text):
    """Split prose into sentence-ish units so every unit has a start state."""
    parts = re.split(r"(?<=[.!?])\s+|\n{2,}", text)
    return [part.strip() for part in parts if len(part.split()) >= 3]


def _load_model():
    """Return the cached model, rebuilding it when the corpus changes."""
    global _model, _model_mtime

    try:
        stat = os.stat(CORPUS_FILE)
    except OSError:
        raise CorpusError(f"corpus not found at {CORPUS_FILE}") from None

    if _model is not None and _model_mtime == stat.st_mtime:
        return _model

    try:
        with open(CORPUS_FILE, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError as exc:
        raise CorpusError(f"corpus unreadable ({type(exc).__name__})") from None

    words = text.split()
    if len(words) < MIN_WORDS:
        raise CorpusError(
            f"corpus has {len(words)} words; at least {MIN_WORDS} are needed"
        )

    model = SmartMarkov(order=ORDER)
    model.train(_sentences(text))
    if not model.transitions:
        raise CorpusError("corpus produced no transitions")

    _model = model
    _model_mtime = stat.st_mtime
    log.info("aiml: built corpus model (%s words)", len(words))
    return model


def _polish(text):
    """Trim a raw walk into one presentable sentence."""
    words = (text or "").split()
    if not words:
        return ""

    # Stop at the first sentence end once there is enough to read
    kept = []
    for word in words:
        kept.append(word)
        if len(kept) >= 6 and word.endswith((".", "!", "?")):
            break

    line = " ".join(kept).strip()
    line = line.lstrip("\"'([-–— ")
    if not line:
        return ""
    line = line[0].upper() + line[1:]
    if line[-1] not in ".!?":
        line = line.rstrip(",;:-–— ") + "."
    if len(line) > MAX_CHARS:
        line = line[:MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:-–— ") + "…"
    return line


#------------------------------
#Commands
#------------------------------


def setup(client, my_id):

    async def _reply(event, body):
        if not await say(event, body, name="aiml", parse_mode="html"):
            log.info("aiml: could not deliver an answer")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml$"))
    async def aiml_help(event):
        await _reply(event, "🧠 <b>Local text</b>\n" + brand.esc(__HELP__))

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml train(?:\s+(\d+))?$"))
    async def aiml_train(event):
        global _model, _model_mtime
        _model = None
        _model_mtime = None
        try:
            model = _load_model()
        except CorpusError as exc:
            await _reply(
                event,
                "❌ <b>Cannot train from the corpus.</b>\n"
                f"{brand.esc(exc)}\n\n"
                f"Put a text file at <code>{brand.esc(CORPUS_FILE)}</code> "
                "(at least a few thousand words) and try again.",
            )
            return

        stats = model.get_stats()
        body = (
            "✅ <b>Model rebuilt</b>\n"
            f"Corpus · <code>{brand.esc(CORPUS_FILE)}</code>\n"
            f"Words · <code>{stats['total_words']}</code>\n"
            f"States · <code>{stats['unique_states']}</code>\n"
            f"Transitions · <code>{stats['total_transitions']}</code>"
        )
        if event.pattern_match.group(1):
            body += (
                "\n\n<i>The message count in the old command is ignored: "
                "training reads the corpus file, never chat history.</i>"
            )
        await _reply(event, body)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml generate(?:\s+([\s\S]+))?$"))
    async def aiml_generate(event):
        seed = re.sub(r"\s+", " ", event.pattern_match.group(1) or "").strip()
        if len(seed) > MAX_SEED:
            seed = seed[:MAX_SEED]
        try:
            model = _load_model()
        except CorpusError as exc:
            await _reply(
                event,
                "❌ <b>No usable corpus.</b>\n"
                f"{brand.esc(exc)}\n\n"
                f"Add text at <code>{brand.esc(CORPUS_FILE)}</code> "
                "or run <code>!aiml train</code> for the details.",
            )
            return

        # A bigram walk can dead-end after two words; keep the longest of a few
        # tries instead of showing the shortest one as if it were the answer
        candidates = []
        try:
            for attempt in range(3):
                raw = model.generate(seed if attempt == 0 and seed else None,
                                     max_words=MAX_WORDS)
                line = _polish(raw)
                if line:
                    candidates.append(line)
                if len(line.split()) >= 8:
                    break
        except Exception as exc:  # noqa: BLE001 - a bad walk must not kill the client
            log.exception("aiml: generation failed")
            await _reply(event, f"❌ <b>Generation failed</b> · <code>{brand.esc(type(exc).__name__)}</code>")
            return

        line = max(candidates, key=lambda text: len(text.split()), default="")
        if not line:
            await _reply(
                event,
                "❌ <b>Nothing came out.</b> The corpus may be too thin for that "
                f"seed. Try <code>!aiml generate</code> without one.",
            )
            return

        body = f"🧠 <b>Local text</b>\n\n<blockquote>{brand.esc(line)}</blockquote>"
        if seed:
            body += f"\n\nSeed · <code>{brand.esc(seed)}</code>"
        await _reply(event, body)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml status$"))
    async def aiml_status(event):
        try:
            model = _load_model()
        except CorpusError as exc:
            await _reply(
                event,
                "📊 <b>Corpus model</b>\n"
                f"State · <code>unavailable</code>\n"
                f"Why · {brand.esc(exc)}\n"
                f"Path · <code>{brand.esc(CORPUS_FILE)}</code>",
            )
            return
        stats = model.get_stats()
        await _reply(
            event,
            "📊 <b>Corpus model</b>\n"
            f"Path · <code>{brand.esc(CORPUS_FILE)}</code>\n"
            f"Order · <code>{ORDER}</code>\n"
            f"Words · <code>{stats['total_words']}</code>\n"
            f"Unique words · <code>{stats['unique_words']}</code>\n"
            f"States · <code>{stats['unique_states']}</code>\n"
            f"Transitions · <code>{stats['total_transitions']}</code>\n\n"
            "<i>Source: the local file only. Telegram messages are never read.</i>",
        )

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml reset$"))
    async def aiml_reset(event):
        global _model, _model_mtime
        _model = None
        _model_mtime = None
        await _reply(
            event,
            "✅ <b>Model cache cleared.</b> The next "
            "<code>!aiml generate</code> rebuilds it from "
            f"<code>{brand.esc(CORPUS_FILE)}</code>.",
        )
