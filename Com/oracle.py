"""`!fortune`, `!tarot`, `!predict`, `!mood` -- the local oracle.

Why none of this calls a model
------------------------------
Each answer is a small table plus a random source: fortunes, a tarot deck with
two readings per card, weighted predictions and a keyword lexicon. That is a few
kilobytes of Python and no quota, no latency and nothing to train. An API would
make every one of these slower and more fragile without making the answer better.

Nothing here reads a message the command was not given. `!mood` looks only at
the text typed after it (or the one message it replies to), never at history,
and the output says it is keyword rules rather than a reading.

All four are owner-only through ``from_users=my_id`` like the rest of the
self-bot; each answer is one message and nothing retries.
"""
import logging
import random
import re

from telethon import events

from Com.core import brand
from Com.core.reply import say

__HELP__ = (
    "!fortune → A fortune and six lucky numbers\n"
    "!tarot [question] → Three-card spread from the major arcana\n"
    "!predict <question> → A weighted verdict, in character\n"
    "!mood <text> (or reply) → Keyword mood readout, for fun"
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.oracle")

MAX_QUESTION = 300
MAX_MOOD_INPUT = 1200

_RNG = random.SystemRandom()


#------------------------------
#Fortune
#------------------------------


FORTUNES = (
    "The thing you keep postponing is cheaper today than it will be tomorrow.",
    "A door you thought was locked is only stuck. Push once more.",
    "Someone is quietly rooting for you and has not said so yet.",
    "The answer arrives when you stop rehearsing the question.",
    "You will be early to something that starts late. Bring a book.",
    "A small kindness you forgot about is still travelling toward you.",
    "The plan is sound; the timeline is fiction.",
    "You are one honest sentence away from a much easier week.",
    "What looks like a detour is the part you will remember.",
    "Say the difficult thing gently, and say it this time.",
    "An old tool still fits the new problem. Check the drawer.",
    "You will meet the right person in the wrong queue.",
    "The budget will stretch if the ego does not.",
    "A message you are drafting gets better every hour you do not send it.",
    "Rest is not a reward for finishing. It is part of the method.",
    "The second attempt will work because of what the first one taught you.",
    "A rumour is not a forecast. Wait for the receipt.",
    "You will find the missing item exactly where you looked first.",
    "The room you are avoiding has better air than you expect.",
    "Someone's silence is about their week, not your worth.",
    "Take the smaller plate. There is dessert later.",
    "The version of you that starts today gets there sooner.",
)


def _fortune_body():
    text = _RNG.choice(FORTUNES)
    numbers = _RNG.sample(range(1, 50), 6)
    return (
        "🥠 <b>Fortune</b>\n\n"
        f"<blockquote>{brand.esc(text)}</blockquote>\n\n"
        "Lucky numbers · <code>"
        + " ".join(str(n) for n in numbers)
        + "</code>"
    )


#------------------------------
#Tarot
#------------------------------


# name, upright, reversed -- the major arcana only, one line each
TAROT = (
    ("The Fool", "a beginning that rewards nerve", "a leap taken before the ground was checked"),
    ("The Magician", "the tools are already in your hands", "polish the trick before the performance"),
    ("The High Priestess", "what is known but not yet said", "a secret kept from yourself"),
    ("The Empress", "growth fed patiently", "a harvest rushed before it ripened"),
    ("The Emperor", "structure that holds", "a rule kept past its usefulness"),
    ("The Hierophant", "a tradition worth asking why", "borrowed authority with a hollow centre"),
    ("The Lovers", "a choice between two goods", "a choice avoided until it chose you"),
    ("The Chariot", "momentum with a direction", "speed without steering"),
    ("Strength", "gentleness that outlasts force", "a grip too tight on a soft thing"),
    ("The Hermit", "solitude that answers", "isolation dressed as wisdom"),
    ("Wheel of Fortune", "a turn you did not schedule", "the same turn, ignored once"),
    ("Justice", "the bill, itemised", "a scale tipped by wishful thinking"),
    ("The Hanged Man", "a delay that reframes", "waiting without changing the angle"),
    ("Death", "an ending that makes room", "an ending kept on life support"),
    ("Temperance", "a measured mix", "too much of the thing that was working"),
    ("The Devil", "a habit with excellent marketing", "the chain was never locked"),
    ("The Tower", "a collapse that tells the truth", "a warning patched over"),
    ("The Star", "quiet hope after weather", "hope mistaken for a plan"),
    ("The Moon", "a path lit in pieces", "a story told by fear"),
    ("The Sun", "plain good fortune, no catch", "a good day overshadowed by habit"),
    ("Judgement", "a summons to be honest", "a verdict you keep appealing"),
    ("The World", "a circle closed", "one loose end holding the circle open"),
)

SPREAD = ("What is", "What crosses", "What follows")


def _tarot_body(question):
    cards = _RNG.sample(TAROT, 3)
    parts = []
    for position, card in zip(SPREAD, cards):
        name, upright, reversed_ = card
        flipped = _RNG.random() < 0.35
        meaning = reversed_ if flipped else upright
        label = f"{name} (reversed)" if flipped else name
        parts.append(
            f"<b>{brand.esc(position)} · {brand.esc(label)}</b>\n"
            f"{brand.esc(meaning)}"
        )
    body = "🔮 <b>Three cards</b>\n"
    if question:
        body += f"<blockquote>{brand.esc(question)}</blockquote>\n"
    return body + "\n" + "\n\n".join(parts)


#------------------------------
#Prediction
#------------------------------


# weight, verdict, one line of colour
PREDICTIONS = (
    (26, "Yes, and sooner than you think", "the obstruction is smaller than the story about it"),
    (18, "Yes, with a condition", "the condition is one you already know and keep renegotiating"),
    (14, "Not yet", "the missing piece is information, not effort"),
    (10, "Ask again after one real conversation", "the answer lives in a person, not a plan"),
    (10, "Leaning no", "not because it is impossible, but because the timing is doing the arguing"),
    (8, "It depends on who moves first", "you are closer to first than you admit"),
    (6, "Yes, but not in the shape you pictured", "keep the outcome, release the storyboard"),
    (5, "The odds are better than the vibe", "proceed, but bring a receipt"),
    (3, "No, and you will be relieved", "the no is a door closing on a draft you did not want"),
)

CONFIDENCE = ((55, 65), (66, 75), (76, 85), (86, 95))


def _predict_body(question):
    weights = [row[0] for row in PREDICTIONS]
    _, verdict, line = _RNG.choices(PREDICTIONS, weights=weights, k=1)[0]
    low, high = _RNG.choice(CONFIDENCE)
    percent = _RNG.randint(low, high)
    return (
        "🔮 <b>Prediction</b>\n"
        f"<blockquote>{brand.esc(question)}</blockquote>\n\n"
        f"<b>{brand.esc(verdict)}</b>\n"
        f"{brand.esc(line)}\n\n"
        f"Confidence · <code>{percent}%</code>"
    )


#------------------------------
#Mood
#------------------------------


POSITIVE = {
    "good", "great", "happy", "glad", "love", "loved", "lovely", "nice", "fun",
    "excited", "exciting", "amazing", "awesome", "brilliant", "win", "won",
    "winning", "yes", "thanks", "thank", "grateful", "proud", "calm", "relaxed",
    "hopeful", "better", "best", "easy", "kind", "safe", "sorted", "ready",
    "delighted", "perfect", "beautiful", "enjoy", "enjoyed", "smile", "laugh",
    "laughing", "yay", "wonderful", "solid", "fresh", "rested", "lucky",
}

NEGATIVE = {
    "bad", "sad", "angry", "mad", "tired", "exhausted", "awful", "terrible",
    "hate", "hated", "annoying", "annoyed", "worried", "worry", "anxious",
    "stress", "stressed", "stressful", "sick", "hurt", "broken", "fail",
    "failed", "failing", "no", "never", "lost", "alone", "lonely", "stuck",
    "confused", "ugh", "crap", "worse", "worst", "hard", "difficult", "mess",
    "messy", "late", "overwhelmed", "drained", "upset", "scared", "afraid",
    "disappointed", "frustrated", "hopeless", "miserable", "pain", "cry",
}

INTENSIFIERS = {
    "very", "really", "so", "extremely", "super", "totally", "absolutely",
    "incredibly", "quite", "too", "deeply", "seriously",
}

NEGATIONS = {"not", "never", "no", "don't", "dont", "isn't", "isnt", "aren't",
             "arent", "wasn't", "wasnt", "didn't", "didnt", "can't", "cant"}

MOOD_BANDS = (
    (3, "☀️", "Bright", "the good words are doing most of the talking"),
    (1, "🌤", "Warm", "more light than shadow in this one"),
    (0, "🌗", "Mixed", "both columns have entries; the tie is the story"),
    (-2, "🌥", "Cloudy", "the heavy words are winning, but not by much"),
    (-99, "⛈", "Stormy", "this reads like a hard day, not a hard life"),
)


def _mood_score(text):
    """Return (positive weight, negative weight, positive words, negative words)."""
    tokens = re.findall(r"[a-z']+", text.lower())
    positive = negative = 0
    positive_words = []
    negative_words = []
    for index, token in enumerate(tokens):
        previous = tokens[index - 1] if index else ""
        weight = 2 if previous in INTENSIFIERS else 1
        negated = previous in NEGATIONS
        if token in POSITIVE:
            # "not good" counts against, "not bad" counts for
            if negated:
                negative += weight
                negative_words.append(token)
            else:
                positive += weight
                positive_words.append(token)
        elif token in NEGATIVE:
            if negated:
                positive += weight
                positive_words.append(token)
            else:
                negative += weight
                negative_words.append(token)
    return positive, negative, positive_words, negative_words


def _mood_body(text):
    positive, negative, positive_words, negative_words = _mood_score(text)
    score = positive - negative
    if not positive_words and not negative_words:
        emoji, label, note = "🌫", "Unreadable", "no familiar words either way"
    else:
        _, emoji, label, note = next(
            (band for band in MOOD_BANDS if score >= band[0]), MOOD_BANDS[-1]
        )
    body = f"{emoji} <b>{label}</b>\n\n"
    body += (
        f"Signal · <code>{score:+d}</code> "
        f"({positive} good, {negative} heavy)\n"
        f"{brand.esc(note)}\n\n"
    )
    matched = list(dict.fromkeys(positive_words + negative_words))[:6]
    if matched:
        body += "Words it noticed · <code>" + brand.esc(", ".join(matched)) + "</code>\n\n"
    else:
        body += "No familiar mood words in that one. Neutral, or a language this lexicon does not know.\n\n"
    body += "<i>Keyword rules, not a real reading.</i>"
    return body


#------------------------------
#Helpers
#------------------------------


def _clean_question(raw):
    text = re.sub(r"\s+", " ", (raw or "")).strip()
    if len(text) > MAX_QUESTION:
        text = text[: MAX_QUESTION - 1].rstrip() + "…"
    return text


async def _mood_text(event, rest):
    """Explicit text, else the replied message's text, else empty."""
    if rest:
        return rest
    if event.is_reply:
        reply = await event.get_reply_message()
        if reply:
            return reply.raw_text or ""
    return ""


#------------------------------
#Commands
#------------------------------


def setup(client, my_id):

    async def _reply(event, body):
        if not await say(event, body, name="oracle", parse_mode="html"):
            log.info("oracle: could not deliver an answer")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!fortune$"))
    async def fortune_cmd(event):
        await _reply(event, _fortune_body())

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!tarot(?:\s+([\s\S]+))?$"))
    async def tarot_cmd(event):
        await _reply(event, _tarot_body(_clean_question(event.pattern_match.group(1))))

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!predict(?:\s+([\s\S]+))?$"))
    async def predict_cmd(event):
        question = _clean_question(event.pattern_match.group(1))
        if not question:
            await _reply(
                event,
                "❌ <b>Ask something first.</b>\n"
                "Usage · <code>!predict will the deploy survive the night?</code>",
            )
            return
        await _reply(event, _predict_body(question))

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!mood(?:\s+([\s\S]*))?$"))
    async def mood_cmd(event):
        text = (await _mood_text(event, event.pattern_match.group(1) or "")).strip()
        if not text:
            await _reply(
                event,
                "❌ <b>Give me something to read.</b>\n"
                "Usage · <code>!mood tired but the tests passed</code> "
                "(or reply to a message).",
            )
            return
        if len(text) > MAX_MOOD_INPUT:
            text = text[:MAX_MOOD_INPUT]
        await _reply(event, _mood_body(text))
