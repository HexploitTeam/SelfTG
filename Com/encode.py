"""!encode: text encoders that mirror the decoders in Com/decodecheck.py."""
import base64
import urllib.parse
import codecs
import html
import re
from telethon import events
import Com.core.tgsend as tgsend
from Com.core import brand
from Com.core.reply import say

__HELP__ = (
    "!encode <method> <text> → Encode text using a specific method.\n"
    "!encode ALL <text> → Encode using all available methods.\n\n"
    "Available methods:\n"
    "base64, base32, base58, base85, base36, base62, base45, base91,\n"
    "hex, url, rot13, rot47, rot5, atbash, reverse, unicode, html,\n"
    "binary, quoted-printable, uuencode, xxencode"
)
__CATEGORY__ = "Utilities"


#------------------------------
#Encoder functions
#------------------------------

def encode_base64(text):
    return base64.b64encode(text.encode('utf-8')).decode('utf-8')

def encode_base32(text):
    return base64.b32encode(text.encode('utf-8')).decode('utf-8')

def encode_base58(text):
    try:
        import base58
        return base58.b58encode(text.encode('utf-8')).decode('utf-8')
    except ImportError:
        return "⚠️ base58 library not installed (pip install base58)"

def encode_base85(text):
    return base64.a85encode(text.encode('utf-8')).decode('utf-8')

def encode_hex(text):
    return text.encode('utf-8').hex()

def encode_url(text):
    return urllib.parse.quote_plus(text)

def encode_rot13(text):
    return codecs.encode(text, 'rot13')

def encode_rot47(text):
    return ''.join(
        chr(33 + ((ord(c) - 33 + 47) % 94)) if 33 <= ord(c) <= 126 else c
        for c in text
    )

def encode_rot5(text):
    return ''.join(
        str((int(c) + 5) % 10) if c.isdigit() else c
        for c in text
    )

def encode_atbash(text):
    return ''.join(
        chr(ord('a') + (ord('z') - ord(c))) if 'a' <= c <= 'z' else
        chr(ord('A') + (ord('Z') - ord(c))) if 'A' <= c <= 'Z' else c
        for c in text
    )

def encode_reverse(text):
    return text[::-1]

def encode_unicode_escape(text):
    return ''.join(f'\\u{ord(c):04x}' for c in text)

def encode_html_entities(text):
    return ''.join(f'&#{ord(c)};' for c in text)

def encode_binary(text):
    return ' '.join(format(ord(c), '08b') for c in text)

def encode_quoted_printable(text):
    import quopri
    from io import BytesIO
    out = BytesIO()
    quopri.encode(BytesIO(text.encode('utf-8')), out, quotetabs=False)
    return out.getvalue().decode('utf-8')

def encode_uuencode(text):
    from io import BytesIO
    try:
        import uu  # deprecated stdlib module, removed in Python 3.13
    except ImportError:
        return "⚠️ uuencode unavailable: the 'uu' module was removed from this Python"
    in_file = BytesIO(text.encode('utf-8'))
    out_file = BytesIO()
    uu.encode(in_file, out_file, "text.txt")
    return out_file.getvalue().decode('utf-8')

def encode_xxencode(text):
    # XXencode alphabet
    alphabet = "+-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    data = text.encode('utf-8')
    out = []
    for i in range(0, len(data), 3):
        chunk = data[i:i+3]
        # Pad with zeros
        if len(chunk) < 3:
            chunk = chunk + b'\x00' * (3 - len(chunk))
        a, b, c = chunk
        # 3 bytes -> 4 XXencode chars
        out.append(alphabet[(a >> 2) & 0x3f])
        out.append(alphabet[((a << 4) | (b >> 4)) & 0x3f])
        out.append(alphabet[((b << 2) | (c >> 6)) & 0x3f])
        out.append(alphabet[c & 0x3f])
    # Zero padding is kept; Com/decodecheck.py strips it before decoding
    return ''.join(out)

def encode_base36(text):
    import binascii
    n = int.from_bytes(text.encode('utf-8'), 'big')
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    res = []
    while n > 0:
        n, rem = divmod(n, 36)
        res.append(alphabet[rem])
    return ''.join(reversed(res)) or '0'

def encode_base62(text):
    import binascii
    n = int.from_bytes(text.encode('utf-8'), 'big')
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    res = []
    while n > 0:
        n, rem = divmod(n, 62)
        res.append(alphabet[rem])
    return ''.join(reversed(res)) or '0'

