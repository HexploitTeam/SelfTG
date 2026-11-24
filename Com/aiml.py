"""`!aiml` -- local text generation from an owner-supplied corpus.

The hard rule
-------------
This module never reads a Telegram message. The model is trained from the text
files in ``data/corpus/`` only: a folder that ships with the repo
(public-domain prose) and that the owner can add to with any text they have the
right to use. Each file is one source; ``!aiml train`` reads all of them
together.
Earlier versions built a per-chat model from ``client.iter_messages``; that was
removed because Telegram's terms forbid using platform data to train a model,
and a self-bot that scrapes the chats it can see is exactly that.

Keeping a corpus out of the chat also removes a privacy problem: the old
``ML/models/markov_<chat>.json`` files contained fragments of real messages.
They are no longer read, no longer written, and the directory is ignored.

What the command does now
-------------------------
``gen`` writes a sentence (or continues one you start), ``say`` continues from
your own words, ``para`` writes a short paragraph, ``next`` shows what the
corpus does after a phrase, ``corpus`` and ``status`` report what was learned,
and ``config``/``set`` tune the sampler. ``train`` and ``reset`` manage the
in-memory model. The sampler itself lives in ``ML/smart_markov.py``: counts for
every order from 1 to ``order``, blended at sampling time, with count weighting
and a temperature.

Cost
----
The shipped sources are ~180 KB. Counts for three orders over them cost about
15 MB of Python objects, built once per process on first use (~0.2 s) and
rebuilt only when a source or the chosen order changes. The cache check stats
the files and never rereads them, so cached commands cost no parsing at all.
Adding text grows the model roughly in proportion; the number of sources is
capped, so one command cannot walk a directory holding thousands of files.
Generation is a walk over those counters: no neural model, no inference server,
no CPU spike.
"""
import logging
import os
import random
import re
import time

from telethon import events

from Com.core import brand
from Com.core.reply import say
from Com.core.storage import load_json, save_json
from ML.smart_markov import MAX_ORDER, SmartMarkov

__HELP__ = (
    "!aiml gen [words] → A sentence from the local corpus model\n"
    "!aiml say <prompt> → Continue from your own words\n"
    "!aiml para [sentences] → A short paragraph\n"
    "!aiml next <text> → The likeliest continuations, with odds\n"
    "!aiml corpus → Every source, with its size and word count\n"
    "!aiml status → Model size, build time and settings\n"
    "!aiml config → Show settings; !aiml set <key> <value> changes them\n"
    "!aiml train → Retrain on every file in data/corpus/; !aiml reset drops the cache\n"
    "Sources are local files in data/corpus/. Telegram messages are never used."
)
__CATEGORY__ = "AI"

log = logging.getLogger("selftg.aiml")

CORPUS_DIR = os.path.join("data", "corpus")
SETTINGS_FILE = "mode/aiml.json"

MAX_SEED = 160
MAX_SOURCES = 12
MAX_CHARS = 1000
MIN_WORDS = 300

DEFAULTS = {"order": 3, "temp": 1.0, "length": 30, "sentences": 3}
LIMITS = {
    "order": (1, MAX_ORDER),
    "temp": (0.2, 2.0),
    "length": (8, 120),
    "sentences": (1, 6),
}
NOTES = {
    "order": "Context length. Higher follows the corpus more closely.",
    "temp": "Below 1 is safer, above 1 is stranger.",
    "length": "Words per sentence.",
    "sentences": "Sentences per !aiml para.",
}

_RNG = random.Random()

_model = None
_model_key = None
_build_seconds = 0.0
_build_rss = None
_builds = 0
_source_count = 0


class CorpusError(Exception):
    """The corpus is missing, unreadable or too small to generate from."""


class SettingsError(Exception):
    """A setting could not be validated or written."""


#------------------------------
#Settings
#------------------------------

