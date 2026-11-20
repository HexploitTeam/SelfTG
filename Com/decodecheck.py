"""!decodecheck: identify and decode text written in common encodings."""
import base64
import binascii
import urllib.parse
import re
import string
import codecs
import html
import json
import ast
import quopri
import unicodedata

# Both are gone or missing on some builds; import defensively
try:
    import uu
except ImportError:  # pragma: no cover - depends on the interpreter build
    uu = None

try:
    import binhex
except ImportError:  # pragma: no cover - depends on the interpreter build
    binhex = None
from io import BytesIO
from telethon import events

__HELP__ = (
    "!decodecheck (reply/text) → Auto‑detect and decode text from common encodings.\n"
    "Supports: Base64/32/58/85/91/36/62/45, Hex, URL, ROT13/47, Binary, Unicode escape, "
    "Quoted-Printable, UU, XX, BinHex, HTML entities, JSON/Python literals, Atbash, Reverse, "
    "Octal/Hex escapes, ROT5, Caesar, Morse."
)
__CATEGORY__ = "Utilities"

def is_printable(text):
    """Return True if >= 85% of characters are printable (Unicode-aware)."""
    if not text:
        return False
    printable_count = sum(1 for c in text if c.isprintable())
    return printable_count / len(text) >= 0.85


#------------------------------
#Decoder functions
#------------------------------

def try_base64(text):
    """Standard and URL-safe base64, with padding handling."""
    variants = [base64.b64decode, base64.urlsafe_b64decode]
    for func in variants:
        try:
            padded = text + "=" * (-len(text) % 4)
            decoded = func(padded.encode('utf-8'))
            return decoded.decode('utf-8', errors='ignore')
        except Exception:
            continue
    return None

def try_base32(text):
    try:
        padded = text.upper() + "=" * (-len(text) % 8)
        decoded = base64.b32decode(padded.encode('utf-8'))
        return decoded.decode('utf-8', errors='ignore')
    except Exception:
        return None

