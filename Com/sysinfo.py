# Com/sysinfo.py
import psutil
import platform
import asyncio
import os
import json
from datetime import datetime
import pytz
from telethon import events

from Com.storage import save_json as _save_json

try:
    import GPUtil
except:
    GPUtil = None

__HELP__ = "!sysinfo → Show detailed system information including CPU, memory, disks, network, GPU, and uptime."

os.makedirs("mode/sys", exist_ok=True)
# This used to be mode/sys/sysmon.json, which Com/sysmon.py keeps as a *list*
# of samples: this module overwrote it with a single dict every few seconds, so
# !sysmon export handed back one snapshot instead of history.
SYS_LOG_FILE = "mode/sys/sysinfo.json"
TZ = pytz.timezone("Asia/Tehran")


def setup(client, my_id):

    async def collect_sysinfo():
        try:
            now = datetime.now(TZ)
            # CPU
            cpu_freq = psutil.cpu_freq()
            cpu_percent_per_core = psutil.cpu_percent(percpu=True)
            cpu_count = psutil.cpu_count(logical=True)
            cpu_cores = psutil.cpu_count(logical=False)

            # Memory
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()

            # Disks
            disks = []
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append({
                        "device": part.device,
                        "mount": part.mountpoint,
                        "used": usage.used,
                        "total": usage.total,
                        "percent": usage.percent
                    })
                except:
                    continue

            # Network
            net_io = psutil.net_io_counters()
            # psutil.net_connections() raises AccessDenied on non-root Linux and
            # is expensive; one failure used to abort the entire report.
            try:
                conns = len(psutil.net_connections(kind="inet"))
            except Exception:
                conns = None

            # Uptime
            boot_time = datetime.fromtimestamp(psutil.boot_time(), tz=TZ)
            uptime_sec = (now - boot_time).total_seconds()
            days, rem = divmod(uptime_sec, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, _ = divmod(rem, 60)

            # GPU
            gpus = []
            if GPUtil:
                try:
                    for gpu in GPUtil.getGPUs():
                        gpus.append({
                            "name": gpu.name,
                            "load": gpu.load * 100,
                            "mem_used": gpu.memoryUsed,
                            "mem_total": gpu.memoryTotal,
                            "temp": gpu.temperature
                        })
                except:
                    pass

            sysinfo = {
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "cpu": {
                    "cores": cpu_cores,
                    "threads": cpu_count,
                    "freq": cpu_freq.current if cpu_freq else None,
                    "per_core_usage": cpu_percent_per_core
                },
                "memory": {
                    "total": mem.total,
                    "used": mem.used,
                    "percent": mem.percent,
                    "swap_total": swap.total,
                    "swap_used": swap.used,
                    "swap_percent": swap.percent
                },
                "disks": disks,
                "network": {
                    "sent": net_io.bytes_sent,
                    "recv": net_io.bytes_recv,
                    "connections": conns
                },
                "uptime":
                f"{int(days)}d {int(hours)}h {int(minutes)}m (since {boot_time.strftime('%Y-%m-%d %H:%M:%S')} IRST)",
                "platform":
                f"{platform.system()} {platform.release()} ({platform.machine()})",
                "python": platform.python_version(),
                "gpus": gpus
            }

            # Save log (atomic: this file is rewritten on every sample).
            _save_json(SYS_LOG_FILE, sysinfo)

            return sysinfo

        except Exception as e:
            return {"error": str(e)}

    async def format_sysinfo(info):
        lines = ["🖥️ **System Info Report**", "-----------------------------"]

        # CPU
        cpu = info.get("cpu", {})
        lines.append(
            f"⚡ **CPU:** ({cpu.get('cores')} cores / {cpu.get('threads')} threads)"
        )
        lines.append(
            f"Usage per core: {', '.join(f'{p}%' for p in cpu.get('per_core_usage', []))}"
        )
        lines.append(
            f"Frequency: {cpu.get('freq', 'N/A')} MHz\n-----------------------------"
        )

        # Memory
        mem = info.get("memory", {})
        lines.append(
            f"💾 **Memory:** {(mem.get('used') or 0) / 1e9:.2f}GB/{(mem.get('total') or 0) / 1e9:.2f}GB ({mem.get('percent', 0)}%)"
        )
        lines.append(
            f"🔄 Swap: {mem.get('swap_used') or 0:.2f}B/{mem.get('swap_total') or 0:.2f}B ({mem.get('swap_percent',0)}%)\n-----------------------------"
        )

        # Disks
        lines.append("📀 **Disks:**")
        for d in info.get("disks", []):
            lines.append(
                f" - {d['device']} ({d['mount']}) {d['used']/1e6:.2f}MB/{d['total']/1e9:.2f}GB ({d['percent']}%)"
            )
        lines.append("-----------------------------")

        # Network
        net = info.get("network", {})
        lines.append(
            f"📡 **Network:** Sent {net.get('sent')/1e6:.2f}MB | Recv {net.get('recv')/1e6:.2f}MB | Conns: {net.get('connections')}"
        )
        lines.append("-----------------------------")

        # GPU
        gpus = info.get("gpus", [])
        if gpus:
            lines.append("🎮 **GPU(s):**")
            for gpu in gpus:
                lines.append(
                    f" - {gpu['name']}: Load {gpu['load']}% | Mem {gpu['mem_used']}/{gpu['mem_total']}MB | Temp {gpu['temp']}°C"
                )
            lines.append("-----------------------------")

        # Uptime / Platform
        lines.append(f"⏱️ **Uptime:** {info.get('uptime')}")
        lines.append(f"💻 **Platform:** {info.get('platform')}")
        lines.append(f"🐍 **Python:** {info.get('python')}")
        lines.append("-----------------------------")

        return "\n".join(lines)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!sysinfo$"))
    async def sysinfo_cmd(event):
        info = await collect_sysinfo()
        if info.get("error"):
            # format_sysinfo() divided None by 1e9 and raised, so the command
            # used to fail with no reply at all when collection broke.
            await event.edit(f"❌ Could not collect system info: {info['error']}")
            return
        msg = await format_sysinfo(info)
        await event.reply(msg)
        await event.delete()

    # -----------------------------
    # Optional background snapshot log
    # -----------------------------
    # Opt-in (SYSINFO_AUTOLOG=1), was unconditional every 5s. Nothing reads the
    # snapshot except this module, and on Replit's small CPU quota a permanent
    # 5s wakeup that rewrites a file is pure overhead. !sysinfo collects on
    # demand anyway, so when enabled the interval is a minute.
    if os.environ.get("SYSINFO_AUTOLOG") == "1":
        async def auto_log():
            while True:
                try:
                    await collect_sysinfo()
                except Exception as e:
                    print(f"[sysinfo] auto log failed: {e}")
                await asyncio.sleep(60)

        asyncio.create_task(auto_log())
