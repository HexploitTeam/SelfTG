"""`!love` -- remember a name, then send one of twenty lines for it.

Two forms, one stored value
---------------------------
    !love <name>    save the lover's name
    !love           send one random line from ``LOVE_LINES``, with that name in it

The lines are source, not data: ``LOVE_LINES`` below is the whole text of the
feature. There is no API, no model and no per-chat state -- the command reads
one name, picks one constant and sends one message.

Storage
-------
The name lives in ``mode/settings.json`` -- the store `!creator` and
`!remind tz` already use -- under ``lover_name``. It is not a secret, so it does
not belong in Replit Secrets, and it has to survive a restart, so it is not a
constant. Reads and writes go through ``Com.core.storage``: every other key in
that file is kept, and ``save_json`` renames a temporary file over the target,
so a restart mid-write cannot leave a truncated store.

Delivery and layout
-------------------
One message, edited into the command message through ``Com/core/reply.py`` (the
same path `!chat` uses). A single line is far inside Telegram's 4096 limit.

The message is a script-font ``Love`` header over the line in italics. The
header is ordinary Unicode letters from ``Com/core/fonts.py``, so it renders in
every client without any markup; the italics are one ``<i>`` tag sent with
``parse_mode="html"``. The name itself is never re-styled -- a name the owner
set in one font must not come back in another.

Name handling and formatting injection
--------------------------------------
The name is pasted into the text, so it is filtered before it is stored: 1-30
characters after collapsing runs of whitespace, no control or invisible
formatting characters, and none of the characters that would split or mark up
the message -- ``*``, ``_``, backticks, angle brackets, backslashes, ``~``,
``|``, brackets, braces, ``#``, ``@`` and ``$``. Everything else is kept, so
names in any language and any Unicode font work (``𝐒𝐚𝐫𝐚𝐡``, ``𝓢𝓪𝓻𝓪𝓱``,
``Ｓａｒａｈ``).

Because the message is parsed as HTML, the name and the chosen line go through
``html.escape`` before they are sent: a name can never open a tag, and an ``&``
cannot start an entity. Substitution uses ``str.replace("{name}", name)``,
never ``str.format``, so braces inside an edited line cannot raise.

Who can use it
--------------
Owner-only, through the same ``from_users=my_id`` gate as every other self-bot
command. A public handler would be a second, differently shaped registration
that answers strangers in every chat, costs one outgoing message per stranger,
and could drift from the single owner check used everywhere else.
"""
import html
import logging
import random
import unicodedata

from telethon import events

from Com.core.fonts import script
from Com.core.reply import say
from Com.core.storage import load_store, save_json

log = logging.getLogger("selftg.love")

SETTINGS_FILE = "mode/settings.json"
SETTINGS_VERSION = 1
KEY = "lover_name"

# Markup that would split the message; every other character is kept
BLOCKED_CHARS = set("*_`<>\\~|[](){}#@$")
MAX_NAME = 30

# The header above every line; plain Unicode letters, no markup
HEADER = f"♡ {script('Love')} ♡"

# The twenty lines `!love` picks from; {name} is replaced with the stored name.
LOVE_LINES = (
    "{name} is the first thought I want in the morning and the last one I keep at night.",
    "I stopped looking for the right person the day {name} walked in.",
    "There's no version of my future I want that doesn't have {name} in it.",
    "My whole heart has one address, and it's wherever {name} is.",
    "The best part of my day is the part I spend with {name}.",
    "I didn't know what home felt like until {name} said my name.",
    "A thousand times over, I would still choose {name}.",
    "Everything in me goes quiet when {name} is near.",
    "Give me the ordinary days, as long as they're with {name}.",
    "Loving {name} is the easiest thing I have ever done.",
    "{name} is the name my heart says before I fall asleep.",
    "Every good thing in my life starts with {name}.",
    "If I had to do it all again, I'd find {name} sooner.",
    "I want the loud years and the quiet ones, all of them with {name}.",
    "{name} laughs and the whole day makes sense again.",
    "There is nothing I wouldn't do twice for {name}.",
    "I keep every small thing {name} says, and I keep it close.",
    "Some people arrive and change everything; {name} did that.",
    "Wherever {name} is, that's the place I want to be.",
    "Falling for {name} was never a choice; it was the truth.",
)

