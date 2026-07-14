# Com/logdata.py
from telethon import events
import os

__HELP__ = "!logdata → Show total number of log files and storage used"
__CATEGORY__ = "Information"
LOG_FOLDER = "Logs"
SUBFOLDERS = ["Groups", "Channels"]  # ignore PV as per your previous decision


def human_readable_size(size_bytes):
    """Convert bytes to a readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!logdata$"))
    async def logdata(event):
        try:
            # Edit the command to show "Calculating..."
            await event.edit("📊 Calculating log data...")

            total_files = 0
            total_size = 0

            for folder in SUBFOLDERS:
                path = os.path.join(LOG_FOLDER, folder)
                if os.path.exists(path):
                    for root, dirs, files in os.walk(path):
                        total_files += len(files)
                        for f in files:
                            total_size += os.path.getsize(os.path.join(
                                root, f))

            readable_size = human_readable_size(total_size)

            # Edit the command message with the final result
            await event.edit(
                f"📁 There are {total_files} log files saved in '{LOG_FOLDER}'.\n💾 Storage used: {readable_size}"
            )

        except Exception as e:
            await event.edit(f"❌ Failed to get log data: {str(e)}")
