# Com/blockuser.py
from telethon import events
from telethon import functions

__HELP__ = "!block @username / reply → Block user\n!unblock @username / reply → Unblock user"
__CATEGORY__ = "Utilities"


def setup(client, my_id):

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!block(?:\s+(\S+))?"))
    async def block_user(event):
        try:
            target = event.pattern_match.group(1)
            # Determine target user
            if event.is_reply:
                reply_msg = await event.get_reply_message()
                user = await reply_msg.get_sender()
            elif target:
                user = await client.get_entity(target)
            else:
                await event.edit(
                    "❌ Reply to a user or provide @username to block.")
                return

            await client(functions.contacts.BlockRequest(id=user.id))
            await event.edit(
                f"✅ Blocked user: {getattr(user, 'first_name', 'Unknown')} (@{getattr(user, 'username', 'N/A')})"
            )
        except Exception as e:
            await event.edit(f"❌ Error blocking user: {str(e)}")

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!unblock(?:\s+(\S+))?"))
    async def unblock_user(event):
        try:
            target = event.pattern_match.group(1)
            # Determine target user
            if event.is_reply:
                reply_msg = await event.get_reply_message()
                user = await reply_msg.get_sender()
            elif target:
                user = await client.get_entity(target)
            else:
                await event.edit(
                    "❌ Reply to a user or provide @username to unblock.")
                return

            await client(functions.contacts.UnblockRequest(id=user.id))
            await event.edit(
                f"✅ Unblocked user: {getattr(user, 'first_name', 'Unknown')} (@{getattr(user, 'username', 'N/A')})"
            )
        except Exception as e:
            await event.edit(f"❌ Error unblocking user: {str(e)}")
