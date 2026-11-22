"""!ip: geolocation, DNS, reverse lookup, port and ping checks.

Everything here is keyless. Geolocation runs ipwho.is, then ip-api.com, then
ipinfo.io -- three independent free providers, so one 429 or one outage does not
end the command. DNS and PTR lookups go over DNS over HTTPS (`Com/core/recon.py`)
rather than a local resolver, so they keep working when the platform's resolver
is the thing that is broken.

`!ip info` adds the RDAP network the address belongs to. Registration data
itself is `!rdap`; this only puts the owning network next to the geography.
"""
import asyncio
import shlex
import socket

from telethon import events

import Com.core.api as api
from Com.core import brand, recon
from Com.core.reply import say

__HELP__ = (
    "!ip <subcommand> [args] → IP and domain intelligence.\n"
    "Subcommands:\n"
    "  geo <IP|host>          → Geolocation, ASN and network owner\n"
    "  dns <domain> [type]    → DNS over HTTPS (A AAAA MX TXT NS SOA CNAME ...)\n"
    "  resolve <host>         → Resolve a hostname to its addresses\n"
    "  reverse <IP>           → PTR (reverse DNS) lookup\n"
    "  info <IP|host>         → Geo + reverse DNS + RDAP network\n"
    "  ping <host>            → ICMP ping, when the platform allows it\n"
    "  port <host> <port>     → Single TCP port check\n"
    "  help                   → Show this help.\n"
    "Examples:\n"
    "  !ip geo 8.8.8.8\n"
    "  !ip dns example.com MX\n"
    "  !ip dns _dmarc.example.com TXT\n"
    "  !ip resolve github.com\n"
    "  !ip reverse 1.1.1.1\n"
    "  !ip info 1.1.1.1\n"
)
__CATEGORY__ = "Information"

GEO_CACHE_TTL = 24 * 3600                      # geo data barely changes
IPWHO_URL = "https://ipwho.is/{ip}"            # keyless, HTTPS, 1,000/day
IP_API_URL = "http://ip-api.com/json/{ip}"     # keyless, HTTP-only, 45/min
IPINFO_URL = "https://ipinfo.io/{ip}/json"     # keyless, 50,000/month


#------------------------------
#Validation
#------------------------------

def is_valid_ip(ip):
    return recon.is_ip(ip)


def is_valid_domain(domain):
    return recon.is_domain(domain)


#------------------------------
#Geolocation
#------------------------------

def _coord(value):
    """Four decimals is already ~11 m; the providers return 7."""
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return brand.esc(value)


def _render_geo(ip, record, source):
    country = record.get("country") or "N/A"
    code = record.get("country_code") or ""
    flag = record.get("flag") or ""
    country_line = f"<b>Country</b> · {brand.esc(country)}"
    if code:
        country_line += f" ({brand.esc(code)})"
    if flag:
        country_line += f" {brand.esc(flag)}"

    lines = [
        f"📍 <b>Geolocation</b> · <code>{brand.esc(ip)}</code>",
        country_line,
        f"<b>Region</b> · {brand.esc(record.get('region') or 'N/A')}",
        f"<b>City</b> · {brand.esc(record.get('city') or 'N/A')}",
        f"<b>ISP</b> · {brand.esc(record.get('isp') or 'N/A')}",
        f"<b>Org</b> · {brand.esc(record.get('org') or 'N/A')}",
    ]

    asn = record.get("asn")
    if asn:
        asn_line = f"<b>ASN</b> · <code>AS{brand.esc(asn)}</code>"
        if record.get("as_name"):
            asn_line += f" · {brand.esc(record['as_name'])}"
        lines.append(asn_line)

    lines.append(f"<b>Timezone</b> · {brand.esc(record.get('timezone') or 'N/A')}")
    if record.get("lat") is not None and record.get("lon") is not None:
        lines.append(
            f"<b>Coordinates</b> · <code>{_coord(record['lat'])}, "
            f"{_coord(record['lon'])}</code>"
        )
    if record.get("hostname"):
        lines.append(f"<b>Hostname</b> · {brand.esc(record['hostname'])}")
    if record.get("hosting"):
        lines.append("<b>Hosting</b> · yes (datacenter range)")
    lines.append(f"<i>source: {brand.esc(source)}, cached {GEO_CACHE_TTL // 3600}h</i>")
    return "\n".join(lines)


