"""!panel: put the bot's control panel into the current chat.

The panel is the same screen the bot's /start sends, posted by the bot account so
its buttons are live. Telegram only lets a bot attach an inline keyboard to its
own messages, which is why this has to go through the bot client rather than
`event.reply`.
"""
from telethon import events

from Com.bot import client as bot_module
import Com.core.tgsend as tgsend
from Com.bot import ui as botui
from Com.bot.kit import markup
from Com.core import brand

__HELP__ = (
    "!panel → Send the bot's control panel into this chat.\n"
    "The panel is sent by the bot account, so its buttons work."
)
__CATEGORY__ = "Utilities"


def get_owner_panel():
    """The inline keyboard of the main menu, for callers that only need buttons."""
    return markup(botui.home_screen().rows)


def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!panel$"))
    async def panel_cmd(event):
        # Read live: an import would capture None
        status = bot_module.get_bot_status()
        if bot_module.bot_client is None:
            await event.edit(
                brand.render(f"⚠️ Bot not ready: {status}", "panel"),
                parse_mode="html",
            )
            return

        screen = botui.home_screen()
        try:
            await bot_module.bot_client.send_message(
                await tgsend.peer(event),
                brand.sign(screen.text),
                buttons=get_owner_panel(),
                parse_mode="html",
                reply_to=event.id,
            )
        except Exception as exc:  # noqa: BLE001 - report, do not delete the command
            await event.edit(
                brand.render(f"❌ Failed to send panel: {exc}", "panel"),
                parse_mode="html",
            )
            return
        await event.delete()

    # `!botstatus` lives in Com/bs.py; registering it here too would answer twice
