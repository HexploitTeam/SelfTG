"""!botstatus: report whether the helper bot account is connected."""
from telethon import events
from Com.bot import client as bot_module

from Com.core import brand
from Com.core.reply import say

__HELP__ = "!botstatus → Check if the bot is running and connected."
__CATEGORY__ = "Utilities"


def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!botstatus$"))
    async def botstatus_cmd(event):
        # Read live: a module-level import captured None before start_bot
        if not bot_module.BOT_ENABLED:
            await say(
                event, "❌ Bot is not enabled (BOT_TOKEN missing).", name="botstatus"
            )
            return

        running_client = bot_module.bot_client
        if running_client is None:
            await say(event, "⏳ Bot client is not yet connected.", name="botstatus")
            return

        try:
            me = await running_client.get_me()
            handle = f"@{me.username}" if me.username else me.first_name
            await say(
                event,
                f"✅ <b>Bot is running</b> as {brand.esc(handle)} "
                f"(ID <code>{me.id}</code>)",
                name="botstatus",
                parse_mode="html",
            )
        except Exception as e:
            await say(
                event,
                f"❌ <b>Bot is not responding.</b> {brand.esc(e)}",
                name="botstatus",
                parse_mode="html",
            )
