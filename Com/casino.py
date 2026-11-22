"""Native Telegram dice: one server-side roll per command.

What changed, and why
---------------------
The old module forced outcomes by sending a die, reading its value and deleting
it until the wanted number came up -- up to 100 messages for one `!dice 6`, and
more for `!slot seven`. That is precisely the send pattern Telegram's anti-spam
looks for, and it made the account more detectable for a cosmetic result.

Telegram rolls these dice on its servers; a client cannot choose the value in a
single send. So every command here now sends exactly one `InputMediaDice` and
lets the animation land where it lands. Asking for a value or a slot symbol gets
a clear answer instead of a silently different result, and no reroll loop runs.

The commands keep their names, reply support and owner gating (`from_users`).
"""
import logging

from telethon import errors, events
from telethon.tl.types import InputMediaDice

import Com.core.tgsend as tgsend
from Com.core import brand, flood
from Com.core.reply import say

__HELP__ = (
    "!dice → One native dice roll (🎲).\n"
    "!dart → One dart roll (🎯).\n"
    "!football / !soccer → One football roll (⚽).\n"
    "!basketball / !basket → One basketball roll (🏀).\n"
    "!bowl / !bowling → One bowling roll (🎳).\n"
    "!slot → One slot-machine roll (🎰).\n"
    "\n"
    "Telegram rolls these on its servers, so the value cannot be chosen: a "
    "value or symbol argument is refused instead of being faked by resending. "
    "Reply to a message to roll as a reply."
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.casino")

DICE = {
    "dice": ("🎲", "dice"),
    "dart": ("🎯", "dart"),
    "football": ("⚽", "football"),
    "soccer": ("⚽", "football"),
    "basketball": ("🏀", "basketball"),
    "basket": ("🏀", "basketball"),
    "bowl": ("🎳", "bowl"),
    "bowling": ("🎳", "bowl"),
    "slot": ("🎰", "slot"),
}

FORCE_REMOVED = (
    "❌ <b>Choosing a value is not possible</b>\n"
    "Telegram decides a die's value server-side. The old command resent the "
    "dice up to 100 times and deleted the misses, which is a send pattern that "
    "gets accounts limited, so it is gone.\n"
    "Use <code>!dice</code> for a single roll."
)

SLOT_FORCED = (
    "❌ <b>Choosing a slot symbol is not possible</b>\n"
    "The combination is decided server-side; forcing it needed dozens of "
    "resends, so that path is removed.\n"
    "Use <code>!slot</code> for a single roll."
)


#------------------------------
#One roll
#------------------------------

async def _reply_to_id(event):
    """The replied message's id, or None."""
    if not event.is_reply:
        return None
    reply = await event.get_reply_message()
    return reply.id if reply else None


async def roll(client, event, emoji, command):
    """Send exactly one native die and remove the command message."""
    if flood.is_open():
        await say(
            event,
            f"⏳ <b>Sending is paused</b> · <code>{flood.cooldown_left()}s</code> "
            "left after repeated flood waits.",
            name=command,
            parse_mode="html",
        )
        return

    try:
        reply_to = await _reply_to_id(event)
        await client.send_message(
            await tgsend.peer(event),
            file=InputMediaDice(emoticon=emoji),
            reply_to=reply_to,
        )
    except flood.FLOOD_ERRORS as exc:
        cooldown = flood.note_flood(getattr(exc, "seconds", 0))
        await say(
            event,
            f"⏳ <b>Telegram rate limit</b> · wait <code>{exc.seconds}s</code>."
            + (f"\n<i>Sending paused for {cooldown}s.</i>" if cooldown else ""),
            name=command,
            parse_mode="html",
        )
        return
    except errors.ChatWriteForbiddenError:
        await say(event, "❌ <b>The account cannot post in this chat.</b>",
                  name=command, parse_mode="html")
        return
    except errors.ChatSendMediaForbiddenError:
        await say(event, "❌ <b>Media is not allowed in this chat.</b>",
                  name=command, parse_mode="html")
        return
    except errors.RPCError as exc:
        log.warning("casino: %s failed (%s)", command, type(exc).__name__)
        await say(
            event,
            f"❌ <b>Telegram refused the roll</b> "
            f"(<code>{brand.esc(type(exc).__name__)}</code>).",
            name=command,
            parse_mode="html",
        )
        return
    except Exception as exc:  # noqa: BLE001 - a roll must not crash the client
        log.exception("casino: unexpected failure")
        await say(
            event,
            f"❌ <b>{brand.esc(type(exc).__name__)}</b> · {brand.esc(exc)}",
            name=command,
            parse_mode="html",
        )
        return

    try:
        await event.delete()
    except Exception:  # noqa: BLE001 - the roll is already sent
        log.info("casino: could not delete the command message")


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!dice(?:\s+(\S+))?\s*$"))
    async def dice_cmd(event):
        if event.pattern_match.group(1):
            await say(event, FORCE_REMOVED, name="dice", parse_mode="html")
            return
        await roll(client, event, DICE["dice"][0], "dice")

    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!slot(?:\s+(\S+))?\s*$"))
    async def slot_cmd(event):
        if event.pattern_match.group(1):
            await say(event, SLOT_FORCED, name="slot", parse_mode="html")
            return
        await roll(client, event, DICE["slot"][0], "slot")

    @client.on(events.NewMessage(
        from_users=my_id,
        pattern=r"^!(dart|football|soccer|basketball|basket|bowl|bowling)\s*$"))
    async def sports_cmd(event):
        name = event.pattern_match.group(1).lower()
        emoji, command = DICE[name]
        await roll(client, event, emoji, command)
