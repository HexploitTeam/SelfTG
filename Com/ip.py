"""!ip: geolocation, DNS, reverse lookup, port and ping checks."""
import socket
import re
import shlex
import asyncio
import subprocess
import ipaddress
from telethon import events

from Com.core import brand
from Com.core.reply import say
import Com.core.api as api

# dnspython is optional
try:
    import dns.resolver
    HAS_DNS = True
except ImportError:
    HAS_DNS = False

__HELP__ = (
    "!ip <subcommand> [args] → IP and domain intelligence.\n"
    "Subcommands:\n"
    "  geo <IP>               → Geolocation (country, city, ISP, coordinates)\n"
    "  dns <domain> [type]    → DNS lookup (A, AAAA, MX, TXT, NS, CNAME)\n"
    "  resolve <host>         → Resolve hostname to IP(s)\n"
    "  reverse <IP>           → Reverse DNS lookup\n"
    "  info <IP>              → Combined info (geo + reverse)\n"
    "  ping <host>            → ICMP ping (if system ping is available)\n"
    "  port <host> <port>     → Check if a port is open (TCP)\n"
    "  help                   → Show this help.\n"
    "Examples:\n"
    "  !ip geo 8.8.8.8\n"
    "  !ip dns example.com MX\n"
    "  !ip resolve github.com\n"
    "  !ip reverse 1.1.1.1\n"
    "  !ip info 1.1.1.1\n"
)
__CATEGORY__ = "Information"

def is_valid_ip(ip):
    try:
        ipaddress.ip_address(ip)
        return True
    except:
        return False

def is_valid_domain(domain):
    pattern = re.compile(r'^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63}(?<!-))*\.[A-Za-z]{2,}$')
    return pattern.match(domain) is not None

#------------------------------
#Subcommands
#------------------------------

IP_API_URL = "http://ip-api.com/json/{ip}"          # keyless, HTTP-only free tier
IPWHO_URL = "https://ipwho.is/{ip}"                 # keyless HTTPS fallback
GEO_CACHE_TTL = 24 * 3600                           # geo data barely changes


def _render_geo(ip, data, source):
    lines = [
        f"📍 <b>Geolocation</b> · <code>{brand.esc(ip)}</code>",
        f"<b>Country</b> · {brand.esc(data.get('country') or 'N/A')}",
        f"<b>City</b> · {brand.esc(data.get('city') or 'N/A')}",
        f"<b>ISP</b> · {brand.esc(data.get('isp') or 'N/A')}",
        f"<b>Organization</b> · {brand.esc(data.get('org') or 'N/A')}",
        f"<b>AS</b> · {brand.esc(data.get('as') or 'N/A')}",
        f"<b>Timezone</b> · {brand.esc(data.get('timezone') or 'N/A')}",
        f"<b>Lat/Lon</b> · <code>{brand.esc(data.get('lat', 'N/A'))}, "
        f"{brand.esc(data.get('lon', 'N/A'))}</code>",
        f"<i>source: {brand.esc(source)}, cached {GEO_CACHE_TTL // 3600}h</i>",
    ]
    return "\n".join(lines)


async def _geo_ipapi(ip):
    data = await api.fetch_json(
        IP_API_URL.format(ip=ip),
        params={"fields": "status,message,country,city,isp,org,as,lat,lon,timezone"},
        provider="ip-api.com",
        cache_ttl=GEO_CACHE_TTL,
        timeout=8,
    )
    if data.get("status") == "fail":
        raise api.APIError(data.get("message") or "lookup failed", provider="ip-api.com")
    return _render_geo(ip, data, "ip-api.com")


