"""`!games` -- local chat games with no external service.

Why local
---------
None of these need an API: the answers, the dice notation and the guessing game
are logic and a random source. A free HTTP endpoint would add a failure mode
without adding a feature, so the only I/O here is the existing JSON store.

`!guess` is the one stateful game. Its state lives in ``mode/games.json`` (one
entry per chat, pruned after a day) so a Repl restart does not strand a round
mid-way. If that file cannot be written the game still plays and says the round
will not survive a restart -- no silent loss, no crash.

Every command is owner-only through ``from_users=my_id``, like the rest of the
self-bot. Each answer is one message; nothing retries or polls.
"""
import logging
import random
import re
import time

from telethon import events

from Com.core import brand
from Com.core.reply import say
from Com.core.storage import load_json, save_json

__HELP__ = (
    "!8ball <question> → Magic 8-ball answer\n"
    "!coinflip [heads|tails] → Flip a coin, optionally calling it\n"
    "!rps <rock|paper|scissors> → Rock, paper, scissors against the bot\n"
    "!roll <notation> → Dice roll: 2d6, d20, 3d8+2, or a number for one die\n"
    "!guess → Start a 1–100 guessing game in this chat\n"
    "!guess <number> → Make a guess (8 tries)\n"
    "!guess stop → Give up and reveal the number\n"
    "!guess new → Restart the round"
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.games")

GAMES_FILE = "mode/games.json"
GUESS_MIN = 1
GUESS_MAX = 100
GUESS_TRIES = 8
GUESS_TTL = 24 * 3600
MAX_ROLL_DICE = 20
MAX_ROLL_SIDES = 1000
MAX_MODIFIER = 1000

_RNG = random.SystemRandom()

EIGHT_BALL = (
    "It is certain.", "Without a doubt.", "Yes, definitely.",
    "You may rely on it.", "Most likely.", "Outlook good.", "Yes.",
    "Signs point to yes.", "Reply hazy, try again.",
    "Ask again later.", "Better not tell you now.",
    "Cannot predict now.", "Concentrate and ask again.",
    "Don't count on it.", "My reply is no.", "My sources say no.",
    "Outlook not so good.", "Very doubtful.",
)

RPS = {
    "rock": ("✊", "Rock"),
    "paper": ("✋", "Paper"),
    "scissors": ("✌️", "Scissors"),
}
RPS_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}

_PLAIN_DIE = re.compile(r"^(\d{1,4})$")
_DICE_NOTATION = re.compile(r"^(\d{0,2})d(\d{1,4})([+-]\d{1,3})?$", re.IGNORECASE)


#------------------------------
#Guess state
#------------------------------

def _load_games():
    data = load_json(GAMES_FILE, {})
    chats = data.get("chats") if isinstance(data, dict) else None
    return chats if isinstance(chats, dict) else {}


def _save_games(chats):
    try:
        save_json(GAMES_FILE, {"chats": chats})
        return True
    except Exception:  # noqa: BLE001 - a full disk must not end the game
        log.exception("games: could not save guess state")
        return False


def _prune(chats, now):
    """Drop rounds older than a day, or entries that no longer parse."""
    for key in list(chats):
        entry = chats.get(key)
        if not isinstance(entry, dict):
            chats.pop(key, None)
            continue
        try:
            started = float(entry.get("started") or 0)
        except (TypeError, ValueError):
            chats.pop(key, None)
            continue
        if now - started > GUESS_TTL:
            chats.pop(key, None)


def _valid_round(state):
    if not isinstance(state, dict):
        return False
    secret = state.get("secret")
    return isinstance(secret, int) and GUESS_MIN <= secret <= GUESS_MAX


#------------------------------
#Dice notation
#------------------------------

def parse_roll(argument):
    """Return (count, sides, modifier); raise ValueError with a reason."""
    argument = (argument or "").strip().lower()
    plain = _PLAIN_DIE.match(argument)
    if plain:
        count, sides, modifier = 1, int(plain.group(1)), 0
    else:
        match = _DICE_NOTATION.match(argument)
        if not match:
            raise ValueError("use 2d6, d20, 3d8+2, or a single number")
        count = int(match.group(1) or 1)
        sides = int(match.group(2))
        modifier = int(match.group(3) or 0)
    if not 1 <= count <= MAX_ROLL_DICE:
        raise ValueError(f"1–{MAX_ROLL_DICE} dice per roll")
    if not 2 <= sides <= MAX_ROLL_SIDES:
        raise ValueError(f"a die needs 2–{MAX_ROLL_SIDES} sides")
    if abs(modifier) > MAX_MODIFIER:
        raise ValueError(f"modifier must be within ±{MAX_MODIFIER}")
    return count, sides, modifier


