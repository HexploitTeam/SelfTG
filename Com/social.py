"""`!roast`, `!compliment`, `!wyr` -- banter with no network.

The lines are hand-written templates, not generated text: a roast that is
actually funny is cheaper to write once than to approximate with a model, and a
template cannot invent a slur. The only variable is the optional target, which
is escaped before it reaches the message.

Keep the roasts absurd rather than personal. Nothing here touches appearance,
family, identity, or anything a real person cannot laugh off; that is the line
between a joke and a report.
"""
import logging
import random
import re

from telethon import events

from Com.core import brand
from Com.core.reply import say

__HELP__ = (
    "!roast [target] → A harmless roast, optionally aimed at someone\n"
    "!compliment [target] → The opposite, for balance\n"
    "!wyr → Would you rather, from a local question bank"
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.social")

MAX_TARGET = 40

_RNG = random.SystemRandom()

ROASTS = (
    "You have the charisma of a dial tone.",
    "Your confidence is writing cheques your calendar cannot cash.",
    "You are the human equivalent of a loading screen that never reaches 100%.",
    "Your ideas are excellent; your follow-through is on holiday.",
    "You bring the energy of a Monday morning to every group chat.",
    "You have never met a shortcut you could not turn into a detour.",
    "Your search history is forty percent 'how to' and sixty percent 'why is'.",
    "You are one browser tab away from total collapse.",
    "Your typing speed is impressive for someone who proofreads never.",
    "You have the organisational skills of a sock drawer in a storm.",
    "Your plants would describe you as 'ambitious'.",
    "You are the reason the phrase 'quick question' needs a trigger warning.",
    "Your phone battery treats your plans as a rumour.",
    "You could start a fire with the friction of your last three excuses.",
    "Your playlist has one song and it is a hold message.",
    "You are the plot twist nobody ordered.",
    "Your plans have plans. None of them include a first step.",
    "You make 'almost finished' feel like a lifestyle.",
    "Your remaining willpower is held together by cold coffee.",
    "You are proof that a deadline is a suggestion if you are loud enough.",
)

COMPLIMENTS = (
    "You explain difficult things like someone who actually wants you to understand.",
    "Your presence lowers the temperature of a tense room.",
    "You notice the small effort nobody else thanks people for.",
    "You are the person others relax around.",
    "Your laugh makes bad news easier to carry.",
    "You have a talent for making ordinary days feel intentional.",
    "You ask the question everyone else was too polite to ask.",
    "Your taste is specific, and that is the best kind.",
    "You make people feel included without making a show of it.",
    "You are better at starting over than most people are at starting.",
    "Your kindness has edges, which is why it holds.",
    "You remember the details people only mention once.",
    "You are proof that quiet competence is a personality.",
    "Your curiosity is contagious in the best way.",
    "You handle being wrong better than most people handle being right.",
    "You bring the exact thing a room did not know it needed.",
    "You make hard conversations feel survivable.",
    "Your standards are high and your patience is higher.",
    "You are the calm in a group chat that does not deserve it.",
    "You have a way of making effort look effortless, which is unfair and lovely.",
)

# (option A, option B) -- both mundane enough to argue about
WOULD_YOU_RATHER = (
    ("have a pet dragon", "have a pet kraken"),
    ("never lose your keys again", "never lose your phone again"),
    ("always be ten minutes early", "always be exactly on time"),
    ("read every language", "play every instrument"),
    ("live without coffee", "live without tea"),
    ("have unlimited free flights", "have unlimited free hotels"),
    ("remember every dream", "never dream again"),
    ("be able to pause time for ten minutes a day", "rewind one hour once a week"),
    ("always have the perfect comeback", "always know when to stay quiet"),
    ("never wait in a queue again", "never sit in traffic again"),
    ("have a personal chef", "have a personal trainer"),
    ("know how every film ends", "forget every spoiler you have ever read"),
    ("work four days a week for the same pay", "work five days and retire five years early"),
    ("have a house with a library", "have a house with a workshop"),
    ("only ever eat your favourite meal", "never eat the same meal twice"),
    ("be famous for something silly", "be unknown and extremely comfortable"),
    ("have perfect memory", "have perfect judgement"),
    ("live by the sea", "live in the mountains"),
    ("always win board games", "always win arguments"),
    ("get one extra hour every morning", "get one extra hour every night"),
    ("have a robot that cleans", "have a robot that cooks"),
    ("never be cold again", "never be too hot again"),
    ("speak to animals for a day", "speak every human language for a week"),
    ("have a secret passage in your home", "have a rooftop garden"),
    ("know what everyone really thinks", "never wonder again"),
)


def _target(raw):
    """A display name for a line, or an empty string when none was given."""
    text = re.sub(r"\s+", " ", (raw or "")).strip()
    text = text.lstrip("@")[:MAX_TARGET].strip()
    return text


def _line_body(title, emoji, lines, target):
    line = _RNG.choice(lines)
    if target:
        # The templates are second person, so the name becomes a vocative
        line = f"{target}, {line[0].lower()}{line[1:]}"
    return f"{emoji} <b>{title}</b>\n\n<blockquote>{brand.esc(line)}</blockquote>"


def _wyr_body():
    first, second = _RNG.choice(WOULD_YOU_RATHER)
    return (
        "🤔 <b>Would you rather</b>\n\n"
        f"<b>A</b> · {brand.esc(first)}\n"
        f"<b>B</b> · {brand.esc(second)}\n\n"
        "<i>Pick one. No takebacks.</i>"
    )


def setup(client, my_id):

    async def _reply(event, body):
        if not await say(event, body, name="social", parse_mode="html"):
            log.info("social: could not deliver an answer")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!roast(?:\s+([\s\S]+))?$"))
    async def roast_cmd(event):
        target = _target(event.pattern_match.group(1))
        await _reply(event, _line_body("Roast", "🔥", ROASTS, target))

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!compliment(?:\s+([\s\S]+))?$"))
    async def compliment_cmd(event):
        target = _target(event.pattern_match.group(1))
        await _reply(event, _line_body("Compliment", "🌿", COMPLIMENTS, target))

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!wyr$"))
    async def wyr_cmd(event):
        await _reply(event, _wyr_body())
