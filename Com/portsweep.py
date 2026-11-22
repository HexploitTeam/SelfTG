"""!portsweep: passive exposure first, an explicit bounded TCP scan second.

Two different questions, two different paths:

* `!portsweep <host>` asks Shodan's InternetDB what was already seen. Free,
  keyless, no account; the data is weekly, so it costs the target nothing and
  the account never touches it. This is the default now: the old command fired
  1,024 sequential TCP connections from the Repl on every invocation, which was
  slow, noisy and impossible to justify for a routine lookup.
* `!portsweep <host> <start-end>` performs a real connect scan, because that is
  the only way to see a host Shodan has not indexed. It is capped at 256 ports,
  runs 64 at a time, and refuses private/loopback ranges. Traffic comes from the
  Repl's IP: only scan a host you own or have written permission to test.

Both paths stay owner-only through `from_users=my_id`; the result file and its
`del <ID>` cleanup behave as before.
"""
import asyncio
import logging
import os
import time
from datetime import datetime

from telethon import events

import Com.core.api as api
import Com.core.tgsend as tgsend
from Com.core import brand, recon
from Com.core.reply import say

__HELP__ = (
    "!portsweep <host> → Passive exposure: open ports, hostnames, CVEs and tags "
    "from Shodan InternetDB (free, keyless, weekly).\n"
    "!portsweep <host> <start-end> → Active TCP scan of up to 256 ports from "
    "this Repl. Only scan hosts you own or may test.\n"
    "!portsweep del <ID> → Delete a saved scan result."
)
__CATEGORY__ = "Recon & Discovery"

log = logging.getLogger("selftg.portsweep")

SAVE_FOLDER = "mode/portsweep"
os.makedirs(SAVE_FOLDER, exist_ok=True)

PASSIVE_URL = "https://internetdb.shodan.io/{ip}"
PASSIVE_CACHE_TTL = 6 * 3600
MAX_ACTIVE_PORTS = 256
ACTIVE_CONCURRENCY = 64
CONNECT_TIMEOUT = 1.5
MAX_PASSIVE_PORTS = 24

active_scans = {}  # scan_id: {"host", "ports", "task", "file"}


#------------------------------
#Rendering
#------------------------------

def _save_path(scan_id):
    return os.path.join(SAVE_FOLDER, f"portsweep_{scan_id}.txt")


def _render_passive(host, ip, data, scan_id):
    ports = sorted({int(port) for port in data.get("ports") or []
                    if str(port).isdigit()})
    hostnames = [str(name) for name in data.get("hostnames") or []]
    vulns = [str(cve) for cve in data.get("vulns") or []]
    tags = [str(tag) for tag in data.get("tags") or []]

    lines = [f"🛰 <b>Passive exposure</b> · <code>{brand.esc(ip)}</code>"]
    if host != ip:
        lines.append(f"<b>Host</b> · <code>{brand.esc(host)}</code>")

    if ports:
        lines.append(f"<b>Open ports</b> · {len(ports)}")
        for port in ports[:MAX_PASSIVE_PORTS]:
            service = recon.service_name(port)
            lines.append(
                f"<code>{port}</code>" + (f" · {brand.esc(service)}" if service else "")
            )
        if len(ports) > MAX_PASSIVE_PORTS:
            lines.append(f"<i>… {len(ports) - MAX_PASSIVE_PORTS} more</i>")
    else:
        lines.append("<b>Open ports</b> · none recorded")

    if hostnames:
        lines.append("<b>Hostnames</b> · " + ", ".join(
            f"<code>{brand.esc(name)}</code>" for name in hostnames[:8]
        ))
        if len(hostnames) > 8:
            lines.append(f"<i>… {len(hostnames) - 8} more hostnames</i>")

    if vulns:
        lines.append(f"⚠️ <b>Known vulnerabilities</b> · {len(vulns)}")
        for cve in vulns[:10]:
            lines.append(f"<code>{brand.esc(cve)}</code>")
        if len(vulns) > 10:
            lines.append(f"<i>… {len(vulns) - 10} more</i>")

    if tags:
        lines.append(f"<b>Tags</b> · {brand.esc(', '.join(tags[:8]))}")

    lines.append(
        f"<i>Shodan InternetDB · passive, updated weekly · scan "
        f"{brand.esc(scan_id)}</i>"
    )
    return "\n".join(lines)


def _write_report(scan_id, body):
    path = _save_path(scan_id)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
        handle.write("\n")
    return path


