"""!ip: geolocation, DNS, reverse lookup, port and ping checks."""
import socket
import re
import shlex
import asyncio
import subprocess
import ipaddress
from telethon import events

import Com.core.api as api

# dnspython is optional; socket-based lookups still work without it
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
        f"📍 **Geolocation for {ip}**",
        f"Country: {data.get('country') or 'N/A'}",
        f"City: {data.get('city') or 'N/A'}",
        f"ISP: {data.get('isp') or 'N/A'}",
        f"Organization: {data.get('org') or 'N/A'}",
        f"AS: {data.get('as') or 'N/A'}",
        f"Timezone: {data.get('timezone') or 'N/A'}",
        f"Lat/Lon: {data.get('lat', 'N/A')}, {data.get('lon', 'N/A')}",
        f"_source: {source}, cached {GEO_CACHE_TTL // 3600}h_",
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
        return f"❌ Geolocation failed ({exc}). Both free providers are down or rate limited."
    except Exception as exc:  # noqa: BLE001
        return f"❌ Error: {type(exc).__name__}: {exc}"

async def dns_lookup(domain, record_type='A'):
    if not HAS_DNS:
        return "❌ dnspython not installed. Install with: pip install dnspython"
    try:
        resolver = dns.resolver.Resolver()
        answers = resolver.resolve(domain, record_type)
        results = [str(r) for r in answers]
        return f"📡 **DNS {record_type} records for {domain}**\n" + "\n".join(results)
    except dns.resolver.NoAnswer:
        return f"❌ No {record_type} records found for {domain}"
    except dns.resolver.NXDOMAIN:
        return f"❌ Domain {domain} does not exist"
    except Exception as e:
        return f"❌ Error: {str(e)}"

async def resolve_host(host):
    try:
        # getaddrinfo() is blocking; the loop version runs it in the executor so
        # slow DNS cannot stall every other handler.
        addrs = await asyncio.get_running_loop().getaddrinfo(host, None)
        ips = sorted(set(addr[4][0] for addr in addrs))
        return f"🌐 **Resolved {host}**\n" + "\n".join(ips)
    except Exception as e:
        return f"❌ Error: {str(e)}"

async def reverse_lookup(ip):
    try:
        hostname, _, _ = await asyncio.get_running_loop().run_in_executor(
            None, socket.gethostbyaddr, ip)
        return f"🔁 **Reverse DNS for {ip}**\n`{hostname}`"
    except socket.herror:
        return f"❌ No reverse DNS entry for {ip}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

async def info_lookup(ip):
    geo_result = await geo_lookup(ip)
    reverse_result = await reverse_lookup(ip)
    lines = ["📊 **Combined Info for " + ip + "**"]
    if geo_result.startswith("📍"):
        # (renderer output already carries the source line)
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
        return f"✅ Port {port} on {host} is **open**"
    except (TimeoutError, ConnectionRefusedError, OSError):
        return f"❌ Port {port} on {host} is **closed** or **filtered**"
    except Exception as e:
        return f"❌ Error: {str(e)}"

async def ping_host(host):
    # create_subprocess_exec instead of blocking subprocess.run(): the old call
    # froze the whole event loop (every handler) for up to 10 seconds.
    try:
        proc = await asyncio.create_subprocess_exec(
            'ping', '-c', '4', '-W', '2', host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return "❌ ping command not found on this system."
    except Exception as e:
        return f"❌ Error: {str(e)}"

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=12)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        return f"❌ Ping to {host} timed out."

    out = stdout.decode(errors='replace')
    err = stderr.decode(errors='replace')
    if proc.returncode == 0:
        lines = out.splitlines()
        return f"📡 **Ping to {host}**\n" + "\n".join(lines[-4:])
    return f"❌ Ping failed: {err or 'unknown error'}"

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r'^!ip(?:\s+(.*))?$'))
    async def ip_cmd(event):
        arg_str = event.pattern_match.group(1)
        if not arg_str:
            await event.edit("📖 **IP Command Help**\n" + __HELP__)
            return

        args = shlex.split(arg_str)
        subcommand = args[0].lower()

        if subcommand == "help":
            await event.edit(__HELP__)
            return

        if subcommand == "geo":
            if len(args) < 2:
                await event.edit("❌ Usage: !ip geo <IP>")
                return
            ip = args[1]
            if not is_valid_ip(ip):
                await event.edit("❌ Invalid IP address.")
                return
            result = await geo_lookup(ip)
            await event.edit(result)
            return

        if subcommand == "dns":
            if len(args) < 2:
                await event.edit("❌ Usage: !ip dns <domain> [type]")
                return
            domain = args[1]
            record_type = args[2].upper() if len(args) > 2 else "A"
            if not is_valid_domain(domain):
                await event.edit("❌ Invalid domain name.")
                return
            result = await dns_lookup(domain, record_type)
            await event.edit(result)
            return

        if subcommand == "resolve":
            if len(args) < 2:
                await event.edit("❌ Usage: !ip resolve <host>")
                return
            host = args[1]
            result = await resolve_host(host)
            await event.edit(result)
            return

        if subcommand == "reverse":
            if len(args) < 2:
                await event.edit("❌ Usage: !ip reverse <IP>")
                return
            ip = args[1]
            if not is_valid_ip(ip):
                await event.edit("❌ Invalid IP address.")
                return
            result = await reverse_lookup(ip)
            await event.edit(result)
            return

        if subcommand == "info":
            if len(args) < 2:
                await event.edit("❌ Usage: !ip info <IP>")
                return
            ip = args[1]
            if not is_valid_ip(ip):
                await event.edit("❌ Invalid IP address.")
                return
            result = await info_lookup(ip)
            await event.edit(result)
            return

        if subcommand == "ping":
            if len(args) < 2:
                await event.edit("❌ Usage: !ip ping <host>")
                return
            host = args[1]
            result = await ping_host(host)
            await event.edit(result)
            return

        if subcommand == "port":
            if len(args) < 3:
                await event.edit("❌ Usage: !ip port <host> <port>")
                return
            host = args[1]
            try:
                port = int(args[2])
                if port < 1 or port > 65535:
                    raise ValueError
            except:
                await event.edit("❌ Invalid port number.")
                return
            result = await port_check(host, port)
            await event.edit(result)
            return

        await event.edit(f"❌ Unknown subcommand: {subcommand}\nUse `!ip help` for available commands.")