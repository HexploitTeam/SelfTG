# Com/sysmon.py
import time
import psutil
import platform
import os
import asyncio
import json
from telethon import events

__HELP__ = "!sysmon start/stop/export → Live system monitor that updates every 5s, logs stats, and can export logs."
__CATEGORY__ = "Utilities"

START_TIME = time.time()
active_monitors = {}  # chat_id -> task

LOG_DIR = "mode/sys"
LOG_FILE = os.path.join(LOG_DIR, "sysmon.json")
os.makedirs(LOG_DIR, exist_ok=True)


def format_stats():
    uptime_seconds = int(time.time() - START_TIME)
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"

    cpu_usage = psutil.cpu_percent(interval=0.5)
    cpu_count = psutil.cpu_count(logical=True)

    memory = psutil.virtual_memory()
    mem_usage = (f"{memory.used // (1024**2)}MB / "
                 f"{memory.total // (1024**2)}MB ({memory.percent}%)")

    swap = psutil.swap_memory()
    swap_usage = (f"{swap.used // (1024**2)}MB / "
                  f"{swap.total // (1024**2)}MB ({swap.percent}%)"
                  if swap.total > 0 else "N/A")

    load_avg = "N/A"
    if hasattr(os, "getloadavg"):
        la1, la5, la15 = os.getloadavg()
        load_avg = f"{la1:.2f}, {la5:.2f}, {la15:.2f}"

    disk = psutil.disk_usage(os.getcwd())
    used_gb = disk.used / (1024**3)
    total_gb = disk.total / (1024**3)
    if used_gb < 1:
        used_str = f"{disk.used // (1024**2)}MB"
    else:
        used_str = f"{used_gb:.1f}GB"
    if total_gb < 1:
        total_str = f"{disk.total // (1024**2)}MB"
    else:
        total_str = f"{total_gb:.1f}GB"
    disk_usage = f"{used_str} / {total_str} ({disk.percent}%)"

    processes = len(psutil.pids())
    sys_info = f"{platform.system()} {platform.release()} ({platform.machine()})"

    stats = {
        "uptime": uptime_str,
        "cpu_usage": f"{cpu_usage}%",
        "cpu_cores": cpu_count,
        "memory": mem_usage,
        "swap": swap_usage,
        "load_avg": load_avg,
        "disk": disk_usage,
        "processes": processes,
        "system": sys_info,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    }

    return stats


def save_stats(stats):
    """Save stats to JSON, ensure it's a list."""
    data = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    data = loaded
                else:
                    # If file contains dict or something else, reset to list
                    data = []
        except Exception:
            data = []

    data.append(stats)

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def pretty_stats(stats):
    return (
        f"⏱ **Uptime:** `{stats['uptime']}`\n\n"
        f"💻 **System:** `{stats['system']}`\n"
        f"🧮 **CPU:** `{stats['cpu_usage']}` of {stats['cpu_cores']} cores\n"
        f"📦 **Memory:** `{stats['memory']}`\n"
        f"💾 **Swap:** `{stats['swap']}`\n"
        f"📊 **Load Avg (1/5/15m):** `{stats['load_avg']}`\n"
        f"💽 **Disk:** `{stats['disk']}`\n"
        f"⚙️ **Processes:** `{stats['processes']}`\n"
        f"🕒 **Logged at:** `{stats['timestamp']}`")


def setup(client, my_id):

    async def monitor_task(chat_id, msg):
        try:
            while chat_id in active_monitors:
                stats = format_stats()
                save_stats(stats)  # log into file
                await msg.edit(pretty_stats(stats))
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await msg.edit(f"❌ Monitor error: {str(e)}")
        finally:
            active_monitors.pop(chat_id, None)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!sysmon start$"))
    async def start_sysmon(event):
        chat_id = event.chat_id
        if chat_id in active_monitors:
            await event.reply("⚠️ SysMon is already running in this chat.")
            return

        msg = await event.reply("🖥 Starting system monitor...")
        task = asyncio.create_task(monitor_task(chat_id, msg))
        active_monitors[chat_id] = task
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!sysmon stop$"))
    async def stop_sysmon(event):
        chat_id = event.chat_id
        if chat_id not in active_monitors:
            await event.reply("⚠️ SysMon is not running here.")
            return

        task = active_monitors.pop(chat_id)
        task.cancel()
        await event.reply("🛑 SysMon stopped.")
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!sysmon export$"))
    async def export_sysmon(event):
        if not os.path.exists(LOG_FILE):
            await event.reply("❌ No logs found yet.")
            return
        await event.reply("📤 Exporting system monitor logs...")
        await client.send_file(event.chat_id,
                               LOG_FILE,
                               caption="📊 SysMon Logs")
