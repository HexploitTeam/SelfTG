"""!info: profile summary for the sender or for the replied-to user."""
from telethon import events
import Com.core.tgsend as tgsend

__HELP__ = "!info → Show your profile info in the chat\n!info (reply) → Show info of replied user"
__CATEGORY__ = "Information"


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!info$"))
    async def info_handler(event):
        try:
            chat = await event.get_chat()
            chat_name = getattr(chat, "title", None) or getattr(chat, "first_name", "This chat")

            if event.is_reply:
                reply_msg = await event.get_reply_message()
                target_user = await client.get_entity(reply_msg.sender_id)
            else:
                target_user = await client.get_me()

            await event.edit(
                f"Gathering **{target_user.id}'s information** in **'{chat_name}'**..."
            )

            first_name = target_user.first_name or ""
            last_name = target_user.last_name or ""
            username = f"@{target_user.username}" if target_user.username else "N/A"
            user_id_val = target_user.id
            is_premium = getattr(target_user, "premium", False)

            total_messages = 0
            async for msg in client.iter_messages(await tgsend.peer(event), from_user=user_id_val):
                total_messages += 1

            photo = await client.get_profile_photos(target_user)
            info_text = (
                f"👤 Name: {first_name} {last_name}\n"
                f"🆔 ID: {user_id_val}\n"
                f"💬 Username: {username}\n"
                f"⭐ Premium: {'Yes' if is_premium else 'No'}\n"
                f"📨 Total messages sent in this chat: {total_messages}"
            )

            if photo.total > 0:
                await client.send_file(await tgsend.peer(event), photo[0], caption=info_text, reply_to=event.id)
            else:
                await client.send_message(await tgsend.peer(event), info_text, reply_to=event.id)

        except Exception as e:
            await event.reply(f"❌ Failed to fetch info: {str(e)}")
