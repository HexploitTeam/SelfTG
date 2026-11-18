"""!finduser: scan the exported group logs for one user's messages."""
from telethon import events
import os
from datetime import datetime
import pytz

__HELP__ = "!finduser <username/ID> → Gather all messages sent by a user in all group logs."
__CATEGORY__ = "Information"
GROUP_FOLDER = "Logs/Groups"
tz = pytz.timezone("Asia/Tehran")


def setup(client, my_id):

    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!finduser(?:\s+(here|.+))?$"))
    async def finduser(event):
        try:
            args = event.pattern_match.group(1)
            send_here = False
            target_user_id = None

            if event.is_reply:
                reply_msg = await event.get_reply_message()
                sender = await reply_msg.get_sender()
                target_user_id = sender.id

                if args and args.lower() == "here":
                    send_here = True  # send in command chat
                else:
                    send_here = False  # send in Saved Messages

            elif args:
                parts = args.split()
                if parts[0].lower() == "here":
                    send_here = True
                    if len(parts) > 1:
                        user_str = parts[1]
                        if user_str.isdigit():
                            target_user_id = int(user_str)
                        else:
                            try:
                                user_entity = await client.get_entity(user_str)
                                target_user_id = user_entity.id
                            except:
                                await event.reply(
                                    f"❌ Cannot find user '{user_str}'")
                                return
                else:
                    send_here = False
                    user_str = parts[0]
                    if user_str.isdigit():
                        target_user_id = int(user_str)
                    else:
                        try:
                            user_entity = await client.get_entity(user_str)
                            target_user_id = user_entity.id
                        except:
                            await event.reply(
                                f"❌ Cannot find user '{user_str}'")
                            return
            else:
                await event.reply(
                    "❌ Please specify a user or reply to a message.")
                return

            if target_user_id is None:
                await event.reply("❌ Could not determine user ID.")
                return

            log_lines = []
            for filename in os.listdir(GROUP_FOLDER):
                if not filename.endswith(".txt"):
                    continue
                file_path = os.path.join(GROUP_FOLDER, filename)
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                group_name = lines[0].strip() if lines else "Unknown Group"
                group_msgs = []
                skip_next = False
                for i, line in enumerate(lines[1:], start=1):
                    if skip_next:
                        skip_next = False
                        continue
                    if f"({target_user_id} -" in line:
                        collected = [line.strip()]
                        if i + 1 < len(lines):
                            next_line = lines[i + 1].strip()
                            if next_line.startswith(
                                    "Edited") or next_line.startswith(
                                        "Deleted"):
                                collected.append(next_line)
                                skip_next = True
                        group_msgs.extend(collected)

                if group_msgs:
                    log_lines.append(f"{group_name}:\n" +
                                     "\n".join(group_msgs) + "\n.\n")

            if not log_lines:
                await event.edit(
                    f"❌ No messages found for **{target_user_id}**")
                return

            now = datetime.now(tz).strftime("%Y-%m-%d_%H-%M-%S")
            temp_file = f"{target_user_id}_{now}.txt"
            with open(temp_file, "w", encoding="utf-8") as f:
                f.writelines("\n".join(log_lines))

            target_chat = event.chat_id if send_here else "me"
            await event.client.send_file(
                target_chat,
                temp_file,
                caption=f"Sent the Log file of **{target_user_id}**",
                reply_to=event.id if send_here else None)
            await event.edit(f"Sent the Log file of **{target_user_id}**")
            os.remove(temp_file)

        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")
