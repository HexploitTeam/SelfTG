"""!dnsprobe: bulk DNS enumeration, written to a per-run text file."""
from telethon import events
import Com.core.tgsend as tgsend
import os
import json
import asyncio
import dns.resolver
from datetime import datetime

__HELP__ = "!dnsprobe <domain1> <domain2> ... → Bulk DNS record enumerator (A, AAAA, MX, TXT, CNAME)\n!dnsprobe del <ID> → Delete a previous probe file by ID"

MODE_FOLDER = "mode/dns"
os.makedirs(MODE_FOLDER, exist_ok=True)
ID_FILE = os.path.join(MODE_FOLDER, "dns_id.txt")
if not os.path.exists(ID_FILE):
    with open(ID_FILE, "w") as f:
        f.write("0")

active_dns_tasks = {}  # id: task_info


def setup(client, my_id):

    def get_next_id():
        with open(ID_FILE, "r") as f:
            last_id = int(f.read().strip())
        next_id = last_id + 1
        with open(ID_FILE, "w") as f:
            f.write(str(next_id))
        return next_id

    async def probe_domain(domain):
        records = {}
        for rtype in ["A", "AAAA", "MX", "TXT", "CNAME"]:
            try:
                answers = dns.resolver.resolve(domain, rtype, lifetime=5)
                records[rtype] = [str(r.to_text()) for r in answers]
            except Exception:
                records[rtype] = []
        return records

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!dnsprobe(?:\s+(.+))?"))
    async def dnsprobe_handler(event):
        try:
            args = event.pattern_match.group(1)
            if not args:
                await event.reply(
                    "❌ Provide at least one domain or use !dnsprobe del <ID>")
                return

            parts = args.split()
            if parts[0].lower() == "del":
                del_id = int(parts[1])
                for filename in os.listdir(MODE_FOLDER):
                    if filename.startswith(f"{del_id}_dnsprobe_"):
                        os.remove(os.path.join(MODE_FOLDER, filename))
                        await event.edit(
                            f"✅ Deleted DNS probe file with ID {del_id}")
                        return
                await event.edit(f"❌ No DNS probe found with ID {del_id}")
                return

            domains = parts
            probe_id = get_next_id()
            now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            temp_file = os.path.join(MODE_FOLDER,
                                     f"{probe_id}_dnsprobe_{now}.txt")

            await event.edit(
                f"⏳ Probing {len(domains)} domain(s)... Task ID: {probe_id}")

            results = []
            for domain in domains:
                records = await probe_domain(domain)
                result_str = f"Domain: {domain}\n"
                for rtype, values in records.items():
                    result_str += f"  {rtype}: {', '.join(values) if values else 'None'}\n"
                result_str += "\n"
                results.append(result_str)

            with open(temp_file, "w", encoding="utf-8") as f:
                f.writelines(results)

            active_dns_tasks[probe_id] = {
                "file": temp_file,
                "domains": domains,
                "timestamp": now
            }

            await client.send_file(await tgsend.peer(event),
                temp_file,
                caption=f"✅ DNS Probe complete. Task ID: {probe_id}",
                reply_to=event.id)
            await event.delete()

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
