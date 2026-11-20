"""!inline: send a message with inline buttons through the helper bot."""
import asyncio
import re
from telethon import events
from telethon.tl.types import KeyboardButtonCallback, KeyboardButtonUrl
import Com.core.tgsend as tgsend
from Com.bot import client as bot_module

__HELP__ = (
    "!inline <text> | button:label:action:value ... → Send a message with inline buttons (via bot).\n"
    "Actions: callback or url.\n"
    "   - callback: sends data back when clicked (you'll get a notification).\n"
    "   - url: opens a link.\n"
    "Use '|' to separate buttons in a row, '||' to start a new row.\n"
    "Example: !inline \"Choose an option\" | Option 1:callback:opt1 | Option 2:callback:opt2\n"
    "If bot is not available, the message will be sent as plain text.\n"
    "Reply to a message to send the inline message as a reply."
)
__CATEGORY__ = "Utilities"

def parse_button_definitions(button_defs):
    """Parse a string of button definitions separated by '|' for rows and '||' for new rows.
       Returns a list of rows, each row a list of (label, action, value) tuples.
    """
    rows = []
    for row_str in button_defs.split('||'):
        row_str = row_str.strip()
        if not row_str:
            continue
        row_buttons = []
        for btn_str in row_str.split('|'):
            btn_str = btn_str.strip()
            if not btn_str:
                continue
            # format: label:action:value
            parts = btn_str.split(':', 2)
            if len(parts) < 3:
                continue
            label, action, value = parts[0].strip(), parts[1].strip(), parts[2].strip()
            row_buttons.append((label, action, value))
        if row_buttons:
            rows.append(row_buttons)
    return rows

def build_telethon_buttons(rows):
    """Convert rows of (label, action, value) to Telethon button objects."""
    telethon_rows = []
    for row in rows:
        telethon_buttons = []
        for label, action, value in row:
            if action == "callback":
                telethon_buttons.append(KeyboardButtonCallback(label, value.encode()))
            elif action == "url":
                telethon_buttons.append(KeyboardButtonUrl(label, value))
            else:
                continue
        if telethon_buttons:
            telethon_rows.append(telethon_buttons)
    return telethon_rows

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!inline(?:\s+(.*))?$"))
    async def inline_cmd(event):
        try:
            arg_str = event.pattern_match.group(1)
            if not arg_str:
                await event.edit("📖 **Inline Help**\n" + __HELP__)
                return

            # Quoted text wins, else split on |
            quoted = re.match(r'^"([^"]*)"', arg_str)
            if quoted:
                text = quoted.group(1)
                remaining = arg_str[len(quoted.group(0)):].strip()
            else:
                first_sep = re.search(r'(\||\|\|)', arg_str)
                if first_sep:
                    text = arg_str[:first_sep.start()].strip()
                    remaining = arg_str[first_sep.start():].strip()
                else:
                    text = arg_str.strip()
                    remaining = ""

            if remaining:
                rows = parse_button_definitions(remaining)
                telethon_rows = build_telethon_buttons(rows)
            else:
                telethon_rows = []

            reply_to = None
            if event.is_reply:
                reply_msg = await event.get_reply_message()
                reply_to = reply_msg.id

            sent = False
            if bot_module.BOT_ENABLED and telethon_rows and bot_module.bot_client:
                sent = await bot_module.send_inline(
                    event.chat_id, text, telethon_rows, reply_to
                )

            if sent:
                await event.delete()
                return

            # No BOT_TOKEN: no buttons
            if telethon_rows:
                await event.edit("⚠️ Bot not available. Sending as plain text without buttons.")
                await asyncio.sleep(1)
            await client.send_message(await tgsend.peer(event), text, reply_to=reply_to)
            await event.delete()

        except Exception as e:
            await event.edit(f"❌ Error: {e}")