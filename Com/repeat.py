"""!repeat: send a message N times."""
from telethon import errors, events

from Com.core import flood
import Com.core.tgsend as tgsend

__HELP__ = (
    "!repeat <N> [text] (reply optional) → Send the same text N times.\n"
    "If text is omitted, it uses the replied message's text.\n"
    "If you reply to a message, the copies are sent as replies to that message.\n"
    "Max N = 20 to avoid spam."
)
__CATEGORY__ = "Utilities"


def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!repeat\s+(\d+)\s*(.*)$"))
    async def repeat_cmd(event):
        try:
            N = int(event.pattern_match.group(1))
            if N < 1:
                await event.edit("❌ Number must be at least 1.")
                return
            if N > 20:
                await event.edit("❌ Maximum allowed is 20 (to avoid spam).")
                return

            text = event.pattern_match.group(2).strip()
            reply_to_id = None

            if text:
                use_text = text
                if event.is_reply:
                    reply_msg = await event.get_reply_message()
                    reply_to_id = reply_msg.id
            else:
                if not event.is_reply:
                    await event.edit("❌ Reply to a message when no text is provided.")
                    return
                reply_msg = await event.get_reply_message()
                if not reply_msg.text:
                    await event.edit("❌ The replied message has no text.")
                    return
                use_text = reply_msg.text
                reply_to_id = reply_msg.id

            await event.delete()

            # Shared gate: a flood ends the series (Com/core/flood.py)
            peer = await tgsend.peer(event)
            sent = 0
            for _ in range(N):
                left = flood.cooldown_left()
                if left:
                    await client.send_message(peer, flood.describe(left))
                    break
                try:
                    await client.send_message(peer, use_text, reply_to=reply_to_id)
                except flood.FLOOD_ERRORS as exc:
                    left = flood.note_flood(exc.seconds)
                    note = (f"⏳ Telegram asked to wait {exc.seconds}s; stopped "
                            f"after {sent} of {N} copies.")
                    if left:
                        note += "\n" + flood.describe(left)
                    await client.send_message(peer, note)
                    break
                sent += 1
                await flood.pace(event.chat_id)
            flood.forget(event.chat_id)

        except ValueError:
            try:
                await event.edit("❌ Invalid number. Use `!repeat <N>`.")
            except:
                pass
        except Exception as e:
            try:
                await client.send_message(await tgsend.peer(event), f"❌ Error: {str(e)}")
            except:
                pass