"""!subenum: certificate-transparency subdomain enumeration with DNS checks.

Two keyless CT sources, because one is not reliable enough: crt.sh is the richer
source and returns 502 often, Cert Spotter's anonymous tier is stable but allows
10 requests an hour. crt.sh is asked first, Cert Spotter answers when it fails.

A wildcard DNS record makes every DNS check meaningless -- a made-up label would
"resolve" too -- so it is probed first and reported instead of listing hundreds
of false positives. DNS validation runs off the event loop with bounded
concurrency, and the name count is capped so a huge certificate set cannot turn
into a thousand resolver calls on the free tier.
"""
from telethon import events
import Com.core.tgsend as tgsend
from Com.core import brand, recon
from Com.core.reply import say
import asyncio
import json
import logging
import os
import socket
import uuid
from datetime import datetime

import Com.core.api as api
from Com.core.storage import save_json

log = logging.getLogger("selftg.subenum")

__HELP__ = (
    "!subenum <domain> → Enumerate subdomains (crt.sh → Cert Spotter) and send "
    "the active ones as a TXT file.\n"
    "!subenum del <ID> → Delete a previously saved subdomain TXT file")
__CATEGORY__ = "Recon & Discovery"

LOG_DIR = "mode/subenum_logs"
ACTIVE_FILE = "mode/subenum_active.json"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs("mode", exist_ok=True)

CRT_URL = "https://crt.sh/"
CERTSPOTTER_URL = "https://api.certspotter.com/v1/issuances"
CT_CACHE_TTL = 3600
MAX_NAMES = 500
MAX_VALIDATE = 300
DNS_CONCURRENCY = 50
DNS_TIMEOUT = 3


