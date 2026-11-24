"""`!pirate`, `!shakespeare`, `!uwu`, `!leet` -- local text transformers.

Four small substitution tables, no API and no model. They exist because the
cheapest way to make a bot feel like it understood a message is to hand the
message back wearing a hat, and because each one costs a regex pass.

Input is the typed text or the message being replied to, capped so a pasted
essay cannot produce a message Telegram rejects. The transformed text is escaped
before it enters the HTML body; nothing here trusts its input.
"""
import logging
import random
import re

from telethon import events

from Com.core import brand
from Com.core.reply import say

__HELP__ = (
    "!pirate <text> (or reply) → Say it like a pirate\n"
    "!shakespeare <text> (or reply) → Say it like the Bard\n"
    "!uwu <text> (or reply) → Say it, regrettably, like that\n"
    "!leet <text> (or reply) → 5p34k 1n l337"
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.style")

MAX_INPUT = 800

_RNG = random.SystemRandom()


#------------------------------
#Pirate
#------------------------------

PIRATE_WORDS = {
    "you": "ye", "your": "yer", "yours": "yers", "my": "me", "friend": "matey",
    "friends": "hearties", "hello": "ahoy", "hi": "ahoy", "yes": "aye",
    "stop": "avast", "are": "be", "is": "be", "am": "be", "the": "th'",
    "there": "thar", "here": "hyar", "of": "o'", "and": "an'", "going": "goin'",
    "doing": "doin'", "nothing": "nothin'", "something": "somethin'",
    "money": "doubloons", "drink": "grog", "food": "victuals", "boat": "ship",
    "ship": "fine ship", "everyone": "all hands", "people": "scallywags",
    "understand": "savvy", "look": "spy", "steal": "plunder", "leave": "depart",
}

PIRATE_OPENERS = ("Arr!", "Avast!", "Yo-ho-ho!", "Shiver me timbers!")


def _pirate(text):
    words = re.sub(
        r"[A-Za-z']+",
        lambda match: _match_case(match.group(0), PIRATE_WORDS.get(match.group(0).lower())),
        text,
    )
    opener = _RNG.choice(PIRATE_OPENERS)
    return f"{opener} {words}"


#------------------------------
#Shakespeare
#------------------------------

BARD_WORDS = {
    "you": "thou", "your": "thy", "yours": "thine", "are": "art", "have": "hast",
    "has": "hath", "do": "dost", "does": "doth", "did": "didst", "will": "shalt",
    "would": "wouldst", "can": "canst", "could": "couldst", "shall": "shalt",
    "hello": "good morrow", "hi": "good morrow", "yes": "aye", "no": "nay",
    "friend": "good friend", "friends": "good friends", "please": "prithee",
    "before": "ere", "soon": "anon", "nothing": "naught", "something": "somewhat",
    "listen": "hark", "stop": "stay", "go": "hie", "quickly": "apace",
    "truly": "forsooth", "perhaps": "perchance", "never": "ne'er",
}

BARD_CLOSERS = ("Forsooth.", "I prithee, mark it.", "So it doth stand.", "")


def _shakespeare(text):
    words = re.sub(
        r"[A-Za-z']+",
        lambda match: _match_case(match.group(0), BARD_WORDS.get(match.group(0).lower())),
        text,
    )
    closer = _RNG.choice(BARD_CLOSERS)
    return f"{words} {closer}".strip()


#------------------------------
#Uwu
#------------------------------

def _uwu(text):
    out = text.replace("r", "w").replace("R", "W")
    out = out.replace("l", "w").replace("L", "W")
    out = re.sub(r"\bno\b", "nyo", out, flags=re.IGNORECASE)
    out = re.sub(r"\byou\b", "yuw", out, flags=re.IGNORECASE)
    out = re.sub(r"n(?=[aeiouAEIOU])", "ny", out)
    out = out.replace("!", "! uwu").replace("?", "? owo")
    if "uwu" not in out.lower() and "owo" not in out.lower():
        out += " uwu"
    return out


#------------------------------
#Leet
#------------------------------

LEET = str.maketrans({
    "a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "t": "7", "g": "9",
    "A": "4", "E": "3", "I": "1", "O": "0", "S": "5", "T": "7", "G": "9",
})


def _leet(text):
    return text.translate(LEET)


#------------------------------
#Shared
#------------------------------

def _match_case(original, replacement):
    """Apply a replacement without flattening the original capitalisation."""
    if not replacement:
        return original
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


async def _target_text(event, rest):
    """Explicit text, else the replied message's text, else empty."""
    if rest:
        return rest
    if event.is_reply:
        reply = await event.get_reply_message()
        if reply:
            return reply.raw_text or ""
    return ""


def setup(client, my_id):

    async def _transform(event, title, transform):
        raw = (await _target_text(event, event.pattern_match.group(1) or "")).strip()
        if not raw:
            command = event.raw_text.split()[0].lstrip("!")
            await say(
                event,
                f"❌ <b>Nothing to transform.</b>\n"
                f"Usage · <code>!{brand.esc(command)} &lt;text&gt;</code> "
                "(or reply to a message).",
                name="style", parse_mode="html",
            )
            return
        trimmed = len(raw) > MAX_INPUT
        if trimmed:
            raw = raw[:MAX_INPUT]
        result = transform(raw)
        if not result or not result.strip():
            await say(event, "❌ <b>That came out empty.</b> Try a longer line.",
                      name="style", parse_mode="html")
            return
        body = f"✍️ <b>{brand.esc(title)}</b>\n\n<blockquote>{brand.esc(result)}</blockquote>"
        if trimmed:
            body += f"\n\n<i>Trimmed to the first {MAX_INPUT} characters.</i>"
        if not await say(event, body, name="style", parse_mode="html"):
            log.info("style: could not deliver an answer")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!pirate(?:\s+([\s\S]+))?$"))
    async def pirate_cmd(event):
        await _transform(event, "Pirate", _pirate)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!shakespeare(?:\s+([\s\S]+))?$"))
    async def shakespeare_cmd(event):
        await _transform(event, "Shakespeare", _shakespeare)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!uwu(?:\s+([\s\S]+))?$"))
    async def uwu_cmd(event):
        await _transform(event, "Uwu", _uwu)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!leet(?:\s+([\s\S]+))?$"))
    async def leet_cmd(event):
        await _transform(event, "Leet", _leet)
