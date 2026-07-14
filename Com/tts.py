# Com/tts.py
from telethon import events
from gtts import gTTS
import os

__HELP__ = "!tts <lang> <text> or reply → Convert text to speech"
__CATEGORY__ = "Utilities"

TTS_FOLDER = "mode/tts"
os.makedirs(TTS_FOLDER, exist_ok=True)


def setup(client, my_id):

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!tts\s+(\w+)\s+(.+)"))
    async def tts_handler(event):
        try:
            lang = event.pattern_match.group(1)
            text = event.pattern_match.group(2).strip()

            # If no text, check reply
            if not text and event.is_reply:
                reply_msg = await event.get_reply_message()
                text = reply_msg.text or reply_msg.message or ""

            if not text:
                await event.reply(
                    "❌ Provide text to convert or reply to a message.")
                return

            # Create TTS
            tts = gTTS(text=text, lang=lang)
            filename = os.path.join(TTS_FOLDER, f"tts_{event.id}.mp3")
            tts.save(filename)

            # Send the audio
            await event.reply(file=filename)

            # Cleanup
            os.remove(filename)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
