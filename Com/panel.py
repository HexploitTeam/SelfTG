# Com/panel.py
import asyncio
from telethon import events
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback, KeyboardButtonRow

from Com.bot import bot_client, BOT_ENABLED, get_bot_status

__HELP__ = (
    "!panel → Send the bot's inline panel (owner menu) in this chat.\n"
    "The panel is sent by the bot account, so buttons are interactive.\n"
    "!botstatus → Check if the bot is running and connected."
)
__CATEGORY__ = "Utilities"

def get_owner_panel():
    return ReplyInlineMarkup([
        KeyboardButtonRow([KeyboardButtonCallback("📊 Stats", b"stats")]),
        KeyboardButtonRow([KeyboardButtonCallback("👿 Enemies", b"enemies")]),
        KeyboardButtonRow([KeyboardButtonCallback("⚠️ Warns", b"warns")]),
        KeyboardButtonRow([KeyboardButtonCallback("🔇 Mutes", b"mutes")]),
        KeyboardButtonRow([KeyboardButtonCallback("📝 Texts", b"texts")]),
        KeyboardButtonRow([KeyboardButtonCallback("⚙️ Admin Panel", b"admin")]),
    ])

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!panel$"))
    async def panel_cmd(event):
        status = get_bot_status()
        if "❌" in status or "⏳" in status:
            await event.edit(f"⚠️ Bot not ready: {status}\nTry again in a moment.")
            return

        if bot_client is None:
            await event.edit("⏳ Bot client is starting, please wait...")
            for _ in range(10):
                await asyncio.sleep(1)
                if bot_client is not None:
                    break
            if bot_client is None:
                await event.edit("⏳ Bot still not ready. Check token or try restarting.")
                return

        try:
            await bot_client.send_message(
                event.chat_id,
                "🤖 **Owner Menu**\nUse the buttons below.",
                buttons=get_owner_panel(),
                reply_to=event.id
            )
        except Exception as e:
            await event.edit(f"❌ Failed to send panel: {e}")
            return
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!botstatus$"))
    async def botstatus_cmd(event):
        status = get_bot_status()
        await event.edit(f"**Bot Status**\n{status}")
        await event.delete()