__HELP__ = (
    "!love <name> → Save the lover's name\n"
    "!love → Send one of the twenty lines, for that name\n"
    "The lines are `LOVE_LINES` in Com/love.py; edit them there."
)
__CATEGORY__ = "Utilities"


#------------------------------
#Name check
#------------------------------

def _bad_char(name):
    """First character that is markup or invisible, or None when all are fine."""
    for ch in name:
        if ch in BLOCKED_CHARS or unicodedata.category(ch).startswith("C"):
            return ch
    return None


def normalize_name(raw):
    """Collapse spaces and validate a name; raises ValueError with a short reason."""
    name = " ".join((raw or "").split())
    if not name:
        raise ValueError("Usage: <code>!love NAME</code>, e.g. <code>!love Sarah</code>")
    if len(name) > MAX_NAME:
        raise ValueError(f"that name is longer than {MAX_NAME} characters")
    if _bad_char(name) is not None:
        raise ValueError(
            "that name has characters that aren't allowed — letters in any "
            "language or font are fine, markup is not"
        )
    if name[0] in "-'\u2019" or name[-1] in "-'\u2019":
        raise ValueError("a name can't start or end with a hyphen or apostrophe")
    return name


#------------------------------
#State
#------------------------------

def load_name():
    """Return the stored name, or None. Never raises."""
    try:
        data = load_store(SETTINGS_FILE, SETTINGS_VERSION, dict)
    except Exception:  # noqa: BLE001 - an unreadable store means "not set"
        log.exception("love: could not read %s", SETTINGS_FILE)
        return None
    value = data.get(KEY) if isinstance(data, dict) else None
    if not isinstance(value, str):
        return None
    return value.strip() or None


def store_name(name):
    """Save `name`; True only on a real write. Other keys are kept."""
    try:
        data = load_store(SETTINGS_FILE, SETTINGS_VERSION, dict)
    except Exception:  # noqa: BLE001 - refuse rather than clobber an unknown file
        log.exception("love: could not read %s", SETTINGS_FILE)
        return False
    if not isinstance(data, dict):
        data = {}
    data[KEY] = name
    data.setdefault("_version", SETTINGS_VERSION)
    try:
        save_json(SETTINGS_FILE, data)
    except Exception:  # noqa: BLE001 - report it; save_json kept the old file
        log.exception("love: could not write %s", SETTINGS_FILE)
        return False
    return True


#------------------------------
#Rendering
#------------------------------

def pick_line(name):
    """One random line with `name` filled in; "" when no line is left."""
    lines = []
    for template in LOVE_LINES:
        line = (template or "").replace("{name}", name).strip()
        if line:
            lines.append(line)
    return random.choice(lines) if lines else ""


def render_line(name):
    """The message `!love` sends: script header, one italic line; "" if empty."""
    line = pick_line(name)
    if not line:
        return ""
    return f"{HEADER}\n<i>{html.escape(line)}</i>"


#------------------------------
#Command handler
#------------------------------

def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!love(?:\s+([\s\S]*))?$"))
    async def love_cmd(event):
        if not event.out or event.sender_id != my_id:
            return

        args = (event.pattern_match.group(1) or "").strip()

        # `!love` alone: one line, for the name that was saved earlier
        if not args:
            name = load_name()
            if name is None:
                await _say(
                    event,
                    "❌ <b>No name set yet.</b>\n"
                    "Use <code>!love NAME</code> first, e.g. <code>!love Sarah</code>.",
                )
                return
            text = render_line(name)
            if not text:
                await _say(
                    event,
                    "❌ <code>LOVE_LINES</code> in <code>Com/love.py</code> is "
                    "empty. Add the lines there and restart the Repl.",
                )
                return
            await _say(event, text)
            return

        # `!love <name>`: remember the name
        try:
            name = normalize_name(args)
        except ValueError as exc:
            await _say(event, f"❌ {exc}")
            return
        if not store_name(name):
            await _say(
                event,
                "❌ <b>Could not save the name.</b> "
                f"<code>{SETTINGS_FILE}</code> is unavailable; nothing was changed.",
            )
            return
        await _say(
            event,
            f"✅ <b>Lover set</b> to <i>{html.escape(name)}</i>\n"
            f"<code>!love</code> now sends one of the {len(LOVE_LINES)} lines.",
        )

    async def _say(event, text):
        # Edit-then-reply is shared: see Com/core/reply.py.
        await say(event, text, name="love", parse_mode="html")