async def _geo_ipwho(ip):
    data = await api.fetch_json(
        IPWHO_URL.format(ip=ip), provider="ipwho.is",
        cache_ttl=GEO_CACHE_TTL, timeout=10,
    )
    if not isinstance(data, dict):
        raise api.APIError("unexpected payload", provider="ipwho.is")
    if not data.get("success", False):
        raise api.APIError(data.get("message") or "lookup failed",
                           provider="ipwho.is")
    connection = data.get("connection") or {}
    timezone = data.get("timezone") or {}
    return _render_geo(ip, {
        "country": data.get("country"),
        "country_code": data.get("country_code"),
        "flag": (data.get("flag") or {}).get("emoji"),
        "region": data.get("region"),
        "city": data.get("city"),
        "isp": connection.get("isp"),
        "org": connection.get("org"),
        "asn": connection.get("asn"),
        "as_name": connection.get("org"),
        "timezone": timezone.get("id"),
        "lat": data.get("latitude"),
        "lon": data.get("longitude"),
        "hostname": None,
        "hosting": None,
    }, "ipwho.is")


async def _geo_ipapi(ip):
    data = await api.fetch_json(
        IP_API_URL.format(ip=ip),
        params={"fields": "status,message,country,countryCode,regionName,city,"
                          "isp,org,as,lat,lon,timezone,hosting"},
        provider="ip-api.com", cache_ttl=GEO_CACHE_TTL, timeout=8,
    )
    if not isinstance(data, dict):
        raise api.APIError("unexpected payload", provider="ip-api.com")
    if data.get("status") == "fail":
        raise api.APIError(data.get("message") or "lookup failed",
                           provider="ip-api.com")
    as_field = data.get("as") or ""
    asn = as_field[2:].split(" ", 1)[0] if as_field.startswith("AS") else None
    return _render_geo(ip, {
        "country": data.get("country"),
        "country_code": data.get("countryCode"),
        "region": data.get("regionName"),
        "city": data.get("city"),
        "isp": data.get("isp"),
        "org": data.get("org"),
        "asn": asn,
        "as_name": as_field,
        "timezone": data.get("timezone"),
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "hosting": data.get("hosting"),
    }, "ip-api.com")


async def _geo_ipinfo(ip):
    data = await api.fetch_json(
        IPINFO_URL.format(ip=ip), provider="ipinfo.io",
        cache_ttl=GEO_CACHE_TTL, timeout=10,
    )
    if not isinstance(data, dict):
        raise api.APIError("unexpected payload", provider="ipinfo.io")
    if data.get("error"):
        raise api.APIError("lookup failed", provider="ipinfo.io")
    lat, _, lon = (data.get("loc") or "").partition(",")
    org = data.get("org") or ""
    asn = org.split(" ", 1)[0].lstrip("AS") if org.startswith("AS") else None
    return _render_geo(ip, {
        "country": data.get("country"),
        "region": data.get("region"),
        "city": data.get("city"),
        "isp": org or None,
        "org": org or None,
        "asn": asn,
        "as_name": org if asn else None,
        "timezone": data.get("timezone"),
        "lat": lat or None,
        "lon": lon or None,
        "hostname": data.get("hostname"),
    }, "ipinfo.io")


async def geo_lookup(target):
    """Geolocation for an address or a hostname.

    Returns ``(text, ip)``. The hostname is resolved first so `!ip geo
    example.com` answers instead of calling it an invalid IP.
    """
    ip = target
    if not recon.is_ip(ip):
        try:
            ip = (await recon.resolve_host(target))[0]
        except api.APIError as exc:
            return (f"❌ <b>Could not resolve</b> "
                    f"<code>{brand.esc(target)}</code> · {brand.esc(exc)}"), target
    try:
        text = await api.first_success([
            ("ipwho.is", lambda: _geo_ipwho(ip)),
            ("ip-api.com", lambda: _geo_ipapi(ip)),
            ("ipinfo.io", lambda: _geo_ipinfo(ip)),
        ])
    except api.APIError as exc:
        return (
            f"❌ <b>Geolocation failed.</b> {brand.esc(exc)}\n"
            "All three free providers are down or rate limited; nothing was "
            "cached."
        ), ip
    return text, ip


