"""!textfile: turn a message or a reply into a .txt document."""
from telethon import events
import Com.core.tgsend as tgsend
import os
from datetime import datetime

from Com.core import brand
from Com.core.reply import say

__HELP__ = "!textfile <text> or reply → Create a .txt file from text"

os.makedirs("temp", exist_ok=True)


def setup(client, my_id):

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!textfile(?:\s+(.+))?"))
    async def textfile(event):
        try:
            text = event.pattern_match.group(1)
            if not text and event.is_reply:
                reply_msg = await event.get_reply_message()
                text = reply_msg.text or reply_msg.message
            if not text:
                await say(
                    event, "❌ Please provide text or reply to a message.",
                    name="textfile",
                )
                return

            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"temp/textfile_{now}.txt"

            with open(filename, "w", encoding="utf-8") as f:
                f.write(text)

            await client.send_file(await tgsend.peer(event),
                                   filename,
                                   caption="📄 Here is your text file.",
                                   reply_to=event.id)

            os.remove(filename)

        except Exception as e:
            await say(
                event,
                f"❌ <b>Text file failed.</b> {brand.esc(e)}",
                name="textfile",
                parse_mode="html",
            )
