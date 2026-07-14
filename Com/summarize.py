# Com/summarize.py
import os
import aiohttp
from telethon import events

__HELP__ = "!summarize <text> → Summarize the given text using Google Gemini AI"
__CATEGORY__ = "Utilities"

def setup(client, my_id):
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta2/models/text-bison-001:generate"

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!summarize\s+(.+)"))
    async def summarize(event):
        text_to_summarize = event.pattern_match.group(1).strip()

        if not text_to_summarize:
            await event.reply("❌ Please provide text to summarize!")
            return

        msg = await event.reply("⏳ Summarizing...")

        try:
            headers = {
                "Authorization": f"Bearer {GEMINI_API_KEY}",
                "Content-Type": "application/json"
            }

            payload = {
                "prompt": f"Summarize this text:\n{text_to_summarize}",
                "temperature": 0.3,
                "maxOutputTokens": 500
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(GEMINI_URL,
                                        headers=headers,
                                        json=payload) as response:
                    if response.status != 200:
                        text = await response.text()
                        await msg.edit(f"❌ Error: {response.status} - {text}")
                        return

                    data = await response.json()

            summary = data.get("candidates",
                               [{}])[0].get("content", "No summary returned.")
            await msg.edit(f"📝 Summary:\n{summary}")

        except Exception as e:
            await msg.edit(f"❌ Error: {str(e)}")
