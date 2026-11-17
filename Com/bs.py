# Com/botstatus.py
from telethon import events
from Com.bot import bot_client, BOT_ENABLED

__HELP__ = "!botstatus → Check if the bot is running and connected."
__CATEGORY__ = "Utilities"

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!botstatus$"))
    async def botstatus_cmd(event):
        if not BOT_ENABLED:
            await event.edit("❌ Bot is not enabled (BOT_TOKEN missing).")
            return
        if bot_client is None:
            await event.edit("⏳ Bot client is not yet connected.")
        else:
            try:
                me = await bot_client.get_me()
                await event.edit(f"✅ Bot is running as @{me.username or me.first_name} (ID: {me.id})")
            except Exception as e:
                await event.edit(f"❌ Bot is not responding: {e}")