#------------------------------
#DNS
#------------------------------

def _type_help():
    return ", ".join(sorted(recon.DOH_TYPES))


async def dns_lookup(domain, record_type="A"):
    record_type = (record_type or "A").upper()
    if record_type not in recon.DOH_TYPES:
        return (
            f"❌ <b>Unsupported record type</b> "
            f"<code>{brand.esc(record_type)}</code>\n"
            f"Use one of · <code>{_type_help()}</code>"
        )

    try:
        result = await recon.doh(domain, record_type)
    except api.APIError as exc:
        return (
            f"❌ <b>DNS lookup failed.</b> {brand.esc(exc)}\n"
            "Both DNS over HTTPS providers failed; try again in a minute."
        )

    head = (f"📡 <b>DNS {brand.esc(record_type)}</b> · "
            f"<code>{brand.esc(domain)}</code>")

    if result["status"] == "nxdomain":
        return (
            f"❌ <b>Domain does not exist.</b> "
            f"<code>{brand.esc(domain)}</code>\n"
            "<i>NXDOMAIN from the recursive resolver</i>"
        )

    if result["status"] == "nodata":
        lines = [head, f"<i>No {brand.esc(record_type)} records at this name</i>"]
        if result["authority"]:
            lines.append(
                f"<b>SOA</b> · <code>{brand.esc(result['authority'][0])}</code>"
            )
        return "\n".join(lines)

    answers = result["answers"]
    lines = [head]
    for answer in answers[:20]:
        lines.append(f"<code>{brand.esc(answer)}</code>")
    if len(answers) > 20:
        lines.append(f"<i>… {len(answers) - 20} more</i>")
    footer = f"<i>source: {brand.esc(result['provider'])}"
    if result.get("ttl") is not None:
        footer += f", ttl {brand.esc(result['ttl'])}s"
    lines.append(footer + "</i>")
    return "\n".join(lines)


async def resolve_host(host):
    try:
        addresses = await recon.resolve_host(host)
    except api.APIError as exc:
        return f"❌ <b>Resolve failed.</b> {brand.esc(exc)}"
    return (
        f"🌐 <b>Resolved</b> · <code>{brand.esc(host)}</code>\n"
        + "\n".join(f"<code>{brand.esc(address)}</code>" for address in addresses)
    )


async def reverse_lookup(ip):
    try:
        name = recon.ptr_name(ip)
    except api.APIError as exc:
        return f"❌ <b>Reverse lookup failed.</b> {brand.esc(exc)}"

    try:
        result = await recon.doh(name, "PTR")
    except api.APIError as exc:
        # DoH is down: the platform resolver may still know the name
        try:
            hostname, _, _ = await asyncio.get_running_loop().run_in_executor(
                None, socket.gethostbyaddr, ip
            )
        except OSError:
            return (f"❌ <b>Reverse lookup failed.</b> {brand.esc(exc)}\n"
                    "The platform resolver has no PTR entry either.")
        return (
            f"🔁 <b>Reverse DNS</b> · <code>{brand.esc(ip)}</code>\n"
            f"<code>{brand.esc(hostname)}</code>"
        )

    if result["status"] != "ok" or not result["answers"]:
        return f"❌ <b>No reverse DNS entry</b> for <code>{brand.esc(ip)}</code>"
    return (
        f"🔁 <b>Reverse DNS</b> · <code>{brand.esc(ip)}</code>\n"
        + "\n".join(f"<code>{brand.esc(answer)}</code>"
                    for answer in result["answers"][:5])
    )


#------------------------------
#Network owner
#------------------------------

async def network_summary(ip):
    """One RDAP line for the network `ip` belongs to, or None."""
    try:
        data = await recon.rdap_lookup("ip", ip)
    except api.APIError:
        return None
    name = data.get("name") or data.get("handle") or "N/A"
    line = f"🏷 <b>Network</b> · {brand.esc(name)}"
    handle = str(data.get("handle") or "")
    # Some registries use the range itself as the handle; do not print it twice
    if handle and handle != name and handle != f"{data.get('startAddress')} - {data.get('endAddress')}":
        line += f" · <code>{brand.esc(handle)}</code>"
    if data.get("startAddress") and data.get("endAddress"):
        line += (f"\n<code>{brand.esc(data['startAddress'])} – "
                 f"{brand.esc(data['endAddress'])}</code>")
    return line


