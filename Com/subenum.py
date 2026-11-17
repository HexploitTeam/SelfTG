# Com/subenum.py
from telethon import events
import asyncio
import json
import logging
import os
from datetime import datetime
import socket

import Com.api as api
from Com.storage import save_json

log = logging.getLogger("selftg.subenum")

__HELP__ = (
    "!subenum <domain> → Enumerate active subdomains and send as TXT file\n"
    "!subenum del <ID> → Delete a previously saved subdomain TXT file")
__CATEGORY__ = "Recon & Discovery"

LOG_DIR = "mode/subenum_logs"
ACTIVE_FILE = "mode/subenum_active.json"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs("mode", exist_ok=True)


def setup(client, my_id):

    async def fetch_ct_subdomains(domain):
        # crt.sh is free and keyless but routinely answers 502/504 under load,
        # so the call goes through Com.api (bounded timeout + one retry) and a
        # failure is reported instead of looking like "no subdomains found".
        url = "https://crt.sh/"
        try:
            data = await api.fetch_json(
                url,
                params={"q": f"%.{domain}", "output": "json"},
                provider="crt.sh",
                timeout=25,
                retries=1,
            )
        except api.APIError as exc:
            log.info("subenum: crt.sh failed (%s)", exc.describe())
            return None
        except Exception as exc:  # noqa: BLE001
            log.info("subenum: crt.sh crashed (%s)", type(exc).__name__)
            return None

        subdomains = set()
        for entry in data if isinstance(data, list) else []:
            name = entry.get("name_value", "")
            for sub in str(name).split("\n"):
                sub = sub.strip().lower()
                if sub.endswith(domain) and len(subdomains) < 5000:
                    subdomains.add(sub)
        return sorted(subdomains)

    def check_dns(subdomain):
        try:
            ip = socket.gethostbyname(subdomain)
            return ip
        except:
            return None

    def load_active():
        if os.path.exists(ACTIVE_FILE):
            with open(ACTIVE_FILE, "r", encoding="utf-8") as f:
                try:
                    return json.load(f)
                except:
                    return {}
        return {}

    def save_active(active_data):
        save_json(ACTIVE_FILE, active_data)

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!subenum(?:\s+(.+))?"))
    async def subenum_handler(event):
        try:
            arg = event.pattern_match.group(1)
            if not arg and event.is_reply:
                reply_msg = await event.get_reply_message()
                arg = (reply_msg.text or "").strip()

            if not arg:
                await event.reply(
                    "❌ Provide a domain or reply to a message containing one.")
                return

            # Delete command
            await event.delete()

            # Handle delete command
            if arg.startswith("del"):
                parts = arg.split()
                if len(parts) != 2 or not parts[1].isdigit():
                    await event.reply("❌ Usage: !subenum del <ID>")
                    return
                del_id = parts[1]
                active_data = load_active()
                entry = active_data.get(del_id)
                if entry and os.path.exists(entry["file"]):
                    os.remove(entry["file"])
                    del active_data[del_id]
                    save_active(active_data)
                    await event.reply(
                        f"✅ Deleted subdomain file with ID {del_id}")
                else:
                    await event.reply(f"❌ File with ID {del_id} not found")
                return

            domain = arg
            active_data = load_active()

            # Check if already scanned
            for task_id, info in active_data.items():
                if info.get("domain") == domain and os.path.exists(
                        info.get("file", "")):
                    await event.reply(
                        f"📄 Already scanned **{domain}**, sending saved file..."
                    )
                    await client.send_file(
                        event.chat_id,
                        info["file"],
                        caption=f"Subdomains for **{domain}** (ID: {task_id})")
                    return

            await event.reply(f"🔍 Scanning subdomains for **{domain}**...")

            subdomains = await fetch_ct_subdomains(domain)
            if subdomains is None:
                await event.reply(
                    "❌ crt.sh (free certificate-transparency API) is unavailable or "
                    "rate limiting right now. Try again in a minute."
                )
                return
            active_subs = []
            for sub in subdomains:
                ip = await asyncio.get_event_loop().run_in_executor(
                    None, check_dns, sub)
                if ip:
                    active_subs.append(f"{sub} → {ip}")

            if not active_subs:
                await event.reply(
                    f"❌ No active subdomains found for **{domain}**")
                return

            # Save to TXT file
            now = datetime.now().strftime("%Y%m%d%H%M%S")
            task_id = int(now)
            file_path = os.path.join(LOG_DIR, f"{domain}_{task_id}.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(active_subs))

            # Save active data
            active_data[task_id] = {
                "domain": domain,
                "file": file_path,
                "timestamp": now
            }
            save_active(active_data)

            await client.send_file(
                event.chat_id,
                file_path,
                caption=f"✅ Active subdomains for **{domain}** (ID: {task_id})"
            )

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