def encode_base45(text):
    # Base45 alphabet (0-9 A-Z space $%*+-./:)
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"
    data = text.encode('utf-8')
    out = []
    for i in range(0, len(data), 2):
        if i+1 < len(data):
            c = (data[i] << 8) | data[i+1]
        else:
            c = data[i] << 8
        out.append(alphabet[c % 45])
        c //= 45
        out.append(alphabet[c % 45])
        if i+1 >= len(data):
            break
    return ''.join(out)

def encode_base91(text):
    # Base91 alphabet
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&()*+,./:;<=>?@[]^_`{|}~\""
    data = text.encode('utf-8')
    b = 0
    n = 0
    out = []
    for byte in data:
        b |= byte << n
        n += 8
        if n > 13:
            v = b & 8191
            if v > 88:
                b >>= 13
                n -= 13
            else:
                v = b & 16383
                b >>= 14
                n -= 14
            out.append(alphabet[v % 91])
            v //= 91
            out.append(alphabet[v % 91])
    if n:
        out.append(alphabet[b % 91])
        if n > 7 or b > 90:
            b //= 91
            out.append(alphabet[b % 91])
    return ''.join(out)


#------------------------------
#Encoder registry
#------------------------------

ENCODERS = {
    "base64": encode_base64,
    "base32": encode_base32,
    "base58": encode_base58,
    "base85": encode_base85,
    "base36": encode_base36,
    "base62": encode_base62,
    "base45": encode_base45,
    "base91": encode_base91,
    "hex": encode_hex,
    "url": encode_url,
    "rot13": encode_rot13,
    "rot47": encode_rot47,
    "rot5": encode_rot5,
    "atbash": encode_atbash,
    "reverse": encode_reverse,
    "unicode": encode_unicode_escape,
    "html": encode_html_entities,
    "binary": encode_binary,
    "quoted-printable": encode_quoted_printable,
    "uuencode": encode_uuencode,
    "xxencode": encode_xxencode,
}

# Display emoji for each encoder
EMOJIS = {
    "base64": "🔐",
    "base32": "🔐",
    "base58": "🔐",
    "base85": "🔐",
    "base36": "🔢",
    "base62": "🔢",
    "base45": "🔢",
    "base91": "🔢",
    "hex": "📦",
    "url": "🔗",
    "rot13": "🔄",
    "rot47": "🔄",
    "rot5": "🔄",
    "atbash": "🔄",
    "reverse": "↔️",
    "unicode": "💠",
    "html": "🌐",
    "binary": "⚡",
    "quoted-printable": "📧",
    "uuencode": "📎",
    "xxencode": "📎",
}

def setup(client, my_id):
    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!encode\s+([A-Za-z0-9\-]+)\s+(.+)$"))
    async def encode_cmd(event):
        try:
            method = event.pattern_match.group(1).lower()
            text = event.pattern_match.group(2)

            if method == "all":
                output = "📦 <b>All Encodings</b>\n"
                output += f"Input · <code>{brand.esc(text)}</code>\n"
                for name, func in sorted(ENCODERS.items()):
                    label = f"{EMOJIS.get(name, '🔹')} <b>{name.upper()}</b>"
                    try:
                        encoded = func(text)
                        if encoded.startswith("⚠️"):
                            output += f"\n{label} · <i>{brand.esc(encoded)}</i>"
                        else:
                            output += f"\n{label} · <code>{brand.esc(encoded)}</code>"
                    except Exception as e:
                        output += f"\n❌ <b>{name.upper()}</b> · <i>{brand.esc(e)}</i>"
                if len(output) > 4000:
                    import io
                    bio = io.BytesIO(brand.plain(output).encode('utf-8'))
                    bio.name = "encodings.txt"
                    await client.send_file(
                        await tgsend.peer(event), bio,
                        caption=brand.sign("📦 <b>All Encodings</b>", "encode"),
                        parse_mode="html")
                    await event.delete()
                else:
                    await say(event, output, name="encode", parse_mode="html")
                return

            if method not in ENCODERS:
                await say(event,
                          f"❌ Unknown method · <code>{brand.esc(method)}</code>\n"
                          "Available · "
                          f"<code>{', '.join(sorted(ENCODERS.keys()))}</code>",
                          name="encode", parse_mode="html")
                return

            encoded = ENCODERS[method](text)
            if encoded.startswith("⚠️"):
                await say(event, f"❌ {brand.esc(encoded)}",
                          name="encode", parse_mode="html")
                return

            emoji = EMOJIS.get(method, "🔐")
            await say(event,
                      f"{emoji} <b>Encoded with {method.upper()}</b>\n"
                      f"Input · <code>{brand.esc(text)}</code>\n\n"
                      f"<code>{brand.esc(encoded)}</code>",
                      name="encode", parse_mode="html")

        except Exception as e:
            await say(event, f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="encode", parse_mode="html")