def _settings():
    """Read settings, falling back to the default for anything invalid."""
    raw = load_json(SETTINGS_FILE, {})
    settings = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return settings

    for key, (low, high) in LIMITS.items():
        value = raw.get(key)
        if value is None:
            continue
        try:
            value = float(value) if key == "temp" else int(value)
        except (TypeError, ValueError):
            continue
        if low <= value <= high:
            settings[key] = value
    return settings


def _save_settings(settings):
    try:
        save_json(SETTINGS_FILE, settings)
    except OSError as exc:
        raise SettingsError(
            f"could not write {SETTINGS_FILE} ({type(exc).__name__})"
        ) from None


#------------------------------
#Corpus loading
#------------------------------

def _sentences(text):
    """Split prose into sentence-ish units so every unit has a start state."""
    parts = re.split(r"(?<=[.!?])\s+|\n{2,}", text)
    return [part.strip() for part in parts if len(part.split()) >= 3]


def _rss_kb():
    """Peak resident set in KB, or None where the platform cannot report it."""
    try:
        import resource
    except ImportError:
        return None
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def _sources():
    """Every text file the model trains on, or CorpusError saying why not."""
    try:
        names = sorted(os.listdir(CORPUS_DIR))
    except OSError:
        names = []

    paths = [
        os.path.join(CORPUS_DIR, name)
        for name in names
        if name.lower().endswith(".txt")
        and not name.startswith(".")
        and os.path.isfile(os.path.join(CORPUS_DIR, name))
    ]

    if not paths:
        raise CorpusError(f"no .txt files in {CORPUS_DIR}/")
    if len(paths) > MAX_SOURCES:
        raise CorpusError(
            f"{len(paths)} sources in {CORPUS_DIR}/; at most {MAX_SOURCES} "
            "are trained. Remove some or merge them into one file."
        )
    return paths


