# Com/monitor.py
from telethon import events
import os
import json

__HELP__ = "!monitor set <keyword> → Watch for keywords and alert you\n!monitor remove <keyword> → Remove a keyword from monitoring\n!monitor list → Show all monitored keywords"
__CATEGORY__ = "Utilities"

DATA_FILE = "mode/monitor.json"
os.makedirs("mode", exist_ok=True)


def setup(client, my_id):

    # -----------------------
    # Load saved keywords
    # -----------------------
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                monitored_keywords = json.load(f)
        except:
            monitored_keywords = {}
    else:
        monitored_keywords = {}

    def save_data():
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(monitored_keywords, f, indent=2)

    # -----------------------
    # Set a keyword
    # -----------------------
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!monitor set (.+)"))
    async def monitor_set(event):
        keyword = event.pattern_match.group(1).strip().lower()
        chat_id = str(event.chat_id)
        if chat_id not in monitored_keywords:
            monitored_keywords[chat_id] = []
        if keyword in monitored_keywords[chat_id]:
            await event.reply(
                f"⚠️ Keyword '{keyword}' is already being monitored in this chat."
            )
            return
        monitored_keywords[chat_id].append(keyword)
        save_data()
        await event.reply(
            f"✅ Now monitoring keyword: '{keyword}' in this chat.")

    # -----------------------
    # Remove a keyword
    # -----------------------
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!monitor remove (.+)"))
    async def monitor_remove(event):
        keyword = event.pattern_match.group(1).strip().lower()
        chat_id = str(event.chat_id)
        if chat_id not in monitored_keywords or keyword not in monitored_keywords[
                chat_id]:
            await event.reply(
                f"⚠️ Keyword '{keyword}' is not monitored in this chat.")
            return
        monitored_keywords[chat_id].remove(keyword)
        save_data()
        await event.reply(f"❌ Removed keyword: '{keyword}' from monitoring.")

    # -----------------------
    # List monitored keywords
    # -----------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!monitor list$"))
    async def monitor_list(event):
        chat_id = str(event.chat_id)
        keywords = monitored_keywords.get(chat_id, [])
        if not keywords:
            await event.reply(
                "ℹ️ No keywords are currently monitored in this chat.")
            return
        await event.reply("📝 Monitored keywords:\n" +
                          "\n".join(f"• {k}" for k in keywords))

    # -----------------------
    # Alert on keyword match
    # -----------------------
    @client.on(events.NewMessage())
    async def keyword_alert(event):
        chat_id = str(event.chat_id)
        if chat_id not in monitored_keywords:
            return
        text = (event.raw_text or "").lower()
        for kw in monitored_keywords[chat_id]:
            if kw in text:
                try:
                    await client.send_message(
                        my_id,
                        f"⚡ Keyword alert!\nChat: {event.chat.title if hasattr(event.chat, 'title') else event.chat_id}\nUser: {getattr(await event.get_sender(), 'first_name', 'Unknown')}\nKeyword: '{kw}'\nMessage: {event.text}",
                        reply_to=event.id)
                except Exception as e:
                    print(f"Failed to alert keyword '{kw}': {e}")
                break  # only alert once per message
