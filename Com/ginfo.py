# Com/ginfo.py
from telethon import events, functions, types

__HELP__ = "!ginfo → Shows group/channel info including name, ID, members, total messages, description, and profile picture"


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!ginfo$"))
    async def ginfo(event):
        try:
            # Fetch chat info
            chat = await event.get_chat()
            chat_id = chat.id
            title = getattr(chat, "title", "N/A")
            username = f"@{chat.username}" if getattr(chat, "username",
                                                      None) else "N/A"

            # Fetch full channel info
            if isinstance(chat, types.Channel) or isinstance(chat, types.Chat):
                full = await client(
                    functions.channels.GetFullChannelRequest(channel=chat))
                description = getattr(full.full_chat, "about", "N/A")
                total_members = getattr(full.full_chat, "participants_count",
                                        "N/A")
            else:
                description = "N/A"
                total_members = "N/A"

            # Count total text messages
            messages = await client.get_messages(chat_id, limit=None)
            total_msgs = sum(1 for msg in messages if msg.text)

            # Send initial message
            msg_text = (f"📌 Name: {title}\n"
                        f"🆔 ID: {chat_id}\n"
                        f"💬 Username: {username}\n"
                        f"👥 Members: {total_members}\n"
                        f"✉️ Total text messages: {total_msgs}\n"
                        f"📝 Description: {description}")
            info_msg = await event.reply(msg_text)

            # Send main profile picture
            try:
                photos = await client.get_profile_photos(chat)
                if photos.total > 0:
                    await client.send_file(event.chat_id,
                                           photos[0],
                                           reply_to=info_msg.id)
            except Exception:
                # Ignore if no photo
                pass

        except Exception as e:
            await event.reply(f"❌ Failed to fetch group info: {str(e)}")
