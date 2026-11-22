"""!block and !unblock, targeting the argument or the replied-to user."""
from telethon import events
from telethon import functions

from Com.core import brand
from Com.core.reply import say

__HELP__ = "!block @username / reply → Block user\n!unblock @username / reply → Unblock user"
__CATEGORY__ = "Utilities"


def setup(client, my_id):

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!block(?:\s+(\S+))?"))
    async def block_user(event):
        try:
            target = event.pattern_match.group(1)
            if event.is_reply:
                reply_msg = await event.get_reply_message()
                user = await reply_msg.get_sender()
            elif target:
                user = await client.get_entity(target)
            else:
                await say(
                    event, "❌ Reply to a user or provide @username to block.",
                    name="block",
                )
                return

            await client(functions.contacts.BlockRequest(id=user.id))
            await say(
                event,
                f"✅ <b>Blocked</b> "
                f"{brand.esc(getattr(user, 'first_name', 'Unknown'))} "
                f"(<code>@{brand.esc(getattr(user, 'username', 'N/A'))}</code>)",
                name="block",
                parse_mode="html",
            )
        except Exception as e:
            await say(
                event,
                f"❌ <b>Could not block user.</b> {brand.esc(e)}",
                name="block",
                parse_mode="html",
            )

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!unblock(?:\s+(\S+))?"))
    async def unblock_user(event):
        try:
            target = event.pattern_match.group(1)
            if event.is_reply:
                reply_msg = await event.get_reply_message()
                user = await reply_msg.get_sender()
            elif target:
                user = await client.get_entity(target)
            else:
                await say(
                    event, "❌ Reply to a user or provide @username to unblock.",
                    name="unblock",
                )
                return

            await client(functions.contacts.UnblockRequest(id=user.id))
            await say(
                event,
                f"✅ <b>Unblocked</b> "
                f"{brand.esc(getattr(user, 'first_name', 'Unknown'))} "
                f"(<code>@{brand.esc(getattr(user, 'username', 'N/A'))}</code>)",
                name="unblock",
                parse_mode="html",
            )
        except Exception as e:
            await say(
                event,
                f"❌ <b>Could not unblock user.</b> {brand.esc(e)}",
                name="unblock",
                parse_mode="html",
            )
