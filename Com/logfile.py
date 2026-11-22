"""!logfile: send the exported transcript for one chat as a document."""

from telethon import events
from Com.core import brand
from Com.core.reply import say
import os

__HELP__ = "!logfile <Channel|Group|PV> <NumberID> → Sends the log file of the specified chat"
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
            await say(event,
                      "❌ Invalid type. Use <code>Channel</code>, or "
                      "<code>Group</code>.",
                      name="logfile", parse_mode="html")
            return

        if not os.path.exists(folder):
            await say(event,
                      f"❌ Log folder missing · <code>{brand.esc(folder)}</code>",
                      name="logfile", parse_mode="html")
            return

        filename = f"{number_id}.txt"
        file_path = None
        for f in os.listdir(folder):
            if f.strip() == filename:
                file_path = os.path.join(folder, f)
                break

        if not file_path or not os.path.isfile(file_path):
            await say(event,
                      f"❌ Log file not found · <code>{brand.esc(filename)}</code>\n"
                      "Check the folder and the ID.",
                      name="logfile", parse_mode="html")
            return

        # InputPeerSelf: no entity cache needed
        await client.send_file(await client.get_me(input_peer=True),
                               file_path,
                               caption=brand.sign(
                                   f"📄 <b>Log file</b> · "
                                   f"<code>{brand.esc(filename)}</code>",
                                   "logfile"),
                               parse_mode="html")
        await say(event,
                  f"✅ Log file sent · <code>{brand.esc(filename)}</code>",
                  name="logfile", parse_mode="html")

    # Fallback for wrong usage
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!logfile\b"))
    async def logfile_fallback(event):
        parts = event.text.split()
        if len(parts) != 3 or parts[1] not in ["Channel", "PV", "Group"]:
            await say(event,
                      "❌ Wrong format. Correct usage · "
                      "<code>!logfile &lt;Channel|Group&gt; &lt;NumberID&gt;</code>",
                      name="logfile", parse_mode="html")
