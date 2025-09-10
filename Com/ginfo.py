from telethon import events
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import Channel, Chat

__HELP__ = "!ginfo → Shows detailed info about the current group or channel"


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!ginfo$"))
    async def group_info(event):
        try:
            chat = await event.get_chat()
            chat_id = chat.id  # keeps -100 prefix
            name = getattr(chat, "title", getattr(chat, "first_name",
                                                  "Unknown"))
            username = getattr(chat, "username", None)
            invite_link = f"https://t.me/{username}" if username else "N/A"
            description = getattr(chat, "about", None) or getattr(
                chat, "description", None) or "No description"

            # Get member count
            try:
                if isinstance(chat, (Channel, Chat)):
                    member_count = getattr(chat, "participants_count", None)
                    if member_count is None:
                        members = await client.get_participants(chat)
                        member_count = len(members)
                else:
                    member_count = "N/A"
            except:
                member_count = "N/A"

            # Total messages
            try:
                history = await client(
                    GetHistoryRequest(peer=chat,
                                      limit=0,
                                      offset_date=None,
                                      offset_id=0,
                                      max_id=0,
                                      min_id=0,
                                      add_offset=0,
                                      hash=0))
                total_messages = history.count
            except:
                total_messages = "N/A"

            info_text = (f"📌 Group Info:\n"
                         f"Name: {name}\n"
                         f"ID: {chat_id}\n"
                         f"Link: {invite_link}\n"
                         f"Description: {description}\n"
                         f"Members: {member_count}\n"
                         f"Total Messages: {total_messages}\n")

            await event.edit(info_text)
        except Exception as e:
            await event.edit(f"❌ Failed to fetch info: {str(e)}")