#------------------------------
#Passive
#------------------------------

async def passive_lookup(host):
    """Return (text, ip) for a passive lookup, or (None, ip) when unseen."""
    ip = host
    if not recon.is_ip(ip):
        ip = (await recon.resolve_host(host))[0]

    try:
        data = await api.fetch_json(
            PASSIVE_URL.format(ip=ip),
            provider="shodan-internetdb",
            cache_ttl=PASSIVE_CACHE_TTL,
            timeout=12,
        )
    except api.APIError as exc:
        if exc.status == 404:
            return None, ip
        raise

    if not isinstance(data, dict):
        raise api.APIError("unexpected InternetDB payload",
                           provider="shodan-internetdb")
    scan_id = str(int(datetime.now().timestamp() * 1000))
    text = _render_passive(host, ip, data, scan_id)
    try:
        _write_report(scan_id, brand.plain(text))
    except OSError:
        # The card is the answer; a full disk must not swallow it
        log.info("portsweep: could not write the passive report")
    return text, ip


#------------------------------
#Active scan
#------------------------------

async def _check_port(host, port, semaphore):
    async with semaphore:
        started = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=CONNECT_TIMEOUT
            )
            latency = int((time.monotonic() - started) * 1000)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            return port, latency
        except (asyncio.TimeoutError, OSError):
            return None
        except Exception:  # noqa: BLE001 - one port must not abort the scan
            return None


async def scan_ports(client, peer, host, ip, ports, scan_id):
    """Scan `ports` on `ip` with bounded concurrency, then send the report."""
    started = time.monotonic()
    semaphore = asyncio.Semaphore(ACTIVE_CONCURRENCY)
    results = await asyncio.gather(
        *(_check_port(ip, port, semaphore) for port in ports)
    )
    found = sorted((entry for entry in results if entry), key=lambda item: item[0])
    elapsed = int(time.monotonic() - started)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"Host: {host}" + (f" ({ip})" if host != ip else ""),
        f"Scan ID: {scan_id}",
        f"Date: {now}",
        f"Range: {ports[0]}-{ports[-1]} ({len(ports)} ports, {elapsed}s)",
        "Open ports:",
    ]
    if found:
        for port, latency in found:
            service = recon.service_name(port)
            label = f"  {port}" + (f"/{service}" if service else "")
            lines.append(f"{label}  ({latency} ms)")
    else:
        lines.append("  none")
    lines.append("")
    lines.append(
        "Only scan hosts you own or have written permission to test; "
        "the connections came from this Repl's IP."
    )

    try:
        path = _write_report(scan_id, "\n".join(lines))
        await client.send_file(
            peer,
            path,
            caption=brand.sign(
                f"✅ <b>Scan complete</b> · {brand.esc(host)}\n"
                f"<b>Open</b> · {len(found)} of {len(ports)} · "
                f"<code>{elapsed}s</code>\n"
                f"Scan ID · <code>{brand.esc(scan_id)}</code>",
                "portsweep",
            ),
            parse_mode="html",
        )
    except Exception as exc:  # noqa: BLE001 - report delivery is best effort
        log.info("portsweep: could not deliver report (%s)", type(exc).__name__)
        try:
            await client.send_message(
                peer,
                brand.sign(
                    f"✅ <b>Scan complete</b> · {brand.esc(host)}\n"
                    f"<b>Open</b> · {len(found)} of {len(ports)}\n"
                    f"<i>Report file could not be sent.</i>",
                    "portsweep",
                ),
                parse_mode="html",
            )
        except Exception:  # noqa: BLE001
            log.info("portsweep: completion message also failed")
    finally:
        active_scans.pop(scan_id, None)


#------------------------------
#Command
#------------------------------

