# Com/translate.py
import asyncio

from telethon import events
from googletrans import Translator

__HELP__ = "!translate <lang_code> <text> → Translate text to the specified language (e.g., !translate en سلام)"
__CATEGORY__ = "Utilities"

def _translate_sync(text, dest):
    """googletrans is synchronous and does a network round trip."""
    return Translator().translate(text, dest=dest)


def setup(client, my_id):

    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!translate\s+(\S+)\s+(.+)"))
    async def translate(event):
        try:
            lang = event.pattern_match.group(1)
            text = event.pattern_match.group(2)

            # Off the event loop: a synchronous request here stalled every
            # other handler for the duration of the call.
            translated = await asyncio.to_thread(_translate_sync, text, lang)
            await event.reply(
                f"🌐 Translated ({translated.src} → {lang}):\n{translated.text}"
            )
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
