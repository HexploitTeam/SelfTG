# Com/translate.py
from telethon import events
from googletrans import Translator

__HELP__ = "!translate <lang_code> <text> → Translate text to the specified language (e.g., !translate en سلام)"
__CATEGORY__ = "Utilities"

def setup(client, my_id):
    translator = Translator()

    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!translate\s+(\S+)\s+(.+)"))
    async def translate(event):
        try:
            lang = event.pattern_match.group(1)
            text = event.pattern_match.group(2)

            translated = translator.translate(text, dest=lang)
            await event.reply(
                f"🌐 Translated ({translated.src} → {lang}):\n{translated.text}"
            )
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