def _manifest():
    """Name, size and mtime of every source: enough to key the model cache."""
    documents = []
    for path in _sources():
        try:
            stat = os.stat(path)
        except OSError as exc:
            raise CorpusError(
                f"{os.path.basename(path)} unreadable ({type(exc).__name__})"
            ) from None
        documents.append(
            {
                "path": path,
                "name": os.path.basename(path),
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return documents


def _documents():
    """Read every source into words and sentence units, keeping its stats."""
    documents = _manifest()
    total_words = 0

    for document in documents:
        try:
            with open(document["path"], "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError as exc:
            raise CorpusError(
                f"{document['name']} unreadable ({type(exc).__name__})"
            ) from None

        document["words"] = len(text.split())
        document["sentences"] = _sentences(text)
        total_words += document["words"]

    if total_words < MIN_WORDS:
        raise CorpusError(
            f"{len(documents)} source(s) hold {total_words} words; "
            f"at least {MIN_WORDS} are needed"
        )
    return documents


def _cache_key(order, documents):
    """Every source's identity: adding, removing, editing or renaming one
    file rebuilds the model without a manual !aiml train."""
    return (
        order,
        tuple((doc["name"], doc["mtime_ns"], doc["bytes"]) for doc in documents),
    )


def _files_label(count):
    return f"{count} file" if count == 1 else f"{count} files"


def _totals(documents):
    return {
        "files": len(documents),
        "bytes": sum(document["bytes"] for document in documents),
        "words": sum(document["words"] for document in documents),
    }


def _source_rows(documents, limit=6):
    """One line per source for a card, with a count when the list is cut."""
    rows = [
        f"{brand.esc(doc['name'])} · <code>{doc['words']:,}</code> words"
        f" · <code>{len(doc['sentences']):,}</code> sentences"
        for doc in documents[:limit]
    ]
    if len(documents) > limit:
        rows.append(f"<i>+{len(documents) - limit} more</i>")
    return "\n".join(rows)


def _load_model(order=None, force=False, documents=None):
    """Return the cached model, rebuilding it when any source or the order changes.

    ``documents`` is an already-read list from :func:`_documents`; without it
    the cache check only stats the files and the text is read on a real rebuild.
    """
    global _model, _model_key, _build_seconds, _build_rss, _builds, _source_count

    if order is None:
        order = _settings()["order"]

    key = _cache_key(order, documents if documents is not None else _manifest())
    if not force and _model is not None and _model_key == key:
        return _model

    if documents is None:
        documents = _documents()

    before = _rss_kb()
    started = time.perf_counter()
    model = SmartMarkov(order=order)
    for document in documents:
        model.train(document["sentences"])
    elapsed = time.perf_counter() - started
    after = _rss_kb()
    growth = None if before is None or after is None else after - before

    if not model.total_words:
        raise CorpusError("the sources produced no usable sentences")

    _model = model
    _model_key = key
    _build_seconds = elapsed
    _source_count = len(documents)
    if growth and growth > 0:
        _build_rss = growth
    _builds += 1
    log.info(
        "aiml: built order-%s model from %s source(s), %s words, in %.3fs",
        order, len(documents), _totals(documents)["words"], elapsed,
    )
    return model


#------------------------------
#Presentation
#------------------------------

def _tidy(line, capitalize=True):
    """Trim a raw walk into one presentable sentence."""
    line = " ".join((line or "").split())
    if not line:
        return ""

    if capitalize:
        line = line[0].upper() + line[1:]
    line = line.strip("\"'( [-–—")
    if not line:
        return ""

    if line[-1] not in ".!?…":
        line = line.rstrip(",;:-–— ") + "."
    if len(line) > MAX_CHARS:
        line = line[:MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:-–— ") + "…"
    return line


def _sentence(model, max_words, temperature):
    """One acceptable sentence; keep the longest walk if none is long enough."""
    best = ""
    for _attempt in range(4):
        line = _tidy(
            model.generate(max_words=max_words, temperature=temperature, rng=_RNG)
        )
        if len(line.split()) >= 5:
            return line
        best = line or best
    return best


def _settings_line(settings, length=None):
    return (
        f"order <code>{settings['order']}</code> · "
        f"temp <code>{settings['temp']:g}</code> · "
        f"<code>{settings['length'] if length is None else length}</code> words"
    )


def _check_range(value, key):
    low, high = LIMITS[key]
    if not low <= value <= high:
        raise SettingsError(f"{key} must be between {low} and {high}")
    return value


#------------------------------
#Commands
#------------------------------

def setup(client, my_id):

    async def _reply(event, body):
        if not await say(event, body, name="aiml", parse_mode="html"):
            log.info("aiml: could not deliver an answer")

    def _help_card(settings):
        return (
            "🧠 <b>Local text</b>\n"
            f"{brand.esc(__HELP__)}\n\n"
            f"Now · {_settings_line(settings)}"
        )

    def _corpus_failure(event, exc):
        return _reply(
            event,
            "❌ <b>No usable corpus.</b>\n"
            f"{brand.esc(exc)}\n\n"
            f"Put UTF-8 <code>.txt</code> files in "
            f"<code>{brand.esc(CORPUS_DIR)}/</code> "
            f"(at least {MIN_WORDS} words in total), then "
            "<code>!aiml train</code>.",
        )

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml(?:\s+(?:help|\?))?$"))
    async def aiml_help(event):
        await _reply(event, _help_card(_settings()))

    @client.on(events.NewMessage(
        from_users=my_id, pattern=r"^!aiml (gen|generate|say)(?:\s+([\s\S]+))?$"
    ))
    async def aiml_generate(event):
        settings = _settings()
        verb = event.pattern_match.group(1)
        argument = " ".join((event.pattern_match.group(2) or "").split())

        if verb == "say" and not argument:
            await _reply(
                event,
                "❌ <b>Give me a starting point.</b>\n"
                "Usage · <code>!aiml say the time traveller</code>",
            )
            return

        # `gen 50` sets the length; `say 50` still means "continue from 50"
        length = settings["length"]
        seed = argument
        if verb != "say" and argument.isdigit():
            length = int(argument)
            seed = ""
            low, high = LIMITS["length"]
            if not low <= length <= high:
                await _reply(
                    event,
                    "❌ <b>Length out of range.</b>\n"
                    f"Use <code>{low}–{high}</code> words, "
                    "e.g. <code>!aiml gen 50</code>.",
                )
                return
        if len(seed) > MAX_SEED:
            seed = seed[:MAX_SEED]

        try:
            model = _load_model(settings["order"])
        except CorpusError as exc:
            await _corpus_failure(event, exc)
            return

        try:
            if seed:
                line = _tidy(
                    model.generate(
                        seed=seed,
                        max_words=max(length, len(seed.split()) + 8),
                        temperature=settings["temp"],
                        rng=_RNG,
                    ),
                    capitalize=False,
                )
            else:
                line = _sentence(model, length, settings["temp"])
        except Exception as exc:  # noqa: BLE001 - a bad walk must not kill the client
            log.exception("aiml: generation failed")
            await _reply(
                event,
                f"❌ <b>Generation failed</b> · <code>{brand.esc(type(exc).__name__)}</code>",
            )
            return

        if seed and (not line or len(line.split()) - len(seed.split()) < 2):
            await _reply(
                event,
                "❌ <b>That prompt goes nowhere.</b>\n"
                f"The corpus never continues <code>{brand.esc(seed[:60])}</code>.\n"
                "Try the last word or two of a sentence instead.",
            )
            return
        if not line:
            await _reply(
                event,
                "❌ <b>Nothing came out.</b> The corpus is too thin for that "
                "prompt. Try <code>!aiml gen</code> without one.",
            )
            return

        await _reply(
            event,
            f"🧠 <b>{'Continued' if seed else 'Local text'}</b>\n\n"
            f"<blockquote>{brand.esc(line)}</blockquote>\n\n"
            f"<i>{len(line.split())} words · {_settings_line(settings, length)}</i>",
        )

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml para(?:\s+(\d+))?$"))
    async def aiml_para(event):
        settings = _settings()
        count = settings["sentences"]
        if event.pattern_match.group(1):
            count = int(event.pattern_match.group(1))
            low, high = LIMITS["sentences"]
            if not low <= count <= high:
                await _reply(
                    event,
                    "❌ <b>Too many sentences.</b>\n"
                    f"Use <code>{low}–{high}</code>, e.g. <code>!aiml para 3</code>.",
                )
                return

        try:
            model = _load_model(settings["order"])
        except CorpusError as exc:
            await _corpus_failure(event, exc)
            return

        try:
            text = " ".join(
                model.paragraph(
                    sentences=count,
                    max_words=settings["length"],
                    temperature=settings["temp"],
                    rng=_RNG,
                ).split()
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("aiml: paragraph failed")
            await _reply(
                event,
                f"❌ <b>Generation failed</b> · <code>{brand.esc(type(exc).__name__)}</code>",
            )
            return

        if not text:
            await _reply(
                event,
                "❌ <b>Nothing came out.</b> The corpus may be too thin to walk.",
            )
            return

        await _reply(
            event,
            "🧠 <b>Local paragraph</b>\n\n"
            f"<blockquote>{brand.esc(text)}</blockquote>\n\n"
            f"<i>{count} sentences · {_settings_line(settings)}</i>",
        )

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml next(?:\s+([\s\S]+))?$"))
    async def aiml_next(event):
        text = " ".join((event.pattern_match.group(1) or "").split())
        if not text:
            await _reply(
                event,
                "❌ <b>Give me a phrase.</b>\n"
                "Usage · <code>!aiml next the time</code>",
            )
            return

        try:
            model = _load_model()
        except CorpusError as exc:
            await _corpus_failure(event, exc)
            return

        ranked = model.next_words(text[:MAX_SEED], limit=6)
        if not ranked:
            await _reply(
                event,
                f"❌ <b>No continuation for that.</b>\n"
                f"The corpus never continues <code>{brand.esc(text[:80])}</code>. "
                "Try the last word or two of a sentence instead.",
            )
            return

        lines = "\n".join(
            f"{brand.esc(word)} · {probability * 100:.1f}%"
            for word, probability in ranked
        )
        await _reply(
            event,
            f"🔮 <b>After</b> <code>{brand.esc(text[:80])}</code>\n"
            f"<blockquote>{lines}</blockquote>\n\n"
            "<i>Blended odds across every order the corpus knows.</i>",
        )

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml corpus$"))
    async def aiml_corpus(event):
        try:
            documents = _documents()
            model = _load_model(documents=documents)
        except CorpusError as exc:
            await _corpus_failure(event, exc)
            return

        stats = model.get_stats()
        totals = _totals(documents)
        top = " · ".join(
            f"{brand.esc(word)} {count:,}" for word, count in stats["top_words"]
        )
        provenance = ""
        if any(doc["name"] == "the-time-machine.txt" for doc in documents):
            provenance = (
                "\n<i>The Time Machine (1895), H. G. Wells — public domain, "
                "Project Gutenberg #35 via the GITenberg mirror.</i>"
            )
        await _reply(
            event,
            "📚 <b>Corpus</b>\n"
            f"Folder · <code>{brand.esc(CORPUS_DIR)}/</code>\n"
            f"Sources · <code>{_files_label(totals['files'])}</code> · "
            f"<code>{totals['bytes'] / 1024:.1f} KB</code>\n"
            f"<blockquote>{_source_rows(documents)}</blockquote>\n"
            f"Words · <code>{stats['total_words']:,}</code>\n"
            f"Sentences · <code>{stats['sentences']:,}</code>\n"
            f"Unique words · <code>{stats['unique_words']:,}</code>\n"
            f"Average sentence · <code>{stats['avg_sentence_words']:.1f} words</code>\n"
            f"Commonest · <code>{top}</code>\n"
            f"{provenance}\n"
            "<i>Add text you have the right to use as another .txt file; "
            "notes go in data/README.md. Telegram messages are never read.</i>",
        )

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml status$"))
    async def aiml_status(event):
        settings = _settings()
        try:
            model = _load_model(settings["order"])
        except CorpusError as exc:
            await _reply(
                event,
                "📊 <b>Corpus model</b>\n"
                "State · <code>unavailable</code>\n"
                f"Why · {brand.esc(exc)}\n"
                f"Folder · <code>{brand.esc(CORPUS_DIR)}/</code>",
            )
            return

        stats = model.get_stats()
        orders = stats["orders"]
        spread = (
            f"{orders[0]}–{orders[-1]}" if len(orders) > 1 else str(orders[0])
        ) if orders else "none"
        cache = "warm" if _model is model else "cold"
        memory = f"<code>+{_build_rss / 1024:.1f} MB</code>" if _build_rss else "n/a"
        await _reply(
            event,
            "📊 <b>Corpus model</b>\n"
            f"Folder · <code>{brand.esc(CORPUS_DIR)}/</code>\n"
            f"Sources · <code>{_files_label(_source_count)}</code>\n"
            f"Orders · <code>{spread}</code>\n"
            f"States · <code>{stats['unique_states']:,}</code>\n"
            f"Transitions · <code>{stats['total_transitions']:,}</code>\n"
            f"Words · <code>{stats['total_words']:,}</code>\n"
            f"Built · <code>{_build_seconds:.3f}s</code> · cache <code>{cache}</code>\n"
            f"Memory · {memory} peak growth\n"
            f"Rebuilds this run · <code>{_builds}</code>\n"
            f"Settings · {_settings_line(settings)}\n\n"
            "<i>Rebuilt only when a source or the order changes.</i>",
        )

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml train$"))
    async def aiml_train(event):
        settings = _settings()
        try:
            documents = _documents()
            model = _load_model(settings["order"], force=True, documents=documents)
        except CorpusError as exc:
            await _reply(
                event,
                "❌ <b>Cannot train from the corpus.</b>\n"
                f"{brand.esc(exc)}\n\n"
                f"Put UTF-8 <code>.txt</code> files in "
                f"<code>{brand.esc(CORPUS_DIR)}/</code> "
                f"(at least {MIN_WORDS} words in total) and try again.",
            )
            return

        stats = model.get_stats()
        totals = _totals(documents)
        per_order = " / ".join(f"{count:,}" for count in stats["states_by_order"])
        memory = f"\nMemory · <code>+{_build_rss / 1024:.1f} MB</code> peak" if _build_rss else ""
        await _reply(
            event,
            "✅ <b>Model trained</b>\n"
            f"Sources · <code>{_files_label(totals['files'])}</code> · "
            f"<code>{totals['bytes'] / 1024:.1f} KB</code>\n"
            f"<blockquote>{_source_rows(documents)}</blockquote>\n"
            f"Words · <code>{stats['total_words']:,}</code>\n"
            f"Sentences · <code>{stats['sentences']:,}</code>\n"
            f"States · <code>{stats['unique_states']:,}</code> "
            f"<i>(by order {per_order})</i>\n"
            f"Transitions · <code>{stats['total_transitions']:,}</code>\n"
            f"Build · <code>{_build_seconds:.3f}s</code>{memory}\n\n"
            f"<i>Settings · {_settings_line(settings)}</i>\n"
            "<i>Read from data/corpus/ only. Telegram messages are never used.</i>",
        )

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml config$"))
    async def aiml_config(event):
        settings = _settings()
        rows = []
        for key, (low, high) in LIMITS.items():
            value = settings[key]
            shown = f"{value:g}" if key == "temp" else str(value)
            rows.append(f"{key.capitalize()} · <code>{shown}</code> "
                        f"<i>({low}–{high})</i>")
        await _reply(
            event,
            "⚙️ <b>Local text settings</b>\n" + "\n".join(rows) + "\n\n"
            f"Stored · <code>{brand.esc(SETTINGS_FILE)}</code>\n"
            "Change · <code>!aiml set temp 0.7</code>",
        )

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml set(?:\s+(\w+))?(?:\s+(\S+))?$"))
    async def aiml_set(event):
        key = (event.pattern_match.group(1) or "").lower()
        value = event.pattern_match.group(2)

        if not key or key not in LIMITS:
            await _reply(
                event,
                "❌ <b>Unknown setting.</b>\n"
                f"Keys · <code>{', '.join(LIMITS)}</code>\n"
                "Usage · <code>!aiml set order 2</code>",
            )
            return
        if value is None:
            await _reply(
                event,
                f"❌ <b>Missing value.</b>\n"
                f"Usage · <code>!aiml set {key} {LIMITS[key][0]}</code>",
            )
            return

        try:
            parsed = float(value) if key == "temp" else int(value)
        except ValueError:
            await _reply(
                event,
                f"❌ <b>Not a number.</b>\n"
                f"<code>{brand.esc(key)}</code> takes a number between "
                f"<code>{LIMITS[key][0]}</code> and <code>{LIMITS[key][1]}</code>.",
            )
            return

        try:
            _check_range(parsed, key)
        except SettingsError as exc:
            await _reply(event, f"❌ <b>Out of range.</b>\n{brand.esc(exc)}.")
            return

        settings = _settings()
        settings[key] = parsed
        try:
            _save_settings(settings)
        except SettingsError as exc:
            await _reply(
                event,
                "❌ <b>Could not save the setting.</b>\n"
                f"{brand.esc(exc)}\n"
                "Nothing was changed.",
            )
            return

        note = NOTES.get(key, "")
        extra = ""
        if key == "order":
            extra = "\n<i>The model rebuilds on the next command.</i>"
        await _reply(
            event,
            "✅ <b>Setting saved</b>\n"
            f"{key.capitalize()} · <code>{parsed:g}</code>\n"
            f"<i>{brand.esc(note)}</i>{extra}\n\n"
            f"Now · {_settings_line(settings)}",
        )

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml reset$"))
    async def aiml_reset(event):
        global _model, _model_key
        _model = None
        _model_key = None
        await _reply(
            event,
            "✅ <b>Model cache cleared.</b>\n"
            "The next command rebuilds it from "
            f"<code>{brand.esc(CORPUS_DIR)}/</code>. Settings are kept.",
        )
