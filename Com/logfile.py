from telethon import events
import os

__HELP__ = "!logfile <Channel|Group> <NumberID> → Sends the log file of the specified chat"
__CATEGORY__ = "Information"
LOG_FOLDER = "Logs"
PV_FOLDER = os.path.join(LOG_FOLDER, "PV")
GROUP_FOLDER = os.path.join(LOG_FOLDER, "Groups")
CHANNEL_FOLDER = os.path.join(LOG_FOLDER, "Channels")


def setup(client, my_id):

    @client.on(
        events.NewMessage(
            from_users=my_id,
            pattern=r"^!logfile\s+(Channel|Group)\s+(-?\d+)$"))
    async def send_log_file(event):
        folder_map = {
            "PV": PV_FOLDER,
            "Group": GROUP_FOLDER,
            "Channel": CHANNEL_FOLDER
        }

        parts = event.text.split()
        log_type = parts[1]
        number_id = parts[2]

        folder = folder_map.get(log_type)
        if not folder:
            await event.edit("❌ Invalid type. Use Channel, or Group.")
            return

        # Ensure the folder exists
        if not os.path.exists(folder):
            await event.edit(f"❌ Log folder missing: {folder}")
            return

        # Search for file in folder (exact match)
        filename = f"{number_id}.txt"
        file_path = None
        for f in os.listdir(folder):
            if f.strip() == filename:
                file_path = os.path.join(folder, f)
                break

        if not file_path or not os.path.isfile(file_path):
            await event.edit(
                f"❌ Log file not found: {filename}\nCheck folder and ID.")
            return

        # Send the file
        await client.send_file(int(my_id),
                               file_path,
                               caption=f"Log file: {filename}")
        await event.edit(f"✅ Log file sent: {filename}")

    # Fallback for wrong usage
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!logfile\b"))
    async def logfile_fallback(event):
        parts = event.text.split()
        if len(parts) != 3 or parts[1] not in ["Channel", "PV", "Group"]:
            await event.edit(
                "❌ Wrong format. Correct usage: !logfile <Channel|Group> <NumberID>"
            )