async def _geo_ipwho(ip):
    data = await api.fetch_json(
        IPWHO_URL.format(ip=ip),
        provider="ipwho.is",
        cache_ttl=GEO_CACHE_TTL,
        timeout=10,
    )
    if not data.get("success", False):
        raise api.APIError(data.get("message") or "lookup failed", provider="ipwho.is")
    connection = data.get("connection") or {}
    return _render_geo(
        ip,
        {
            "country": data.get("country"),
            "city": data.get("city"),
            "isp": connection.get("isp"),
            "org": connection.get("org"),
            "as": connection.get("asn"),
            "timezone": (data.get("timezone") or {}).get("id"),
            "lat": data.get("latitude"),
            "lon": data.get("longitude"),
        },
        "ipwho.is",
    )


async def geo_lookup(ip):
    """ip-api.com first (keyless), ipwho.is second (keyless HTTPS)."""
    try:
        return await api.first_success([
            ("ip-api.com", lambda: _geo_ipapi(ip)),
            ("ipwho.is", lambda: _geo_ipwho(ip)),
        ])
    except api.APIError as exc:
        return (
            f"❌ <b>Geolocation failed.</b> {brand.esc(exc)}\n"
            "Both free providers are down or rate limited."
        )
    except Exception as exc:  # noqa: BLE001
        return (
            f"❌ <b>Error</b> · {brand.esc(type(exc).__name__)}: "
            f"{brand.esc(exc)}"
        )

async def dns_lookup(domain, record_type='A'):
    if not HAS_DNS:
        return (
            "❌ <b>dnspython not installed.</b> Install with "
            "<code>pip install dnspython</code>"
        )
    try:
        resolver = dns.resolver.Resolver()
        answers = resolver.resolve(domain, record_type)
        results = [str(r) for r in answers]
        return (
            f"📡 <b>DNS {brand.esc(record_type)} records</b> · "
            f"<code>{brand.esc(domain)}</code>\n"
            + "\n".join(f"<code>{brand.esc(r)}</code>" for r in results)
        )
    except dns.resolver.NoAnswer:
        return (
            f"❌ <b>No {brand.esc(record_type)} records</b> for "
            f"<code>{brand.esc(domain)}</code>"
        )
    except dns.resolver.NXDOMAIN:
        return f"❌ <b>Domain does not exist.</b> <code>{brand.esc(domain)}</code>"
    except Exception as e:
        return f"❌ <b>DNS lookup failed.</b> {brand.esc(e)}"

async def resolve_host(host):
    try:
        # getaddrinfo is blocking: run it in the executor
        addrs = await asyncio.get_running_loop().getaddrinfo(host, None)
        ips = sorted(set(addr[4][0] for addr in addrs))
        return (
            f"🌐 <b>Resolved</b> · <code>{brand.esc(host)}</code>\n"
            + "\n".join(f"<code>{brand.esc(ip)}</code>" for ip in ips)
        )
    except Exception as e:
        return f"❌ <b>Resolve failed.</b> {brand.esc(e)}"

async def reverse_lookup(ip):
    try:
        hostname, _, _ = await asyncio.get_running_loop().run_in_executor(
            None, socket.gethostbyaddr, ip)
        return (
            f"🔁 <b>Reverse DNS</b> · <code>{brand.esc(ip)}</code>\n"
            f"<code>{brand.esc(hostname)}</code>"
        )
    except socket.herror:
        return f"❌ <b>No reverse DNS entry</b> for <code>{brand.esc(ip)}</code>"
    except Exception as e:
        return f"❌ <b>Reverse lookup failed.</b> {brand.esc(e)}"

async def info_lookup(ip):
    geo_result = await geo_lookup(ip)
    reverse_result = await reverse_lookup(ip)
    lines = ["📊 <b>Combined Info</b> · <code>" + brand.esc(ip) + "</code>"]
    if geo_result.startswith("📍"):
        geo_lines = geo_result.splitlines()[1:]
        lines.extend(geo_lines)
    else:
        lines.append(geo_result)
    lines.append("")
    lines.append(reverse_result)
    return "\n".join(lines)

