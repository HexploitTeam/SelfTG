"""`!love <name>` -- ten fixed lines for the person the owner names.

The lines are source, not data: ``LOVE_LINES`` below is the whole feature.
There is no API, no model, no cache, no per-chat state and no rate limiting,
because there is no external call to protect -- the command formats a constant
and sends one message.

Delivery
--------
One message with all ten lines, edited into the command message through
``Com/core/reply.py`` (the same path `!chat` uses). Ten separate messages would
be ten outgoing events for one command -- exactly the burst the flood gate in
``Com/core/flood.py`` exists to slow -- and would read as spam. The formatted
message is roughly 600 characters, far inside Telegram's 4096 limit.

Name handling and formatting injection
--------------------------------------
The given name is pasted into the text, so it is filtered before use: 1-30
characters after collapsing runs of whitespace, no control or invisible
formatting characters, and none of the characters that would split or mark up
the message -- ``*``, ``_``, backticks, angle brackets, backslashes, ``~``,
``|``, brackets, braces, ``#``, ``@`` and ``$``. Everything else is kept, so
names in any language and any Unicode font work (``𝐒𝐚𝐫𝐚𝐡``, ``𝓢𝓪𝓻𝓪𝓱``,
``Ｓａｒａｈ``). As a second layer the message is sent with no ``parse_mode`` and
no entities, so the characters that are allowed stay literal.

Substitution uses ``str.replace("{name}", name)``, never ``str.format``: braces
inside an edited line cannot raise ``KeyError`` or ``IndexError``.

Who can use it
--------------
Owner-only, through the same ``from_users=my_id`` gate as every other self-bot
command. A public handler would be a second, differently shaped registration
that answers strangers in every chat, costs one outgoing message per stranger,
and could drift from the single owner check used everywhere else.
"""
import logging
import unicodedata

from telethon import events

from Com.core.reply import say

log = logging.getLogger("selftg.love")

# Markup that would split the message; every other character is kept
BLOCKED_CHARS = set("*_`<>\\~|[](){}#@$")
MAX_NAME = 30

# The ten lines `!love` prints; {name} is replaced with the given name.
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
)

__HELP__ = (
    "!love <name> → Ten short lines for that person\n"
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
        raise ValueError("Usage: `!love <name>` — e.g. `!love Sarah`")
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
#Rendering
#------------------------------

def build_message(name):
    """Substitute `name` into every configured line; "" when none are left."""
    lines = []
    for template in LOVE_LINES:
        line = (template or "").replace("{name}", name).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


#------------------------------
#Command handler
#------------------------------

def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!love(?:\s+([\s\S]*))?$"))
    async def love_cmd(event):
        if not event.out or event.sender_id != my_id:
            return

        args = (event.pattern_match.group(1) or "").strip()
        try:
            name = normalize_name(args)
        except ValueError as exc:
            await _say(event, f"❌ {exc}")
            return

        text = build_message(name)
        if not text:
            await _say(
                event,
                "❌ `LOVE_LINES` in Com/love.py is empty. Add the lines there and "
                "restart the Repl.",
            )
            return

        await _say(event, text)

    async def _say(event, text):
        # Edit-then-reply is shared: see Com/core/reply.py.
        await say(event, text, name="love")