def setup(client, my_id):

    def normalise(raw_names, domain):
        """Keep names under `domain`, drop wildcards, dedupe, cap."""
        names = []
        seen = set()
        for raw in raw_names:
            name = str(raw or "").strip().lower().rstrip(".")
            if name.startswith("*."):
                name = name[2:]
            if not name or name in seen:
                continue
            if name != domain and not name.endswith("." + domain):
                continue
            if not recon.is_domain(name):
                continue
            seen.add(name)
            names.append(name)
            if len(names) >= MAX_NAMES:
                break
        return sorted(names)

    async def from_crtsh(domain):
        data = await api.fetch_json(
            CRT_URL,
            params={"q": f"%.{domain}", "output": "json"},
            provider="crt.sh",
            cache_ttl=CT_CACHE_TTL,
            timeout=30,
            retries=1,
        )
        if not isinstance(data, list):
            raise api.APIError("crt.sh did not return a list", provider="crt.sh")
        names = []
        for entry in data:
            if isinstance(entry, dict):
                names.extend(str(entry.get("name_value") or "").split("\n"))
        return names

    async def from_certspotter(domain):
        data = await api.fetch_json(
            CERTSPOTTER_URL,
            params={"domain": domain, "include_subdomains": "true",
                    "expand": "dns_names"},
            provider="certspotter",
            cache_ttl=CT_CACHE_TTL,
            timeout=20,
        )
        if not isinstance(data, list):
            raise api.APIError("Cert Spotter did not return a list",
                               provider="certspotter")
        names = []
        for entry in data:
            if isinstance(entry, dict):
                names.extend(entry.get("dns_names") or [])
        return names

    async def fetch_ct_names(domain):
        """Return (names, provider) from the first CT source that answers."""
        try:
            return normalise(await from_crtsh(domain), domain), "crt.sh"
        except api.APIError as exc:
            log.info("subenum: crt.sh failed (%s)", exc.describe())
        except Exception as exc:  # noqa: BLE001 - a bad payload is not fatal
            log.info("subenum: crt.sh crashed (%s)", type(exc).__name__)

        try:
            return normalise(await from_certspotter(domain), domain), "Cert Spotter"
        except api.APIError as exc:
            log.info("subenum: Cert Spotter failed (%s)", exc.describe())
        except Exception as exc:  # noqa: BLE001
            log.info("subenum: Cert Spotter crashed (%s)", type(exc).__name__)
        return None, None

    def resolve_one(name):
        try:
            infos = socket.getaddrinfo(name, None, proto=socket.IPPROTO_TCP)
        except OSError:
            return []
        addresses = []
        for info in infos:
            address = info[4][0]
            if address not in addresses:
                addresses.append(address)
        return addresses

    async def has_wildcard(domain):
        probe = f"{uuid.uuid4().hex[:10]}.{domain}"
        try:
            await recon.resolve_host(probe)
        except api.APIError:
            return False
        return True

    async def check_dns(names):
        """Resolve names with bounded concurrency; return 'name → ip' lines."""
        semaphore = asyncio.Semaphore(DNS_CONCURRENCY)
        loop = asyncio.get_running_loop()

        async def one(name):
            async with semaphore:
                try:
                    addresses = await asyncio.wait_for(
                        loop.run_in_executor(None, resolve_one, name),
                        timeout=DNS_TIMEOUT,
                    )
                except Exception:  # noqa: BLE001 - timeout or resolver failure
                    return None
            if not addresses:
                return None
            return f"{name} → {', '.join(addresses[:2])}"

        results = await asyncio.gather(*(one(name) for name in names))
        return [line for line in results if line]

    def load_active():
        if os.path.exists(ACTIVE_FILE):
            with open(ACTIVE_FILE, "r", encoding="utf-8") as f:
                try:
                    return json.load(f)
                except ValueError:
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
                await say(event,
                          "❌ Provide a domain or reply to a message containing "
                          "one.", name="subenum")
                return

            if arg.startswith("del"):
                parts = arg.split()
                if len(parts) != 2 or not parts[1].isdigit():
                    await say(event, "❌ Usage · "
                                     "<code>!subenum del &lt;ID&gt;</code>",
                              name="subenum", parse_mode="html")
                    return
                del_id = parts[1]
                active_data = load_active()
                entry = active_data.get(del_id)
                if entry and os.path.exists(entry["file"]):
                    os.remove(entry["file"])
                    del active_data[del_id]
                    save_active(active_data)
                    await say(event,
                              f"✅ <b>Deleted</b> · ID "
                              f"<code>{brand.esc(del_id)}</code>",
                              name="subenum", parse_mode="html")
                else:
                    await say(event,
                              f"❌ No file with ID "
                              f"<code>{brand.esc(del_id)}</code>",
                              name="subenum", parse_mode="html")
                return

            try:
                domain = recon.clean_domain(arg)
            except api.APIError as exc:
                await say(event, f"❌ {brand.esc(exc)}", name="subenum",
                          parse_mode="html")
                return

            active_data = load_active()
            for task_id, info in active_data.items():
                if info.get("domain") == domain and os.path.exists(
                        info.get("file", "")):
                    await say(event,
                              f"📄 <b>Already scanned</b> · "
                              f"<code>{brand.esc(domain)}</code>, sending the "
                              "saved file…",
                              name="subenum", parse_mode="html")
                    await client.send_file(
                        await tgsend.peer(event), info["file"],
                        caption=brand.sign(
                            f"📄 <b>Subdomains</b> · "
                            f"<code>{brand.esc(domain)}</code> · ID "
                            f"<code>{task_id}</code>",
                            "subenum"),
                        parse_mode="html")
                    return

            await say(event,
                      f"🔍 <b>Scanning subdomains</b> · "
                      f"<code>{brand.esc(domain)}</code>…",
                      name="subenum", parse_mode="html")

            names, provider = await fetch_ct_names(domain)
            if names is None:
                await say(event,
                          "❌ <b>Both certificate-transparency sources "
                          "failed</b>\n"
                          "crt.sh returns 502 often; Cert Spotter allows 10 "
                          "anonymous requests an hour. Try again later.",
                          name="subenum", parse_mode="html")
                return
            if not names:
                await say(event,
                          f"❌ No certificate names found for "
                          f"<code>{brand.esc(domain)}</code> "
                          f"<i>({brand.esc(provider)})</i>",
                          name="subenum", parse_mode="html")
                return

            wildcard = await has_wildcard(domain)
            if wildcard:
                lines = names
                note = ("Wildcard DNS is active: every label answers, so DNS "
                        "checks would be false positives. Listing CT names "
                        "only.")
            else:
                validated = names[:MAX_VALIDATE]
                lines = await check_dns(validated)
                note = ""
                if len(names) > MAX_VALIDATE:
                    note = (f"Validated the first {MAX_VALIDATE} of "
                            f"{len(names)} CT names")

            if not lines:
                await say(event,
                          f"❌ No active subdomains found for "
                          f"<code>{brand.esc(domain)}</code> "
                          f"<i>({len(names)} CT names, none resolved)</i>",
                          name="subenum", parse_mode="html")
                return

            now = datetime.now().strftime("%Y%m%d%H%M%S")
            task_id = int(now)
            file_path = os.path.join(LOG_DIR, f"{domain}_{task_id}.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                if note:
                    f.write(f"# {note}\n")
                f.write("\n".join(lines))

            active_data[task_id] = {
                "domain": domain,
                "file": file_path,
                "timestamp": now
            }
            save_active(active_data)

            summary = (f"✅ <b>{'Names' if wildcard else 'Active subdomains'}"
                       f"</b> · <code>{brand.esc(domain)}</code>\n"
                       f"<b>Found</b> · {len(lines)}")
            if note:
                summary += f"\n<i>{brand.esc(note)}</i>"
            summary += (f"\n<i>source: {brand.esc(provider)}</i>\n"
                        f"ID · <code>{task_id}</code>")

            await client.send_file(
                await tgsend.peer(event),
                file_path,
                caption=brand.sign(summary, "subenum"),
                parse_mode="html"
            )

        except Exception as e:
            log.exception("subenum: unexpected failure")
            await say(event, f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="subenum", parse_mode="html")