def setup(client, my_id):

    async def delete_scan(event, del_id):
        info = active_scans.pop(del_id, None)
        if info:
            task = info.get("task")
            if task and not task.done():
                task.cancel()
        path = _save_path(del_id)
        if os.path.exists(path):
            os.remove(path)
            await say(
                event,
                f"✅ <b>Deleted portsweep result</b> <code>{brand.esc(del_id)}</code>",
                name="portsweep",
                parse_mode="html",
            )
            return
        await say(
            event,
            f"❌ <b>Scan ID not found.</b> <code>{brand.esc(del_id)}</code>",
            name="portsweep",
            parse_mode="html",
        )

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!portsweep\s+(.+)"))
    async def portsweep_cmd(event):
        args = event.pattern_match.group(1).strip()
        parts = args.split()

        if parts[0].lower() == "del":
            if len(parts) < 2:
                await say(event,
                          "❌ Usage · <code>!portsweep del &lt;ID&gt;</code>",
                          name="portsweep", parse_mode="html")
                return
            await delete_scan(event, parts[1])
            return

        try:
            host = recon.clean_host(parts[0])
        except api.APIError as exc:
            await say(event, f"❌ {brand.esc(exc)}", name="portsweep",
                      parse_mode="html")
            return

        # No range: passive. This is the cheap, non-touching path.
        if len(parts) == 1:
            try:
                text, ip = await passive_lookup(host)
            except api.APIError as exc:
                await say(
                    event,
                    f"❌ <b>Passive lookup failed.</b> {brand.esc(exc)}\n"
                    "<i>InternetDB is a single keyless endpoint; retry later "
                    "or use an explicit port range.</i>",
                    name="portsweep",
                    parse_mode="html",
                )
                return
            if text is None:
                await say(
                    event,
                    f"🛰 <b>No passive data</b> · <code>{brand.esc(host)}</code> "
                    f"(<code>{brand.esc(ip)}</code>)\n"
                    "Shodan has not indexed this host. An active scan is a "
                    "separate, explicit choice:\n"
                    "<code>!portsweep "
                    f"{brand.esc(host)} 1-256</code>",
                    name="portsweep",
                    parse_mode="html",
                )
                return
            await say(event, text, name="portsweep", parse_mode="html")
            return

        # Explicit range: active scan, capped and announced.
        try:
            if "-" in parts[1]:
                start_port, end_port = map(int, parts[1].split("-", 1))
            else:
                start_port = end_port = int(parts[1])
        except ValueError:
            await say(event,
                      "❌ <b>Invalid port range.</b> Use <code>80</code> or "
                      "<code>1-256</code>.",
                      name="portsweep", parse_mode="html")
            return

        if not (1 <= start_port <= end_port <= 65535):
            await say(event,
                      "❌ Invalid port range. Use <code>1-65535</code> with "
                      "start ≤ end.",
                      name="portsweep", parse_mode="html")
            return

        ports = list(range(start_port, end_port + 1))
        if len(ports) > MAX_ACTIVE_PORTS:
            await say(
                event,
                f"❌ <b>Range too large.</b> Active scans are capped at "
                f"{MAX_ACTIVE_PORTS} ports per run (asked for {len(ports)}).\n"
                f"Split it, or use <code>!portsweep {brand.esc(host)}</code> "
                "for the passive list.",
                name="portsweep", parse_mode="html",
            )
            return

        if any(info.get("task") and not info["task"].done()
               for info in active_scans.values()):
            await say(event,
                      "❌ <b>A scan is already running.</b> Wait for it, or "
                      "<code>!portsweep del &lt;ID&gt;</code> to cancel it.",
                      name="portsweep", parse_mode="html")
            return

        try:
            ip = host if recon.is_ip(host) else (
                await recon.resolve_host(host))[0]
        except api.APIError as exc:
            await say(event, f"❌ <b>Could not resolve</b> "
                             f"<code>{brand.esc(host)}</code> · {brand.esc(exc)}",
                      name="portsweep", parse_mode="html")
            return

        if recon.is_private(ip):
            await say(
                event,
                f"❌ <b>Refusing to scan a private address</b> "
                f"(<code>{brand.esc(ip)}</code>).\n"
                "<i>Active scans are for hosts you control on the public "
                "internet.</i>",
                name="portsweep", parse_mode="html",
            )
            return

        scan_id = str(int(datetime.now().timestamp() * 1000))
        await say(
            event,
            f"⏳ <b>Active scan started</b> · {brand.esc(host)}\n"
            f"<b>Range</b> · <code>{start_port}-{end_port}</code> "
            f"({len(ports)} ports)\n"
            f"<b>Scan ID</b> · <code>{scan_id}</code>\n"
            "<i>Only scan hosts you own or may test: the traffic leaves from "
            "this Repl's IP.</i>",
            name="portsweep", parse_mode="html",
        )

        peer = await tgsend.peer(event)
        task = asyncio.create_task(
            scan_ports(client, peer, host, ip, ports, scan_id))
        active_scans[scan_id] = {
            "host": host,
            "ports": ports,
            "task": task,
            "file": _save_path(scan_id),
        }
