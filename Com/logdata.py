"""!logdata: count the exported log files and the disk space they use."""
from telethon import events
import os

from Com.core import brand
from Com.core.reply import say

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
            await say(event, "📊 Calculating log data…", name="logdata")

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

            await say(
                event,
                f"📁 <b>Log files</b> · <code>{total_files}</code> saved in "
                f"<code>{brand.esc(LOG_FOLDER)}</code>\n"
                f"💾 <b>Storage used</b> · <code>{brand.esc(readable_size)}</code>",
                name="logdata",
                parse_mode="html",
            )

        except Exception as e:
            await say(
                event,
                f"❌ <b>Could not read log data.</b> {brand.esc(e)}",
                name="logdata",
                parse_mode="html",
            )
