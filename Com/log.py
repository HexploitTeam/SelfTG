"""!log: mirror messages, edits and deletions into text files under Logs/."""

from telethon import events
from datetime import datetime
import os
import pytz

__HELP__ = "!log ON/OFF → Enable or disable logging messages to text files"
__CATEGORY__ = "Information"

LOG_FOLDER = "Logs"
GROUP_FOLDER = os.path.join(LOG_FOLDER, "Groups")
CHANNEL_FOLDER = os.path.join(LOG_FOLDER, "Channels")
MODE_FOLDER = "mode"
MODE_FILE = os.path.join(MODE_FOLDER, "com.txt")

for folder in [LOG_FOLDER, GROUP_FOLDER, CHANNEL_FOLDER, MODE_FOLDER]:
    os.makedirs(folder, exist_ok=True)

if os.path.exists(MODE_FILE):
    with open(MODE_FILE, "r", encoding="utf-8") as f:
        line = f.readline().strip()
        LOG_MODE = line.split(":")[-1].strip() if ":" in line else "OFF"
else:
    LOG_MODE = "OFF"
    with open(MODE_FILE, "w", encoding="utf-8") as f:
        f.write(f"!log: {LOG_MODE}")

TZ = pytz.timezone("Asia/Tehran")


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):

    def normalize_text(text):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

    def get_file_path_and_title(event):
        chat = event.chat
        if event.is_private:
            return None, None  # Skip PV logging
        elif getattr(chat, "broadcast", False):
            return os.path.join(CHANNEL_FOLDER,
                                f"{event.chat_id}.txt"), getattr(
                                    chat, "title", "Channel")
        else:
            return os.path.join(GROUP_FOLDER, f"{event.chat_id}.txt"), getattr(
                chat, "title", "Group")

    # !log ON/OFF command
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!log\s+(DISABLED|OFF)$"))
    async def log_mode(event):
        global LOG_MODE
        mode = event.text.split()[1].upper()
        LOG_MODE = mode
        with open(MODE_FILE, "w", encoding="utf-8") as f:
            f.write(f"!log: {LOG_MODE}")
        await event.edit(f"✅ Logging mode set to: {LOG_MODE}")

    # Log new messages
    @client.on(events.NewMessage())
    async def log_message(event):
        global LOG_MODE
        if LOG_MODE != "ON" or not event.raw_text:
            return

        file_path, chat_name = get_file_path_and_title(event)
        if not file_path:
            return

        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        sender = await event.get_sender()
        now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        msg_id = event.message.id

        sender_name = getattr(sender, "first_name", None) or getattr(
            sender, "title", "Unknown")
        sender_id = getattr(sender, "id", "Unknown")
        username = f"@{sender.username}" if getattr(sender, "username",
                                                    None) else "N/A"
        text = normalize_text(event.raw_text)

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(
                f"{sender_name} ({sender_id} - {username} - {now} - {msg_id}): {text}\n"
            )
            f.write(".\n")

    # Log edited messages
    @client.on(events.MessageEdited())
    async def log_edit(event):
        global LOG_MODE
        if LOG_MODE != "ON" or not event.raw_text:
            return

        file_path, _ = get_file_path_and_title(event)
        if not file_path or not os.path.exists(file_path):
            return

        now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        edited_text = normalize_text(event.raw_text)

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if f"- {event.message.id}):" in line:
                lines.insert(i + 1, f"Edited ({now}): {edited_text}\n")
                break

        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    # Log deleted messages
    @client.on(events.MessageDeleted())
    async def log_deleted(event):
        global LOG_MODE
        if LOG_MODE != "ON":
            return

        file_path, _ = get_file_path_and_title(event)
        if not file_path or not os.path.exists(file_path):
            return

        now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for msg_id in event.deleted_ids:
            for i, line in enumerate(lines):
                if f"- {msg_id}):" in line:
                    lines.insert(i + 1, f"Deleted ({now})\n")
                    break

        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
