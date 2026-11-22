"""!dnsprobe: bulk DNS enumeration, written to a per-run text file.

The resolver calls are blocking (dnspython has no async API), so they run in the
executor. The old version called them straight from the handler: five record
types with a five-second lifetime each meant one slow domain could freeze the
whole Telethon loop for half a minute. The domain count is capped too, so a
pasted list cannot turn into minutes of resolver work on the free tier.

`!ip dns` answers a single record over DNS over HTTPS; this command is the bulk
path and keeps dnspython, which is already a pinned dependency.
"""
from telethon import events
import Com.core.tgsend as tgsend
import os
import asyncio
import dns.resolver
from datetime import datetime

from Com.core import brand
from Com.core.reply import say

__HELP__ = (
    "!dnsprobe <domain1> <domain2> ... → Bulk DNS records "
    "(A, AAAA, MX, TXT, NS, CNAME, SOA), sent as a TXT file.\n"
    "!dnsprobe del <ID> → Delete a previous probe file by ID")
__CATEGORY__ = "Recon & Discovery"

MODE_FOLDER = "mode/dns"
os.makedirs(MODE_FOLDER, exist_ok=True)
ID_FILE = os.path.join(MODE_FOLDER, "dns_id.txt")
if not os.path.exists(ID_FILE):
    with open(ID_FILE, "w") as f:
        f.write("0")

RECORD_TYPES = ("A", "AAAA", "MX", "TXT", "NS", "CNAME", "SOA")
MAX_DOMAINS = 25
RESOLVER_LIFETIME = 5

active_dns_tasks = {}  # id: task_info


def setup(client, my_id):

    def get_next_id():
        with open(ID_FILE, "r") as f:
            last_id = int(f.read().strip())
        next_id = last_id + 1
        with open(ID_FILE, "w") as f:
            f.write(str(next_id))
        return next_id

    def probe_domain_sync(domain):
        """Blocking: resolve every record type; called in the executor."""
        records = {}
        resolver = dns.resolver.Resolver()
        for rtype in RECORD_TYPES:
            try:
                answers = resolver.resolve(
                    domain, rtype, lifetime=RESOLVER_LIFETIME)
                records[rtype] = [str(r.to_text()) for r in answers]
            except Exception:  # noqa: BLE001 - a missing type is normal
                records[rtype] = []
        return records

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!dnsprobe(?:\s+(.+))?"))
    async def dnsprobe_handler(event):
        try:
            args = event.pattern_match.group(1)
            if not args:
                await say(
                    event,
                    "❌ Provide at least one domain or use "
                    "<code>!dnsprobe del &lt;ID&gt;</code>",
                    name="dnsprobe",
                    parse_mode="html",
                )
                return

            parts = args.split()
            if parts[0].lower() == "del":
                if len(parts) != 2 or not parts[1].isdigit():
                    await say(
                        event,
                        "❌ Usage · <code>!dnsprobe del &lt;ID&gt;</code>",
                        name="dnsprobe",
                        parse_mode="html",
                    )
                    return
                del_id = parts[1]
                for filename in os.listdir(MODE_FOLDER):
                    if filename.startswith(f"{del_id}_dnsprobe_"):
                        os.remove(os.path.join(MODE_FOLDER, filename))
                        active_dns_tasks.pop(del_id, None)
                        await say(
                            event,
                            f"✅ <b>Deleted DNS probe file</b> "
                            f"<code>{brand.esc(del_id)}</code>",
                            name="dnsprobe",
                            parse_mode="html",
                        )
                        return
                await say(
                    event,
                    f"❌ <b>No DNS probe found with ID</b> "
                    f"<code>{brand.esc(del_id)}</code>",
                    name="dnsprobe",
                    parse_mode="html",
                )
                return

            domains = parts
            if len(domains) > MAX_DOMAINS:
                await say(
                    event,
                    f"❌ <b>Too many domains.</b> {len(domains)} given, "
                    f"{MAX_DOMAINS} is the per-run cap on the free tier.",
                    name="dnsprobe",
                    parse_mode="html",
                )
                return

            probe_id = get_next_id()
            now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            temp_file = os.path.join(MODE_FOLDER,
                                     f"{probe_id}_dnsprobe_{now}.txt")

            await say(
                event,
                f"⏳ <b>Probing</b> <code>{len(domains)}</code> domain(s)\n"
                f"<b>Task ID</b> · <code>{probe_id}</code>",
                name="dnsprobe",
                parse_mode="html",
            )

            loop = asyncio.get_running_loop()
            results = []
            answered = 0
            for domain in domains:
                try:
                    records = await asyncio.wait_for(
                        loop.run_in_executor(None, probe_domain_sync, domain),
                        timeout=len(RECORD_TYPES) * RESOLVER_LIFETIME + 5,
                    )
                except asyncio.TimeoutError:
                    results.append(f"Domain: {domain}\n  resolver timed out\n\n")
                    continue

                if any(records.values()):
                    answered += 1
                result_str = f"Domain: {domain}\n"
                for rtype, values in records.items():
                    result_str += (f"  {rtype}: "
                                   f"{', '.join(values) if values else 'None'}\n")
                result_str += "\n"
                results.append(result_str)

            with open(temp_file, "w", encoding="utf-8") as f:
                f.writelines(results)

            active_dns_tasks[probe_id] = {
                "file": temp_file,
                "domains": domains,
                "timestamp": now
            }

            await client.send_file(
                await tgsend.peer(event),
                temp_file,
                caption=brand.sign(
                    "✅ <b>DNS Probe complete</b> · task "
                    f"<code>{brand.esc(probe_id)}</code>\n"
                    f"<b>Domains</b> · {len(domains)} · "
                    f"<b>with records</b> · {answered}",
                    "dnsprobe",
                ),
                parse_mode="html",
                reply_to=event.id,
            )

        except Exception as e:
            await say(
                event,
                f"❌ <b>DNS probe failed.</b> {brand.esc(e)}",
                name="dnsprobe",
                parse_mode="html",
            )
