"""!portsweep: bounded TCP port scan with progress messages."""
from telethon import events
import asyncio
import socket
import os
import json
from datetime import datetime

__HELP__ = "!portsweep <host> [start_port-end_port] → Scan ports safely and get open/filtered list.\n!portsweep del <ID> → Delete saved scan result."

SAVE_FOLDER = "mode/portsweep"
os.makedirs(SAVE_FOLDER, exist_ok=True)

active_scans = {
}  # id: {"host": host, "ports": list, "task": Task, "file": filename}


def setup(client, my_id):

    async def scan_ports(chat_id, host, ports, scan_id):
        open_ports = []
        for port in ports:
            try:
                conn = asyncio.open_connection(host, port)
                reader, writer = await asyncio.wait_for(conn, timeout=1)
                open_ports.append(port)
                writer.close()
                await writer.wait_closed()
            except:
                continue

        now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{SAVE_FOLDER}/portsweep_{scan_id}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(
                f"Host: {host}\nScan ID: {scan_id}\nDate: {now}\nOpen Ports:\n"
            )
            for p in open_ports:
                f.write(f"{p}\n")

        await client.send_file(
            chat_id,
            filename,
            caption=f"✅ Portsweep completed for {host}. Scan ID: {scan_id}")
        active_scans.pop(scan_id, None)

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!portsweep\s+(.+)"))
    async def portsweep_cmd(event):
        args = event.pattern_match.group(1).strip()
        try:
            await event.delete()

            if args.startswith("del"):
                del_id = args.split()[1]
                info = active_scans.get(del_id)
                if info:
                    file = info.get("file")
                    task = info.get("task")
                    if task:
                        task.cancel()
                    if file and os.path.exists(file):
                        os.remove(file)
                    active_scans.pop(del_id)
                    await event.reply(f"✅ Deleted portsweep result {del_id}")
                    return
                else:
                    await event.reply(f"❌ Scan ID {del_id} not found")
                    return

            parts = args.split()
            host = parts[0]
            if len(parts) > 1:
                if "-" in parts[1]:
                    start_port, end_port = map(int, parts[1].split("-", 1))
                else:
                    start_port = end_port = int(parts[1])
            else:
                start_port, end_port = 1, 1024

            if not (1 <= start_port <= end_port <= 65535):
                await event.reply(
                    "❌ Invalid port range. Use 1-65535 with start <= end.")
                return

            ports = list(range(start_port, end_port + 1))
            scan_id = str(int(datetime.now().timestamp() * 1000))
            task = asyncio.create_task(
                scan_ports(event.chat_id, host, ports, scan_id))
            active_scans[scan_id] = {
                "host": host,
                "ports": ports,
                "task": task,
                "file": f"{SAVE_FOLDER}/portsweep_{scan_id}.txt"
            }
            await event.reply(
                f"⏳ Portsweep started for {host}. Scan ID: {scan_id}")

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