def render_roll(notation, rolls, modifier):
    total = sum(rolls) + modifier
    if len(rolls) == 1 and not modifier:
        return (f"🎲 <b>Roll · {brand.esc(notation)}</b>\n"
                f"<code>{rolls[0]}</code>")
    parts = " + ".join(str(roll) for roll in rolls)
    if modifier:
        parts += f" {'+' if modifier > 0 else '−'} {abs(modifier)}"
    return (
        f"🎲 <b>Roll · {brand.esc(notation)}</b>\n"
        f"<code>{brand.esc(parts)}</code> = <b>{total}</b>"
    )


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!8ball(?:\s+([\s\S]+))?$"))
    async def eight_ball(event):
        question = (event.pattern_match.group(1) or "").strip()
        if not question:
            await say(
                event,
                "❌ Usage · <code>!8ball &lt;question&gt;</code>",
                name="8ball",
                parse_mode="html",
            )
            return
        answer = _RNG.choice(EIGHT_BALL)
        await say(
            event,
            f"🎱 <b>Magic 8-ball</b>\n"
            f"<blockquote>{brand.esc(question[:200])}</blockquote>\n"
            f"{brand.esc(answer)}",
            name="8ball",
            parse_mode="html",
        )

    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!(?:coinflip|coin)(?:\s+(\S+))?$"))
    async def coinflip(event):
        guess = (event.pattern_match.group(1) or "").strip().lower()
        if guess in ("h", "head"):
            guess = "heads"
        if guess in ("t", "tail"):
            guess = "tails"
        if guess and guess not in ("heads", "tails"):
            await say(
                event,
                "❌ Call it <code>heads</code> or <code>tails</code>.",
                name="coinflip",
                parse_mode="html",
            )
            return

        result = _RNG.choice(("heads", "tails"))
        lines = ["🪙 <b>Coin flip</b>", f"<b>Result</b> · {result.title()}"]
        if guess:
            if guess == result:
                lines.append(f"✅ <b>You called it.</b>")
            else:
                lines.append(f"❌ <b>You called {brand.esc(guess)}.</b>")
        await say(event, "\n".join(lines), name="coinflip", parse_mode="html")

    @client.on(events.NewMessage(
        from_users=my_id, pattern=r"^!(?:rps|rockpaperscissors)(?:\s+(\S+))?$"))
    async def rps(event):
        choice = (event.pattern_match.group(1) or "").strip().lower()
        if choice not in RPS:
            await say(
                event,
                "❌ Pick <code>rock</code>, <code>paper</code> or "
                "<code>scissors</code>.",
                name="rps",
                parse_mode="html",
            )
            return

        mine = _RNG.choice(tuple(RPS))
        my_emoji, my_label = RPS[mine]
        your_emoji, your_label = RPS[choice]
        if mine == choice:
            outcome = "🤝 <b>Draw.</b>"
        elif RPS_BEATS[choice] == mine:
            outcome = "✅ <b>You win.</b>"
        else:
            outcome = "❌ <b>I win.</b>"
        await say(
            event,
            f"{your_emoji} <b>Rock, paper, scissors</b>\n"
            f"<b>You</b> · {your_label}\n"
            f"<b>Me</b> · {my_emoji} {my_label}\n"
            f"{outcome}",
            name="rps",
            parse_mode="html",
        )

    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!roll(?:\s+(\S+))?$"))
    async def roll(event):
        argument = (event.pattern_match.group(1) or "").strip()
        if not argument:
            await say(
                event,
                "❌ Usage · <code>!roll 2d6</code>, <code>!roll d20</code> or "
                "<code>!roll 3d8+2</code>.",
                name="roll",
                parse_mode="html",
            )
            return
        try:
            count, sides, modifier = parse_roll(argument)
        except ValueError as exc:
            await say(
                event,
                f"❌ <b>Bad dice notation.</b> {brand.esc(exc)}",
                name="roll",
                parse_mode="html",
            )
            return

        rolls = [_RNG.randint(1, sides) for _ in range(count)]
        notation = f"{count}d{sides}" + (
            f"{'+' if modifier > 0 else ''}{modifier}" if modifier else "")
        await say(event, render_roll(notation, rolls, modifier),
                  name="roll", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!guess(?:\s+(\S+))?$"))
    async def guess(event):
        argument = (event.pattern_match.group(1) or "").strip().lower()
        now = time.time()
        chats = _load_games()
        _prune(chats, now)
        key = str(event.chat_id)
        state = chats.get(key)
        if state is not None and not _valid_round(state):
            chats.pop(key, None)
            state = None

        if argument in ("stop", "quit", "giveup", "give-up", "end"):
            if state is None:
                await say(event, "❌ No guessing game is running here.",
                          name="guess", parse_mode="html")
                return
            secret = state["secret"]
            chats.pop(key, None)
            _save_games(chats)
            await say(
                event,
                f"🏳️ <b>Game over</b> · the number was "
                f"<code>{secret}</code> after "
                f"<code>{state.get('attempts', 0)}</code> guess(es).",
                name="guess",
                parse_mode="html",
            )
            return

        if argument in ("new", "start", "restart"):
            await _start_round(event, chats, key, now)
            return

        if state is None:
            if argument:
                await say(
                    event,
                    "❌ <b>No game running.</b> Start one with "
                    "<code>!guess</code>.",
                    name="guess",
                    parse_mode="html",
                )
                return
            await _start_round(event, chats, key, now)
            return

        if not argument:
            await say(
                event,
                f"🎯 <b>Guess the number</b> · "
                f"<code>{state.get('low', GUESS_MIN)}–"
                f"{state.get('high', GUESS_MAX)}</code>\n"
                f"<b>Tries left</b> · "
                f"<code>{GUESS_TRIES - int(state.get('attempts', 0))}</code>\n"
                "Make a guess with <code>!guess &lt;number&gt;</code>.",
                name="guess",
                parse_mode="html",
            )
            return

        try:
            number = int(argument)
        except ValueError:
            await say(
                event,
                "❌ Guess with a number: <code>!guess 42</code>, or stop with "
                "<code>!guess stop</code>.",
                name="guess",
                parse_mode="html",
            )
            return
        if not GUESS_MIN <= number <= GUESS_MAX:
            await say(
                event,
                f"❌ Pick a number between {GUESS_MIN} and {GUESS_MAX}.",
                name="guess",
                parse_mode="html",
            )
            return

        secret = state["secret"]
        attempts = int(state.get("attempts", 0)) + 1
        low = int(state.get("low", GUESS_MIN))
        high = int(state.get("high", GUESS_MAX))

        if number == secret:
            chats.pop(key, None)
            _save_games(chats)
            await say(
                event,
                f"🎉 <b>Correct</b> · <code>{secret}</code> in "
                f"<code>{attempts}</code> guess(es).",
                name="guess",
                parse_mode="html",
            )
            return

        if number < secret:
            low = max(low, number + 1)
            hint = "📈 <b>Higher.</b>"
        else:
            high = min(high, number - 1)
            hint = "📉 <b>Lower.</b>"
        state.update({"attempts": attempts, "low": low, "high": high,
                      "started": state.get("started", now)})

        if attempts >= GUESS_TRIES:
            chats.pop(key, None)
            _save_games(chats)
            await say(
                event,
                f"❌ <b>Out of tries.</b> {hint}\n"
                f"<b>The number was</b> · <code>{secret}</code>",
                name="guess",
                parse_mode="html",
            )
            return

        chats[key] = state
        saved = _save_games(chats)
        text = (
            f"{hint}\n"
            f"<b>Range</b> · <code>{low}–{high}</code>\n"
            f"<b>Tries left</b> · <code>{GUESS_TRIES - attempts}</code>"
        )
        if not saved:
            text += "\n<i>State could not be saved; this round ends on restart.</i>"
        await say(event, text, name="guess", parse_mode="html")

    async def _start_round(event, chats, key, now):
        secret = _RNG.randint(GUESS_MIN, GUESS_MAX)
        chats[key] = {
            "secret": secret,
            "attempts": 0,
            "low": GUESS_MIN,
            "high": GUESS_MAX,
            "started": now,
        }
        saved = _save_games(chats)
        text = (
            f"🎯 <b>Guess the number</b> · <code>{GUESS_MIN}–{GUESS_MAX}</code>\n"
            f"<b>Tries</b> · <code>{GUESS_TRIES}</code>\n"
            "Guess with <code>!guess &lt;number&gt;</code>; give up with "
            "<code>!guess stop</code>."
        )
        if not saved:
            text += "\n<i>State could not be saved; this round ends on restart.</i>"
        await say(event, text, name="guess", parse_mode="html")
