"""!info: profile summary for the sender or for the replied-to user."""
from telethon import events

from Com.core import brand
from Com.core.reply import say
import Com.core.tgsend as tgsend

__HELP__ = "!info → Show your profile info in the chat\n!info (reply) → Show info of replied user"
__CATEGORY__ = "Information"


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!info$"))
    async def info_handler(event):
        try:
            chat = await event.get_chat()
            chat_name = getattr(chat, "title", None) or getattr(chat, "first_name", "This chat")

            reply_sender = None
            if event.is_reply:
                # A reply to a message in another chat has no local reply_msg;
                # the peer still arrives with the event (layer 155+)
                reply_msg = await event.get_reply_message()
                if reply_msg is not None:
                    reply_sender = getattr(reply_msg, "sender_id", None)
                reply_sender = reply_sender or event.reply_to_sender
                if reply_sender is None:
                    await say(
                        event,
                        "❌ <b>That reply points at a message this account cannot "
                        "read</b>, and Telegram sent no sender for it.",
                        name="info",
                        parse_mode="html",
                    )
                    return
                target_user = await client.get_entity(reply_sender)
            else:
                target_user = await client.get_me()

            await say(
                event,
                f"⏳ <b>Gathering information</b> for <code>{target_user.id}</code> "
                f"in <b>{brand.esc(chat_name)}</b>…",
                name="info",
                parse_mode="html",
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
            display_name = f"{first_name} {last_name}".strip()
            info_text = (
                f"👤 <b>Name</b> · {brand.esc(display_name or 'N/A')}\n"
                f"🆔 <b>ID</b> · <code>{user_id_val}</code>\n"
                f"💬 <b>Username</b> · {brand.esc(username)}\n"
                f"⭐ <b>Premium</b> · {'Yes' if is_premium else 'No'}\n"
                f"📨 <b>Messages in this chat</b> · <code>{total_messages}</code>"
            )
            # Only set when the replied-to message lives in another chat
            if event.reply_to_chat is not None:
                origin = getattr(event.reply_to_chat, "title", None) \
                    or getattr(event.reply_to_chat, "username", None) \
                    or "another chat"
                info_text += f"\n↩️ <b>Reply came from</b> · {brand.esc(origin)}"

            caption = brand.sign(info_text, "info")
            if photo.total > 0:
                await client.send_file(
                    await tgsend.peer(event),
                    photo[0],
                    caption=caption,
                    parse_mode="html",
                    reply_to=event.id,
                )
            else:
                await client.send_message(
                    await tgsend.peer(event),
                    caption,
                    parse_mode="html",
                    reply_to=event.id,
                )

        except Exception as e:
            await say(
                event,
                f"❌ <b>Could not fetch info.</b> {brand.esc(e)}",
                name="info",
                parse_mode="html",
            )
