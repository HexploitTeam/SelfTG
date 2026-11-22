"""The Spooku Self message shape.

Every message the product sends has the same parts::

    <title>
    ────────────────────────
    <body>

    ────────────────────────
    — Spooku Self · !ban

The body carries the meaning -- one line for a confirmation, a titled card for a
listing. A rule under the title and another above the signature set the content
apart from the marks, so the same shape holds on a self-bot answer and on a
companion-bot screen. The signature is the same line everywhere, at the bottom.

Typography
----------
Telegram HTML only:

* ``<b>`` for the one thing the reader is looking for (the username, the id);
* ``<i>`` for an aside or a state, never for a whole message;
* ``<code>`` for an identifier, a command or a value the owner may copy;
* ``<blockquote>`` for quoted material that is not the product's own words.

Nothing else. No font substitution outside ``!creator`` and ``!love`` (whose
exception lives in ``Com/core/fonts.py``), no second accent colour: the body
already uses ✅ for success and ❌ for failure, which is this project's pair.

Escaping
--------
``render`` escapes a plain-text body before signing it. ``sign`` takes a body
that is already HTML and only appends the signature. A command that interpolates
a username, a note or a reason builds its body with ``esc`` first, so the value
cannot open a tag, start an entity or split the signature off the message.

This module has no ``setup()`` and no ``__HELP__``.
"""
import html
import re

NAME = "Spooku Self"

# Telegram has no horizontal rule; a full-width line of box drawing is the one
# divider that survives HTML parse mode and every client
RULE = "─" * 24

# The tags this product uses; a plain-text copy (a .txt export, a log line)
# keeps the words and drops the markup
_TAG = re.compile(r"</?(?:b|i|code|blockquote)>")


def esc(value):
    """Escape one interpolated value for an HTML body."""
    return html.escape(str(value), quote=False)


def sign(body, command=None):
    """Append the signature to an HTML body; `command` adds the origin tag."""
    line = f"— <b>{NAME}</b>"
    if command:
        line += f" · <code>!{str(command).lstrip('!')}</code>"
    text = (body or "").rstrip()
    if not text:
        return line

    # A titled body gets a rule under the title as well as above the signature
    head, sep, rest = text.partition("\n")
    rest = rest.lstrip("\n")
    if sep and rest:
        text = f"{head}\n{RULE}\n\n{rest}"
    return f"{text}\n\n{RULE}\n{line}"


def render(body, command=None):
    """Escape a plain-text body, then sign it."""
    return sign(esc(body), command)


def plain(body):
    """Strip this module's tags and unescape entities, for a .txt export."""
    return html.unescape(_TAG.sub("", body or ""))
