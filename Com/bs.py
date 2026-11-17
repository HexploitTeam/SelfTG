# Com/bs.py
from telethon import events
from Com import bot as bot_module

__HELP__ = "!botstatus → Check if the bot is running and connected."
__CATEGORY__ = "Utilities"


def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!botstatus$"))
    async def botstatus_cmd(event):
        # Read the module attributes live. The old `from Com.bot import
        # bot_client` captured None at import time (before start_bot ran), so
        # this command always reported "not yet connected".
        if not bot_module.BOT_ENABLED:
            await event.edit("❌ Bot is not enabled (BOT_TOKEN missing).")
            return

        running_client = bot_module.bot_client
        if running_client is None:
            await event.edit("⏳ Bot client is not yet connected.")
            return

        try:
            me = await running_client.get_me()
            await event.edit(
                f"✅ Bot is running as @{me.username or me.first_name} (ID: {me.id})"
            )
        except Exception as e:
            await event.edit(f"❌ Bot is not responding: {e}")
