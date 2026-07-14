# Com/textfile.py
from telethon import events
import os
from datetime import datetime

__HELP__ = "!textfile <text> or reply → Create a .txt file from text"

os.makedirs("temp", exist_ok=True)


def setup(client, my_id):

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!textfile(?:\s+(.+))?"))
    async def textfile(event):
        try:
            # Check if text is given directly or from reply
            text = event.pattern_match.group(1)
            if not text and event.is_reply:
                reply_msg = await event.get_reply_message()
                text = reply_msg.text or reply_msg.message
            if not text:
                await event.reply(
                    "❌ Please provide text or reply to a message.")
                return

            # Create a unique filename
            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"temp/textfile_{now}.txt"

            # Write the text to the file
            with open(filename, "w", encoding="utf-8") as f:
                f.write(text)

            # Send the file
            await client.send_file(event.chat_id,
                                   filename,
                                   caption="📄 Here is your text file.",
                                   reply_to=event.id)

            # Optional: delete local file after sending
            os.remove(filename)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
