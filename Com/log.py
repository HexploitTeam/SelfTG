from telethon import events
from datetime import datetime
import os
import pytz

__HELP__ = "!log ON/OFF → Enable or disable logging messages to text files"

LOG_FOLDER = "Logs"
PV_FOLDER = os.path.join(LOG_FOLDER, "PV")
GROUP_FOLDER = os.path.join(LOG_FOLDER, "Groups")
CHANNEL_FOLDER = os.path.join(LOG_FOLDER, "Channels")
MODE_FOLDER = "mode"
MODE_FILE = os.path.join(MODE_FOLDER, "com.txt")

for folder in [
        LOG_FOLDER, PV_FOLDER, GROUP_FOLDER, CHANNEL_FOLDER, MODE_FOLDER
]:
    os.makedirs(folder, exist_ok=True)

if os.path.exists(MODE_FILE):
    with open(MODE_FILE, "r", encoding="utf-8") as f:
        line = f.readline().strip()
        LOG_MODE = line.split(":")[-1].strip() if ":" in line else "OFF"
else:
    LOG_MODE = "OFF"
    with open(MODE_FILE, "w", encoding="utf-8") as f:
        f.write(f"!log: {LOG_MODE}")


def setup(client, my_id):
    tz = pytz.timezone("Asia/Tehran")

    def normalize_text(text):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

    def get_file_path(event):
        chat_id = str(event.chat_id)
        chat = event.chat
        if event.is_private:
            return os.path.join(PV_FOLDER, f"{chat_id}.txt")
        elif getattr(chat, "broadcast", False):
            return os.path.join(CHANNEL_FOLDER, f"{chat_id}.txt")
        else:
            return os.path.join(GROUP_FOLDER, f"{chat_id}.txt")

    def get_chat_name(event):
        chat = event.chat
        return getattr(chat, "title", getattr(chat, "first_name", "Unknown"))

    # -----------------------
    # !log ON/OFF command
    # -----------------------
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!log\s+(ON|OFF)$"))
    async def log_mode(event):
        global LOG_MODE
        mode = event.text.split()[1].upper()
        LOG_MODE = mode
        with open(MODE_FILE, "w", encoding="utf-8") as f:
            f.write(f"!log: {LOG_MODE}")
        await event.edit(f"✅ Logging mode set to: {LOG_MODE}")

    # -----------------------
    # fallback for wrong usage
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!log\b"))
    async def log_fallback(event):
        parts = event.text.upper().split()
        if len(parts) != 2 or parts[1] not in ["ON", "OFF"]:
            await event.edit("❌ Wrong format. Correct usage: !log ON/OFF")

    # -----------------------
    # Log messages
    @client.on(events.NewMessage())
    async def log_message(event):
        global LOG_MODE
        if LOG_MODE != "ON" or not event.message.message:
            return

        file_path = get_file_path(event)
        chat_name = get_chat_name(event)
        sender = await event.get_sender()
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

        # File creation and name changes
        if not os.path.exists(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"{chat_name}\n")
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            first_line = lines[0].strip() if lines else ""
            if first_line != chat_name:
                with open(file_path, "a", encoding="utf-8") as f:
                    f.write(f"Edited: {chat_name} {now}\n")

        if sender is None:
            sender_name = "Unknown"
            sender_id = event.sender_id
            sender_username = "N/A"
        else:
            sender_name = getattr(sender, "first_name", None) or getattr(
                sender, "title", "Unknown")
            sender_id = getattr(sender, "id", "Unknown")
            sender_username = f"@{sender.username}" if getattr(
                sender, "username", None) else "N/A"

        msg_text = normalize_text(event.message.message)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(
                f"{sender_name} ({sender_id} - {sender_username} - {now}): {msg_text}\n.\n"
            )

    # -----------------------
    # Log edited messages
    @client.on(events.MessageEdited())
    async def log_edit(event):
        global LOG_MODE
        if LOG_MODE != "ON" or not event.message.message:
            return

        file_path = get_file_path(event)
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        edited_text = normalize_text(event.message.message)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"Edited: {edited_text} ({now})\n.\n")
