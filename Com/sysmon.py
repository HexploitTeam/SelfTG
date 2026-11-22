"""!sysmon: periodic system samples kept in a bounded history file."""
import time
import psutil
import platform
import os
import asyncio
import json
from telethon import events
import Com.core.tgsend as tgsend
from Com.core import brand
from Com.core.reply import say

from Com.core.storage import save_json as _save_json

__HELP__ = "!sysmon start/stop/export → Live system monitor that updates every 5s, logs stats, and can export logs."
__CATEGORY__ = "Utilities"

START_TIME = time.time()
active_monitors = {}  # chat_id -> task

LOG_DIR = "mode/sys"
LOG_FILE = os.path.join(LOG_DIR, "sysmon.json")
os.makedirs(LOG_DIR, exist_ok=True)

# 2s samples; bound the file
MAX_LOG_ENTRIES = 500
# Prime psutil for interval=None
psutil.cpu_percent(interval=None)


#------------------------------
#Helpers
#------------------------------

def format_stats():
    uptime_seconds = int(time.time() - START_TIME)
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"

    # interval=None: a blocking sample froze handlers
    cpu_usage = psutil.cpu_percent(interval=None)
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
                    data = []
        except Exception:
            data = []

    data.append(stats)
    if len(data) > MAX_LOG_ENTRIES:
        del data[:-MAX_LOG_ENTRIES]

    # Atomic: the dashboard reads this
    _save_json(LOG_FILE, data)


def pretty_stats(stats):
    return (
        f"⏱ <b>Uptime</b> · <code>{brand.esc(stats['uptime'])}</code>\n"
        f"💻 <b>System</b> · <code>{brand.esc(stats['system'])}</code>\n"
        f"🧮 <b>CPU</b> · <code>{brand.esc(stats['cpu_usage'])}</code> of "
        f"{brand.esc(stats['cpu_cores'])} cores\n"
        f"📦 <b>Memory</b> · <code>{brand.esc(stats['memory'])}</code>\n"
        f"💾 <b>Swap</b> · <code>{brand.esc(stats['swap'])}</code>\n"
        f"📊 <b>Load avg</b> <i>(1/5/15m)</i> · "
        f"<code>{brand.esc(stats['load_avg'])}</code>\n"
        f"💽 <b>Disk</b> · <code>{brand.esc(stats['disk'])}</code>\n"
        f"⚙️ <b>Processes</b> · <code>{brand.esc(stats['processes'])}</code>\n"
        f"🕒 <b>Logged at</b> · <code>{brand.esc(stats['timestamp'])}</code>")


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):

    async def monitor_task(chat_id, msg):
        try:
            while chat_id in active_monitors:
                stats = format_stats()
                save_stats(stats)  # log into file
                await msg.edit(brand.sign(pretty_stats(stats), "sysmon"),
                               parse_mode="html")
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await msg.edit(
                brand.sign(f"❌ <b>Monitor error</b> · "
                           f"<code>{brand.esc(e)}</code>", "sysmon"),
                parse_mode="html")
        finally:
            active_monitors.pop(chat_id, None)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!sysmon start$"))
    async def start_sysmon(event):
        chat_id = event.chat_id
        if chat_id in active_monitors:
            await say(event, "⚠️ SysMon is already running in this chat.",
                      name="sysmon")
            return

        msg = await event.reply(
            brand.sign("🖥 <b>Starting system monitor</b>…", "sysmon"),
            parse_mode="html")
        task = asyncio.create_task(monitor_task(chat_id, msg))
        active_monitors[chat_id] = task
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!sysmon stop$"))
    async def stop_sysmon(event):
        chat_id = event.chat_id
        if chat_id not in active_monitors:
            await say(event, "⚠️ SysMon is not running here.", name="sysmon")
            return

        task = active_monitors.pop(chat_id)
        task.cancel()
        await say(event, "🛑 <b>SysMon stopped</b>", name="sysmon",
                  parse_mode="html")
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!sysmon export$"))
    async def export_sysmon(event):
        if not os.path.exists(LOG_FILE):
            await say(event, "❌ No logs found yet.", name="sysmon")
            return
        await say(event, "📤 <b>Exporting system monitor logs</b>…",
                  name="sysmon", parse_mode="html")
        await client.send_file(
            await tgsend.peer(event),
            LOG_FILE,
            caption=brand.sign("📊 <b>SysMon Logs</b>", "sysmon"),
            parse_mode="html")
