"""!kill: send N random lines from the main text list."""
import os
import json
import random
import asyncio
from telethon import events
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
                await event.edit("❌ Number must be at least 1.")
                return

            username = event.pattern_match.group(2)  # may be None
            if username and not username.startswith("@"):
                username = "@" + username

            lines = load_list()
            if not lines:
                await event.edit("❌ The main list is empty. Add texts with `!enemy list add` or `!enemy clist`.")
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

            for item in selected:
                text = item["text"]
                if username:
                    msg = f"{username}\n{text}"
                else:
                    msg = text
                await client.send_message(await tgsend.peer(event),
                    msg,
                    reply_to=reply_msg.id if reply_msg else None
                )
                await asyncio.sleep(1)  # slight delay to avoid rate limits

            if warn:
                await client.send_message(await tgsend.peer(event),
                    f"⚠️ Only {len(lines)} texts available, used all of them.",
                    reply_to=reply_msg.id if reply_msg else None
                )

        except ValueError:
            await event.edit("❌ Invalid number. Use `!kill <N> [@username]`.")
        except Exception as e:
            try:
                await client.send_message(await tgsend.peer(event), f"❌ Error: {str(e)}")
            except:
                pass