async def info_lookup(target):
    ip = target
    if not recon.is_ip(ip):
        try:
            ip = (await recon.resolve_host(target))[0]
        except api.APIError as exc:
            return f"❌ <b>Could not resolve</b> <code>{brand.esc(target)}</code> · {brand.esc(exc)}"

    geo_text, _ = await geo_lookup(ip)
    reverse_text = await reverse_lookup(ip)
    network_text = await network_summary(ip)

    lines = [f"📊 <b>Combined Info</b> · <code>{brand.esc(ip)}</code>"]
    if geo_text.startswith("📍"):
        lines.extend(geo_text.splitlines()[1:])
    else:
        lines.append(geo_text)
    lines.append("")
    lines.append(reverse_text)
    if network_text:
        lines.append(network_text)
    else:
        lines.append("<i>RDAP network data unavailable</i>")
    return "\n".join(lines)


#------------------------------
#Reachability
#------------------------------

async def port_check(host, port):
    service = recon.service_name(port)
    label = f"port {port}" + (f" ({service})" if service else "")
    started = asyncio.get_running_loop().time()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=4)
        latency = int((asyncio.get_running_loop().time() - started) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return (
            f"✅ <b>{brand.esc(label)} on {brand.esc(host)} is open</b>\n"
            f"<i>answered in {latency} ms</i>"
        )
    except asyncio.TimeoutError:
        return (f"❌ <b>{brand.esc(label)} on {brand.esc(host)} timed out</b>\n"
                "<i>filtered, or the host drops silent packets</i>")
    except ConnectionRefusedError:
        return (f"❌ <b>{brand.esc(label)} on {brand.esc(host)} is closed</b>\n"
                "<i>the host answered and refused</i>")
    except OSError as exc:
        return (f"❌ <b>Port check failed.</b> {brand.esc(host)}\n"
                f"<i>{brand.esc(exc.strerror or exc)}</i>")


async def ping_host(host):
    # Not subprocess.run(): that froze the loop for up to 10s
    try:
        proc = await asyncio.create_subprocess_exec(
            'ping', '-c', '4', '-W', '2', host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return ("❌ <b>ping is not installed here.</b>\n"
                "Replit containers usually have no ICMP; use "
                "<code>!ip port</code> or <code>!portsweep</code>.")
    except Exception as e:
        return f"❌ <b>Ping failed.</b> {brand.esc(e)}"

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=12)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        return f"❌ <b>Ping timed out.</b> <code>{brand.esc(host)}</code>"

    out = stdout.decode(errors='replace')
    err = stderr.decode(errors='replace')
    if proc.returncode == 0:
        lines = out.splitlines()
        return (
            f"📡 <b>Ping</b> · <code>{brand.esc(host)}</code>\n"
            + "\n".join(f"<code>{brand.esc(line)}</code>" for line in lines[-4:])
        )
    return f"❌ <b>Ping failed.</b> {brand.esc(err or 'unknown error')}"


#------------------------------
#Command
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r'^!ip(?:\s+(.*))?$'))
    async def ip_cmd(event):
        arg_str = event.pattern_match.group(1)
        if not arg_str:
            await say(
                event,
                "📖 <b>IP Command Help</b>\n" + brand.esc(__HELP__),
                name="ip",
                parse_mode="html",
            )
            return

        try:
            args = shlex.split(arg_str)
        except ValueError:
            await say(event, "❌ <b>Unbalanced quotes in that command.</b>",
                      name="ip", parse_mode="html")
            return

        subcommand = args[0].lower()
        if subcommand == "help":
            await say(event, brand.esc(__HELP__), name="ip", parse_mode="html")
            return

        if subcommand == "geo":
            if len(args) < 2:
                await say(event, "❌ Usage: <code>!ip geo &lt;IP|host&gt;</code>",
                          name="ip", parse_mode="html")
                return
            try:
                target = recon.clean_host(args[1])
            except api.APIError as exc:
                await say(
                    event,
                    f"❌ <b>{brand.esc(exc)}</b> · "
                    f"<code>{brand.esc(args[1])}</code>",
                    name="ip", parse_mode="html")
                return
            result, _ = await geo_lookup(target)
            await say(event, result, name="ip", parse_mode="html")
            return

        if subcommand == "dns":
            if len(args) < 2:
                await say(event,
                          "❌ Usage: <code>!ip dns &lt;domain&gt; [type]</code>",
                          name="ip", parse_mode="html")
                return
            try:
                domain = recon.clean_domain(args[1])
            except api.APIError as exc:
                await say(
                    event,
                    f"❌ <b>{brand.esc(exc)}</b> · "
                    f"<code>{brand.esc(args[1])}</code>",
                    name="ip", parse_mode="html")
                return
            record_type = args[2].upper() if len(args) > 2 else "A"
            result = await dns_lookup(domain, record_type)
            await say(event, result, name="ip", parse_mode="html")
            return

        if subcommand == "resolve":
            if len(args) < 2:
                await say(event, "❌ Usage: <code>!ip resolve &lt;host&gt;</code>",
                          name="ip", parse_mode="html")
                return
            try:
                host = recon.clean_host(args[1])
            except api.APIError as exc:
                await say(
                    event,
                    f"❌ <b>{brand.esc(exc)}</b> · "
                    f"<code>{brand.esc(args[1])}</code>",
                    name="ip", parse_mode="html")
                return
            result = await resolve_host(host)
            await say(event, result, name="ip", parse_mode="html")
            return

        if subcommand == "reverse":
            if len(args) < 2:
                await say(event, "❌ Usage: <code>!ip reverse &lt;IP&gt;</code>",
                          name="ip", parse_mode="html")
                return
            if not recon.is_ip(args[1]):
                await say(event, "❌ Invalid IP address.", name="ip")
                return
            result = await reverse_lookup(args[1])
            await say(event, result, name="ip", parse_mode="html")
            return

        if subcommand == "info":
            if len(args) < 2:
                await say(event, "❌ Usage: <code>!ip info &lt;IP|host&gt;</code>",
                          name="ip", parse_mode="html")
                return
            try:
                target = recon.clean_host(args[1])
            except api.APIError as exc:
                await say(
                    event,
                    f"❌ <b>{brand.esc(exc)}</b> · "
                    f"<code>{brand.esc(args[1])}</code>",
                    name="ip", parse_mode="html")
                return
            result = await info_lookup(target)
            await say(event, result, name="ip", parse_mode="html")
            return

        if subcommand == "ping":
            if len(args) < 2:
                await say(event, "❌ Usage: <code>!ip ping &lt;host&gt;</code>",
                          name="ip", parse_mode="html")
                return
            try:
                host = recon.clean_host(args[1])
            except api.APIError as exc:
                await say(
                    event,
                    f"❌ <b>{brand.esc(exc)}</b> · "
                    f"<code>{brand.esc(args[1])}</code>",
                    name="ip", parse_mode="html")
                return
            result = await ping_host(host)
            await say(event, result, name="ip", parse_mode="html")
            return

        if subcommand == "port":
            if len(args) < 3:
                await say(event,
                          "❌ Usage: <code>!ip port &lt;host&gt; &lt;port&gt;</code>",
                          name="ip", parse_mode="html")
                return
            try:
                host = recon.clean_host(args[1])
            except api.APIError as exc:
                await say(
                    event,
                    f"❌ <b>{brand.esc(exc)}</b> · "
                    f"<code>{brand.esc(args[1])}</code>",
                    name="ip", parse_mode="html")
                return
            try:
                port = int(args[2])
                if port < 1 or port > 65535:
                    raise ValueError
            except ValueError:
                await say(event, "❌ Invalid port number.", name="ip")
                return
            result = await port_check(host, port)
            await say(event, result, name="ip", parse_mode="html")
            return

        await say(
            event,
            f"❌ <b>Unknown subcommand.</b> <code>{brand.esc(subcommand)}</code>\n"
            "Use <code>!ip help</code> for available commands.",
            name="ip",
            parse_mode="html",
        )
