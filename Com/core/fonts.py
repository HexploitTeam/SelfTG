"""Unicode font styles for command output.

Telegram's own bold and italic stop at Latin letters and need a ``parse_mode``;
a styled label made of Unicode letters (``𝓛𝓸𝓿𝓮``) is ordinary text, so it
renders the same in every client, needs no parse mode and cannot interfere with
the entities of the message around it.

Only the styles the commands actually use are here. Each one maps the letters
it knows and leaves every other character alone, so calling it on text that
already contains a font, an emoji or a brace is safe.

``sans_bold`` is the readable one -- Mathematical Sans-Serif Bold is a plain
grotesque with normal letter shapes, not a script, so a whole sentence set in it
still reads like a sentence.

This module has no ``setup()`` and no ``__HELP__``.
"""

# Mathematical Bold Script: U+1D4D0 'A' ... U+1D4E9 'Z', U+1D4EA 'a' ... U+1D503 'z'
_SCRIPT = {chr(ord("A") + i): chr(0x1D4D0 + i) for i in range(26)}
_SCRIPT.update({chr(ord("a") + i): chr(0x1D4EA + i) for i in range(26)})

# Mathematical Sans-Serif Bold: U+1D5D4 'A' ... U+1D5ED 'Z',
# U+1D5EE 'a' ... U+1D607 'z', U+1D7EC '0' ... U+1D7F5 '9'
_SANS_BOLD = {chr(ord("A") + i): chr(0x1D5D4 + i) for i in range(26)}
_SANS_BOLD.update({chr(ord("a") + i): chr(0x1D5EE + i) for i in range(26)})
_SANS_BOLD.update({chr(ord("0") + i): chr(0x1D7EC + i) for i in range(10)})

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


def sans_bold(text):
    """Bold sans-serif letters: ``sans_bold("Love")`` is ``𝗟𝗼𝘃𝗲``."""
    return "".join(_SANS_BOLD.get(ch, ch) for ch in text)


def small_caps(text):
    """Small capitals: ``small_caps("Love")`` is ``ʟᴏᴠᴇ``."""
    return "".join(_SMALL_CAPS.get(ch.lower(), ch) for ch in text)
