"""!ginfo: group or channel metadata read live, without saving anything."""
from telethon import events, functions, types
import Com.core.tgsend as tgsend
from datetime import datetime
import pytz

from Com.core import brand
from Com.core.reply import say

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

            await say(
                event,
                f"⏳ <b>Gathering info</b> · <code>{chat_id}</code> "
                f"({brand.esc(title)})…",
                name="ginfo",
                parse_mode="html",
            )

            card = brand.sign(
                f"📌 <b>Name</b> · {brand.esc(title)}\n"
                f"🆔 <b>ID</b> · <code>{chat_id}</code>\n"
                f"💬 <b>Username</b> · {brand.esc(username)}\n"
                f"👥 <b>Members</b> · <code>{brand.esc(total_members)}</code>\n"
                f"⏱ <b>Retrieved at</b> · <code>{now}</code>\n"
                f"📝 <b>Description</b> · {brand.esc(description)}",
                "ginfo",
            )

            try:
                photos = await client.get_profile_photos(chat)
                if photos.total > 0:
                    await client.send_file(
                        await tgsend.peer(event),
                        photos[0],
                        caption=card,
                        parse_mode="html",
                        reply_to=event.id,
                    )
                else:
                    # No profile picture
                    await event.reply(card, parse_mode="html")
            except Exception:
                # Fallback if profile fetch fails
                await event.reply(card, parse_mode="html")

        except Exception as e:
            await say(
                event,
                f"❌ <b>Could not fetch group info.</b> {brand.esc(e)}",
                name="ginfo",
                parse_mode="html",
            )