async def port_check(host, port):
    try:
        reader, writer = await asyncio.open_connection(host, port, timeout=3)
        writer.close()
        await writer.wait_closed()
        return f"✅ <b>Port {port} on {brand.esc(host)} is open</b>"
    except (TimeoutError, ConnectionRefusedError, OSError):
        return (
            f"❌ <b>Port {port} on {brand.esc(host)} is closed or filtered</b>"
        )
    except Exception as e:
        return f"❌ <b>Port check failed.</b> {brand.esc(e)}"

async def ping_host(host):
    # Not subprocess.run(): that froze the loop for up to 10s
    try:
        proc = await asyncio.create_subprocess_exec(
            'ping', '-c', '4', '-W', '2', host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return "❌ <b>ping command not found</b> on this system."
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

        args = shlex.split(arg_str)
        subcommand = args[0].lower()

        if subcommand == "help":
            await say(event, brand.esc(__HELP__), name="ip", parse_mode="html")
            return

        if subcommand == "geo":
            if len(args) < 2:
                await say(
                    event,
                    "❌ Usage: <code>!ip geo &lt;IP&gt;</code>",
                    name="ip",
                    parse_mode="html",
                )
                return
            ip = args[1]
            if not is_valid_ip(ip):
                await say(event, "❌ Invalid IP address.", name="ip")
                return
            result = await geo_lookup(ip)
            await say(event, result, name="ip", parse_mode="html")
            return

        if subcommand == "dns":
            if len(args) < 2:
                await say(
                    event,
                    "❌ Usage: <code>!ip dns &lt;domain&gt; [type]</code>",
                    name="ip",
                    parse_mode="html",
                )
                return
            domain = args[1]
            record_type = args[2].upper() if len(args) > 2 else "A"
            if not is_valid_domain(domain):
                await say(event, "❌ Invalid domain name.", name="ip")
                return
            result = await dns_lookup(domain, record_type)
            await say(event, result, name="ip", parse_mode="html")
            return

        if subcommand == "resolve":
            if len(args) < 2:
                await say(
                    event,
                    "❌ Usage: <code>!ip resolve &lt;host&gt;</code>",
                    name="ip",
                    parse_mode="html",
                )
                return
            host = args[1]
            result = await resolve_host(host)
            await say(event, result, name="ip", parse_mode="html")
            return

        if subcommand == "reverse":
            if len(args) < 2:
                await say(
                    event,
                    "❌ Usage: <code>!ip reverse &lt;IP&gt;</code>",
                    name="ip",
                    parse_mode="html",
                )
                return
            ip = args[1]
            if not is_valid_ip(ip):
                await say(event, "❌ Invalid IP address.", name="ip")
                return
            result = await reverse_lookup(ip)
            await say(event, result, name="ip", parse_mode="html")
            return

        if subcommand == "info":
            if len(args) < 2:
                await say(
                    event,
                    "❌ Usage: <code>!ip info &lt;IP&gt;</code>",
                    name="ip",
                    parse_mode="html",
                )
                return
            ip = args[1]
            if not is_valid_ip(ip):
                await say(event, "❌ Invalid IP address.", name="ip")
                return
            result = await info_lookup(ip)
            await say(event, result, name="ip", parse_mode="html")
            return

        if subcommand == "ping":
            if len(args) < 2:
                await say(
                    event,
                    "❌ Usage: <code>!ip ping &lt;host&gt;</code>",
                    name="ip",
                    parse_mode="html",
                )
                return
            host = args[1]
            result = await ping_host(host)
            await say(event, result, name="ip", parse_mode="html")
            return

        if subcommand == "port":
            if len(args) < 3:
                await say(
                    event,
                    "❌ Usage: <code>!ip port &lt;host&gt; &lt;port&gt;</code>",
                    name="ip",
                    parse_mode="html",
                )
                return
            host = args[1]
            try:
                port = int(args[2])
                if port < 1 or port > 65535:
                    raise ValueError
            except:
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