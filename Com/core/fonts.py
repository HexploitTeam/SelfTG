"""Unicode font styles for command output.

Telegram's own bold and italic stop at Latin letters and need a ``parse_mode``;
a styled label made of Unicode letters (``𝓛𝓸𝓿𝓮``) is ordinary text, so it
renders the same in every client, needs no parse mode and cannot interfere with
the entities of the message around it.

Only the two styles the commands actually use are here. Each one maps the
letters it knows and leaves every other character alone, so calling it on text
that already contains a font, an emoji or a brace is safe.

This module has no ``setup()`` and no ``__HELP__``.
"""

# Mathematical Bold Script: U+1D4D0 'A' ... U+1D4E9 'Z', U+1D4EA 'a' ... U+1D503 'z'
_SCRIPT = {chr(ord("A") + i): chr(0x1D4D0 + i) for i in range(26)}
_SCRIPT.update({chr(ord("a") + i): chr(0x1D4EA + i) for i in range(26)})

# Small capitals have no lowercase 'x'; it stays as it is rather than becoming
# a full-size letter in an otherwise small line.
_SMALL_CAPS = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ꜰ", "g": "ɢ",
    "h": "ʜ", "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ",
    "o": "ᴏ", "p": "ᴘ", "q": "ǫ", "r": "ʀ", "s": "ꜱ", "t": "ᴛ", "u": "ᴜ",
    "v": "ᴠ", "w": "ᴡ", "y": "ʏ", "z": "ᴢ",
}


def script(text):
    """Bold script letters: ``script("Love")`` is ``𝓛𝓸𝓿𝓮``."""
    return "".join(_SCRIPT.get(ch, ch) for ch in text)


def small_caps(text):
    """Small capitals: ``small_caps("Love")`` is ``ʟᴏᴠᴇ``."""
    return "".join(_SMALL_CAPS.get(ch.lower(), ch) for ch in text)
