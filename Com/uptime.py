"""!uptime: bot runtime plus a resource snapshot."""
import time
import psutil
from telethon import events
import platform
import os

__HELP__ = "!uptime → Report bot runtime uptime and system resource snapshot."
__CATEGORY__ = "Utilities"

# Track bot start time
START_TIME = time.time()
# Prime psutil so the first interval=None reading is meaningful.
psutil.cpu_percent(interval=None)


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!uptime$"))
    async def uptime_handler(event):
        try:
            uptime_seconds = int(time.time() - START_TIME)
            days, remainder = divmod(uptime_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"

            # interval=0.5 would block the loop; None reports since last call
            cpu_usage = psutil.cpu_percent(interval=None)
            cpu_count = psutil.cpu_count(logical=True)

            # RAM
            memory = psutil.virtual_memory()
            mem_usage = (f"{memory.used // (1024**2)}MB / "
                         f"{memory.total // (1024**2)}MB ({memory.percent}%)")

            # Swap
            swap = psutil.swap_memory()
            swap_usage = (f"{swap.used // (1024**2)}MB / "
                          f"{swap.total // (1024**2)}MB ({swap.percent}%)"
                          if swap.total > 0 else "N/A")

            # Load average (if supported)
            load_avg = "N/A"
            if hasattr(os, "getloadavg"):
                la1, la5, la15 = os.getloadavg()
                load_avg = f"{la1:.2f}, {la5:.2f}, {la15:.2f}"

            # Disk
            disk = psutil.disk_usage("/")
            disk_usage = (f"{disk.used // (1024**3)}GB / "
                          f"{disk.total // (1024**3)}GB ({disk.percent}%)")

            # Processes count
            processes = len(psutil.pids())

            # System info
            sys_info = f"{platform.system()} {platform.release()} ({platform.machine()})"

            msg = (f"⏱ **Bot Uptime:** `{uptime_str}`\n\n"
                   f"💻 **System:** `{sys_info}`\n"
                   f"🧮 **CPU:** `{cpu_usage}%` of {cpu_count} cores\n"
                   f"📦 **Memory:** `{mem_usage}`\n"
                   f"💾 **Swap:** `{swap_usage}`\n"
                   f"📊 **Load Avg (1/5/15m):** `{load_avg}`\n"
                   f"💽 **Disk:** `{disk_usage}`\n"
                   f"⚙️ **Processes:** `{processes}`")

            await event.reply(msg)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
