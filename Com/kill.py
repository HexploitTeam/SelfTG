"""!kill: send N random lines from the main text list."""
import os
import json
import random
from telethon import errors, events

from Com.core import brand, flood
from Com.core.reply import say
import Com.core.tgsend as tgsend

__HELP__ = (
    "!kill <N> [@username] (optional reply) → Reply with N random lines from the main list.\n"
    "Each line is sent as a separate message (or reply if you reply to a message).\n"
    "No repeats. If @username is provided, each starts with '@username' on a new line.\n"
    "Example: !kill 5 @ImSunpr\n"
    "The command is deleted immediately."
)
__CATEGORY__ = "Utilities"

BASE_DIR = "mode"
ELIST_FILE = os.path.join(BASE_DIR, "EList.json")

def load_list():
    if not os.path.exists(ELIST_FILE):
        return []
    try:
        with open(ELIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!kill\s+(\d+)(?:\s+@?(\w+))?$"))
    async def kill_cmd(event):
        try:
            N = int(event.pattern_match.group(1))
            if N < 1:
                await say(event, "❌ Number must be at least 1.", name="kill")
                return

            username = event.pattern_match.group(2)  # may be None
            if username and not username.startswith("@"):
                username = "@" + username

            lines = load_list()
            if not lines:
                await say(
                    event,
                    "❌ <b>The main list is empty.</b> Add texts with "
                    "<code>!enemy list add</code> or <code>!enemy clist</code>.",
                    name="kill",
                    parse_mode="html",
                )
                return

            warn = False
            if N > len(lines):
                N = len(lines)
                warn = True

            selected = random.sample(lines, N)

            reply_msg = None
            if event.is_reply:
                reply_msg = await event.get_reply_message()

            try:
                await event.delete()
            except Exception:
                pass

            peer = await tgsend.peer(event)
            sent = 0
            for item in selected:
                # One series, one gate: jittered gaps, flood stops the loop
                left = flood.cooldown_left()
                if left:
                    await client.send_message(peer, flood.describe(left))
                    break

                text = item["text"]
                msg = f"{username}\n{text}" if username else text
                try:
                    await client.send_message(
                        peer, msg,
                        reply_to=reply_msg.id if reply_msg else None,
                    )
                except flood.FLOOD_ERRORS as exc:
                    left = flood.note_flood(exc.seconds)
                    note = (
                        f"⏳ <b>Telegram asked to wait</b> "
                        f"<code>{exc.seconds}s</code>; stopped after "
                        f"<code>{sent}</code> of <code>{N}</code> messages."
                    )
                    if left:
                        note += "\n" + brand.esc(flood.describe(left))
                    await client.send_message(
                        peer, brand.sign(note, "kill"), parse_mode="html"
                    )
                    break
                sent += 1
                await flood.pace(event.chat_id)
            flood.forget(event.chat_id)
            if warn:
                await client.send_message(
                    await tgsend.peer(event),
                    brand.sign(
                        f"⚠️ <b>Only {len(lines)} texts available</b>, used all of "
                        "them.",
                        "kill",
                    ),
                    parse_mode="html",
                    reply_to=reply_msg.id if reply_msg else None,
                )

        except ValueError:
            await say(
                event,
                "❌ Invalid number. Use "
                "<code>!kill &lt;N&gt; [@username]</code>.",
                name="kill",
                parse_mode="html",
            )
        except Exception as e:
            try:
                await client.send_message(
                    await tgsend.peer(event),
                    brand.sign(f"❌ <b>Kill failed.</b> {brand.esc(e)}", "kill"),
                    parse_mode="html",
                )
            except:
                pass