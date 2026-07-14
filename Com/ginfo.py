# Com/ginfo.py
from telethon import events, functions, types
from datetime import datetime
import pytz

__HELP__ = "!ginfo → Shows group/channel info (name, ID, total members, description) without saving."
__CATEGORY__ = "Information"

def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!ginfo$"))
    async def ginfo(event):
        tz = pytz.timezone("Asia/Tehran")
        try:
            chat = await event.get_chat()
            full = await client(functions.channels.GetFullChannelRequest(channel=chat))

            title = getattr(chat, "title", "N/A")
            chat_id = chat.id
            username = f"@{chat.username}" if getattr(chat, "username", None) else "N/A"
            description = getattr(full.full_chat, "about", "N/A")
            total_members = getattr(full.full_chat, "participants_count", "N/A")

            now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

            # Edit original command message
            await event.edit(f"Gathering {chat_id} (**{title}**) Info . . .")

            # Send main profile picture (if exists)
            try:
                photos = await client.get_profile_photos(chat)
                if photos.total > 0:
                    await client.send_file(
                        event.chat_id,
                        photos[0],
                        caption=(
                            f"📌 Name: {title}\n"
                            f"🆔 ID: {chat_id}\n"
                            f"💬 Username: {username}\n"
                            f"👥 Members: {total_members}\n"
                            f"⏱ Retrieved at: {now}\n"
                            f"📝 Description: {description}"

                        ),
                        reply_to=event.id
                    )
                else:
                    # No profile picture
                    await event.reply(
                        f"📌 Name: {title}\n"
                        f"🆔 ID: {chat_id}\n"
                        f"💬 Username: {username}\n"
                        f"👥 Members: {total_members}\n"
                        f"⏱ Retrieved at: {now}\n"
                        f"📝 Description: {description}"

                    )
            except Exception:
                # Fallback if profile fetch fails
                await event.reply(
                    f"📌 Name: {title}\n"
                    f"🆔 ID: {chat_id}\n"
                    f"💬 Username: {username}\n"
                    f"👥 Members: {total_members}\n"
                    f"⏱ Retrieved at: {now}\n"
                    f"📝 Description: {description}"

                )

        except Exception as e:
            await event.reply(f"❌ Failed to fetch group info: {str(e)}")