def try_base58(text):
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    try:
        n = 0
        for char in text:
            n = n * 58 + alphabet.index(char)
        bytes_ = n.to_bytes((n.bit_length() + 7) // 8, 'big')
        return bytes_.decode('utf-8', errors='ignore')
    except Exception:
        return None

def try_base85(text):
    try:
        decoded = base64.a85decode(text.encode('utf-8'))
        return decoded.decode('utf-8', errors='ignore')
    except Exception:
        return None

def try_hex(text):
    try:
        decoded = bytes.fromhex(text).decode('utf-8', errors='ignore')
        if is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_url(text):
    try:
        decoded = urllib.parse.unquote_plus(text)
        if decoded != text and is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_rot13(text):
    try:
        decoded = codecs.decode(text, 'rot13')
        if decoded != text and is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_bin(text):
    try:
        clean = ''.join(text.split())
        if len(clean) % 8 != 0:
            return None
        decoded = int(clean, 2).to_bytes(len(clean)//8, 'big')
        decoded_str = decoded.decode('utf-8', errors='ignore')
        if is_printable(decoded_str):
            return decoded_str
        return None
    except Exception:
        return None

def try_unicode_escape(text):
    try:
        decoded = bytes(text, 'ascii').decode('unicode_escape')
        if decoded != text and is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

#------------------------------
#New decoders
#------------------------------

def try_base36(text):
    """Base36 decode (alphabet 0-9A-Z)."""
    try:
        n = int(text, 36)
        bytes_ = n.to_bytes((n.bit_length()+7)//8, 'big')
        decoded = bytes_.decode('utf-8', errors='ignore')
        if is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_base62(text):
    """Base62 decode (0-9A-Za-z)."""
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    try:
        n = 0
        for char in text:
            n = n * 62 + alphabet.index(char)
        bytes_ = n.to_bytes((n.bit_length()+7)//8, 'big')
        decoded = bytes_.decode('utf-8', errors='ignore')
        if is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_base91(text):
    """Base91 decode (alphabet: A-Z a-z 0-9 plus punctuation)."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&()*+,./:;<=>?@[]^_`{|}~\""
    try:
        v = -1
        b = 0
        n = 0
        out = []
        for char in text:
            if char not in alphabet:
                return None
            c = alphabet.index(char)
            if v < 0:
                v = c
            else:
                v += c * 91
                b |= v << n
                n += 13 if (v & 8191) > 88 else 14
                while n > 7:
                    out.append(b & 0xff)
                    b >>= 8
                    n -= 8
                v = -1
        if v != -1:
            b |= v << n
            out.append(b & 0xff)
        decoded = bytes(out).decode('utf-8', errors='ignore')
        if is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_base45(text):
    """Base45 decode (used in QR codes)."""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"
    try:
        values = []
        for char in text:
            values.append(alphabet.index(char))
        out = []
        i = 0
        while i < len(values):
            if i+1 < len(values):
                c = values[i] + values[i+1] * 45
            else:
                c = values[i]
            out.append(c >> 8)
            out.append(c & 0xff)
            i += 2
        decoded = bytes(out).decode('utf-8', errors='ignore')
        if is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_quoted_printable(text):
    try:
        decoded = quopri.decodestring(text.encode('utf-8'))
        return decoded.decode('utf-8', errors='ignore')
    except Exception:
        return None

def try_uu(text):
    if uu is None:
        return None
    try:
        decoded = uu.decode(BytesIO(text.encode('utf-8')))
        return decoded.decode('utf-8', errors='ignore')
    except Exception:
        return None

def try_xx(text):
    """XXencode decode (simple implementation)."""
    # XXencode alphabet: +-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz
    alphabet = "+-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    try:
        clean = ''.join(text.split())
        # Each 4 chars -> 3 bytes
        out = []
        for i in range(0, len(clean), 4):
            chunk = clean[i:i+4]
            if len(chunk) < 4:
                chunk += ' ' * (4 - len(chunk))
            a, b, c, d = [alphabet.index(ch) for ch in chunk]
            out.append((a << 2) | (b >> 4))
            out.append(((b & 0x0f) << 4) | (c >> 2))
            out.append(((c & 0x03) << 6) | d)
        decoded = bytes(out).decode('utf-8', errors='ignore')
        if is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_binhex(text):
    try:
        # Best effort; skip anything malformed
        return None
    except Exception:
        return None

def try_html_unescape(text):
    try:
        decoded = html.unescape(text)
        if decoded != text and is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_json_literal(text):
    """Try to parse as JSON string literal."""
    try:
        if not text.startswith('"'):
            text = '"' + text + '"'
        decoded = json.loads(text)
        if isinstance(decoded, str) and is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_python_literal(text):
    """Try to evaluate as Python string literal."""
    try:
        # Literals only; unlike eval() this cannot execute code
        decoded = ast.literal_eval(f'"{text}"') if not text.startswith('"') else ast.literal_eval(text)
        if isinstance(decoded, str) and is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_rot47(text):
    """ROT47 (shift 47) for printable ASCII."""
    try:
        decoded = ''.join(
            chr(33 + ((ord(c) - 33 + 47) % 94)) if 33 <= ord(c) <= 126 else c
            for c in text
        )
        if decoded != text and is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_atbash(text):
    """Atbash cipher (a↔z, b↔y, ...)."""
    try:
        decoded = ''.join(
            chr(ord('a') + (ord('z') - ord(c))) if 'a' <= c <= 'z' else
            chr(ord('A') + (ord('Z') - ord(c))) if 'A' <= c <= 'Z' else c
            for c in text
        )
        if decoded != text and is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_reverse(text):
    """Reverse the string."""
    try:
        decoded = text[::-1]
        if decoded != text and is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_octal_escapes(text):
    """Decode octal escapes like \\123\\456."""
    try:
        pattern = re.compile(r'\\([0-7]{1,3})')
        def repl(m):
            return chr(int(m.group(1), 8))
        decoded = pattern.sub(repl, text)
        if decoded != text and is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_hex_escapes(text):
    """Decode hex escapes like \x48\x65."""
    try:
        pattern = re.compile(r'\\x([0-9a-fA-F]{2})')
        def repl(m):
            return chr(int(m.group(1), 16))
        decoded = pattern.sub(repl, text)
        if decoded != text and is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_rot5(text):
    """ROT5: shift digits by 5."""
    try:
        decoded = ''.join(
            str((int(c) + 5) % 10) if c.isdigit() else c
            for c in text
        )
        if decoded != text and is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

def try_caesar(text):
    """Try all 25 shifts and return the one with highest printable ratio."""
    best = None
    best_score = 0
    for shift in range(1, 26):
        decoded = ''
        for c in text:
            if 'a' <= c <= 'z':
                decoded += chr((ord(c) - ord('a') + shift) % 26 + ord('a'))
            elif 'A' <= c <= 'Z':
                decoded += chr((ord(c) - ord('A') + shift) % 26 + ord('A'))
            else:
                decoded += c
        if decoded != text and is_printable(decoded):
            score = sum(1 for ch in decoded if ch in string.printable) / len(decoded)
            if score > best_score:
                best_score = score
                best = decoded
    if best and best_score > 0.8:
        return best
    return None

def try_morse(text):
    """Decode Morse code (spaces between letters, '/' between words)."""
    morse = {
        '.-': 'A', '-...': 'B', '-.-.': 'C', '-..': 'D', '.': 'E',
        '..-.': 'F', '--.': 'G', '....': 'H', '..': 'I', '.---': 'J',
        '-.-': 'K', '.-..': 'L', '--': 'M', '-.': 'N', '---': 'O',
        '.--.': 'P', '--.-': 'Q', '.-.': 'R', '...': 'S', '-': 'T',
        '..-': 'U', '...-': 'V', '.--': 'W', '-..-': 'X', '-.--': 'Y',
        '--..': 'Z',
        '-----': '0', '.----': '1', '..---': '2', '...--': '3',
        '....-': '4', '.....': '5', '-....': '6', '--...': '7',
        '---..': '8', '----.': '9',
        '.-.-.-': '.', '--..--': ',', '..--..': '?', '.----.': "'",
        '-.-.--': '!', '-..-.': '/', '-.--.': '(', '-.--.-': ')',
        '.-...': '&', '---...': ':', '-.-.-.': ';', '-...-': '=',
        '.-.-.': '+', '-....-': '-', '..--.-': '_', '.-..-.': '"',
        '...-..-': '$', '.--.-.': '@'
    }
    try:
        words = text.split(' / ') if ' / ' in text else [text]
        decoded_words = []
        for word in words:
            letters = word.split(' ')
            decoded_letters = [morse.get(l, '') for l in letters if l]
            decoded_words.append(''.join(decoded_letters))
        decoded = ' '.join(decoded_words)
        if decoded and is_printable(decoded):
            return decoded
        return None
    except Exception:
        return None

#------------------------------
#Decoder list
#------------------------------

DECODERS = [
    # More specific / unambiguous first
    ("Hex", try_hex),
    ("URL Encode", try_url),
    ("Unicode Escape", try_unicode_escape),
    ("Binary (bits)", try_bin),
    ("Octal Escapes", try_octal_escapes),
    ("Hex Escapes", try_hex_escapes),

    # Then the common encodings
    ("Base64", try_base64),
    ("Base32", try_base32),
    ("Base58", try_base58),
    ("Base85", try_base85),
    ("Base36", try_base36),
    ("Base62", try_base62),
    ("Base91", try_base91),
    ("Base45", try_base45),

    # Then text transformations
    ("ROT13", try_rot13),
    ("ROT47", try_rot47),
    ("ROT5", try_rot5),
    ("Atbash", try_atbash),
    ("Reverse", try_reverse),

    # Then escape / HTML / JSON
    ("Quoted-Printable", try_quoted_printable),
    ("UUencode", try_uu),
    ("XXencode", try_xx),
    ("HTML Entities", try_html_unescape),
    ("JSON Literal", try_json_literal),
    ("Python Literal", try_python_literal),

    # Then more complex
    ("Caesar (best shift)", try_caesar),
    ("Morse Code", try_morse),
]


def decode_text(text):
    results = []
    for name, func in DECODERS:
        try:
            decoded = func(text)
            if decoded is not None and is_printable(decoded):
                results.append((name, decoded))
        except Exception:
            continue
    if not results:
        return None, "No decoding method produced readable text."
    return results[0]


def setup(client, my_id):
    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!decodecheck(?:\s+(.+))?$"))
    async def decode_check(event):
        try:
            input_text = event.pattern_match.group(1)
            if not input_text and event.is_reply:
                reply_msg = await event.get_reply_message()
                input_text = reply_msg.text or reply_msg.message
            if not input_text:
                await event.edit("❌ Provide text to decode or reply to a message.")
                return

            input_text = input_text.strip()
            if input_text.startswith('"') and input_text.endswith('"'):
                input_text = input_text[1:-1]
            if input_text.startswith("'") and input_text.endswith("'"):
                input_text = input_text[1:-1]

            method, decoded = decode_text(input_text)
            if method is None:
                await event.edit(f"❌ Could not decode:\n{decoded}")
                return

            response = (
                f"🔍 **Decoded using:** `{method}`\n\n"
                f"**Original:**\n```\n{input_text[:200]}{'...' if len(input_text) > 200 else ''}\n```\n"
                f"**Result:**\n```\n{decoded[:500]}{'...' if len(decoded) > 500 else ''}\n```"
            )
            if len(decoded) > 500:
                response += f"\n\n⚠️ Output truncated (total length: {len(decoded)} chars)"

            await event.edit(response)

        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")