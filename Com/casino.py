"""Animated dice, football, basketball, dart and slot commands."""
import asyncio
from telethon import events
from telethon.tl.types import InputMediaDice
import Com.core.tgsend as tgsend
from Com.core import brand
from Com.core.reply import say

__HELP__ = (
    "!dice              → Random animated dice.\n"
    "!dice <1-6>        → Forced dice (⚠️ casino bots detect).\n"
    "!football          → Football that always scores a goal (value 5).\n"
    "!basketball        → Basketball that always scores (value 5).\n"
    "!dart              → Dart that always hits the bullseye (value 6).\n"
    "!slot              → Random slot machine.\n"
    "!slot <symbol>     → Slot with a specific combination (bar, lemon, grape, seven).\n"
    "!slot <1-64>       → Slot with a raw Telegram value.\n"
    "  Symbols: bar, lemon, grape(s), seven.\n"
    "  Example: !slot seven → gives three sevens.\n"
    "All commands support reply – the result will be a reply to that message."
)
__CATEGORY__ = "Utilities"

# Telegram's slot values
SLOT_MAP = {
    "bar": 1,
    "grape": 22,
    "grapes": 22,
    "lemon": 43,
    "seven": 64,
}
REVERSE_SLOT = {v: k for k, v in SLOT_MAP.items()}

#------------------------------
#Dice helper
#------------------------------

async def force_dice(client, peer, emoji, target_value, reply_to, command):
    """Reroll until we get the target value (fast deletion).

    `peer` must be an input peer (see Com/core/tgsend.py): the game message, the
    lookup of its rolled value and the cleanup all address the same chat, and a
    bare id is not resolvable on a fresh StringSession.
    """
    for _ in range(100):  # increased to 100
        msg = await client.send_message(
            peer,
            file=InputMediaDice(emoticon=emoji),
            reply_to=reply_to
        )
        # Usually already on the sent message
        value = None
        if msg.media:
            value = getattr(msg.media, 'value', None)
        if value is None:
            await asyncio.sleep(0.01)
            msg = await client.get_messages(peer, ids=msg.id)
            if msg.media:
                value = getattr(msg.media, 'value', None)
        if value == target_value:
            return
        try:
            await client.delete_messages(peer, [msg.id])
        except Exception:
            pass
    # Fallback (should never happen)
    await client.send_message(
        peer, brand.sign(f"{emoji} <b>{target_value}</b>", command),
        reply_to=reply_to, parse_mode="html")

#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    # !dice
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!dice(?:\s+([1-6]))?$"))
    async def dice_cmd(event):
        try:
            arg = event.pattern_match.group(1)
            reply_to = None
            if event.is_reply:
                reply_msg = await event.get_reply_message()
                reply_to = reply_msg.id

            if arg is None:
                await event.delete()
                await client.send_message(await tgsend.peer(event),
                    file=InputMediaDice(emoticon="🎲"),
                    reply_to=reply_to
                )
                return

            target = int(arg)
            if target < 1 or target > 6:
                await say(event, "❌ Dice value must be 1–6.", name="dice")
                return
            await event.delete()
            await force_dice(client, await tgsend.peer(event), "🎲", target,
                             reply_to, "dice")

        except Exception as e:
            try:
                await client.send_message(
                    await tgsend.peer(event),
                    brand.sign(f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                               "dice"),
                    parse_mode="html")
            except Exception:
                pass

    # !football
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!football$"))
    async def football_cmd(event):
        reply_to = None
        if event.is_reply:
            reply_msg = await event.get_reply_message()
            reply_to = reply_msg.id
        await event.delete()
        await force_dice(client, await tgsend.peer(event), "⚽", 5, reply_to,
                         "football")

    # !basketball
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!basketball$"))
    async def basketball_cmd(event):
        reply_to = None
        if event.is_reply:
            reply_msg = await event.get_reply_message()
            reply_to = reply_msg.id
        await event.delete()
        await force_dice(client, await tgsend.peer(event), "🏀", 5, reply_to,
                         "basketball")

    # !dart
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!dart$"))
    async def dart_cmd(event):
        reply_to = None
        if event.is_reply:
            reply_msg = await event.get_reply_message()
            reply_to = reply_msg.id
        await event.delete()
        await force_dice(client, await tgsend.peer(event), "🎯", 6, reply_to,
                         "dart")

    # !slot
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!slot(?:\s+(\d+|[a-zA-Z]+))?$"))
    async def slot_cmd(event):
        try:
            arg = event.pattern_match.group(1)
            reply_to = None
            if event.is_reply:
                reply_msg = await event.get_reply_message()
                reply_to = reply_msg.id

            if arg is None:
                await event.delete()
                await client.send_message(await tgsend.peer(event),
                    file=InputMediaDice(emoticon="🎰"),
                    reply_to=reply_to
                )
                return

            if arg.isdigit():
                target = int(arg)
                if target < 1 or target > 64:
                    await say(event,
                              "❌ Slot value must be 1–64 "
                              "(see <code>!help slot</code>).",
                              name="slot", parse_mode="html")
                    return
            else:
                sym = arg.lower()
                if sym not in SLOT_MAP:
                    await say(event,
                              "❌ Unknown symbol. Choose from · "
                              f"<code>{', '.join(SLOT_MAP.keys())}</code>",
                              name="slot", parse_mode="html")
                    return
                target = SLOT_MAP[sym]

            await event.delete()
            await force_dice(client, await tgsend.peer(event), "🎰", target,
                             reply_to, "slot")

        except Exception as e:
            try:
                await client.send_message(
                    await tgsend.peer(event),
                    brand.sign(f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                               "slot"),
                    parse_mode="html")
            except Exception:
                pass