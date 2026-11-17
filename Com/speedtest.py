# Com/speedtest.py
import asyncio
import shlex
from telethon import events

try:
    import speedtest
    HAS_SPEEDTEST = True
except ImportError:
    HAS_SPEEDTEST = False

__HELP__ = (
    "!speedtest [options] → Run an internet speed test.\n"
    "Options:\n"
    "  --server <id>     Use a specific server ID (see list).\n"
    "  --detail          Show extended server information.\n"
    "  list              List the 10 closest servers with IDs.\n"
    "Examples:\n"
    "  !speedtest\n"
    "  !speedtest --server 1234 --detail\n"
    "  !speedtest list"
)
__CATEGORY__ = "Utilities"

def format_speed(bits_per_sec):
    mbps = bits_per_sec / 1_000_000
    mbytes = bits_per_sec / 8 / 1_000_000
    return mbps, mbytes

def run_test(server_id=None, detailed=False):
    st = speedtest.Speedtest()
    st.get_servers()
    if server_id:
        found_server = None
        for group in st.servers.values():
            for srv in group:
                if str(srv['id']) == str(server_id):
                    found_server = srv
                    break
            if found_server:
                break
        if found_server is None:
            raise ValueError(f"Server ID {server_id} not found")
        st.results.server = found_server
    else:
        st.get_best_server()

    server = st.results.server
    download_bits = st.download()
    upload_bits = st.upload()
    ping_ms = st.results.ping
    if ping_ms > 10000:
        ping_ms = ping_ms / 1000.0

    server_info = {
        "name": server.get("name", "Unknown"),
        "sponsor": server.get("sponsor", "Unknown"),
        "country": server.get("country", "Unknown"),
        "host": server.get("host", "Unknown"),
        "id": server.get("id", "Unknown"),
        "lat": server.get("lat", 0),
        "lon": server.get("lon", 0),
        "distance": server.get("d", 0),
    }

    return {
        "ping": ping_ms,
        "download_mbps": download_bits / 1_000_000,
        "upload_mbps": upload_bits / 1_000_000,
        "download_mb_s": download_bits / 8 / 1_000_000,
        "upload_mb_s": upload_bits / 8 / 1_000_000,
        "server": server_info,
    }

def get_server_list(limit=10):
    st = speedtest.Speedtest()
    st.get_servers()
    all_servers = []
    for group in st.servers.values():
        all_servers.extend(group)
    all_servers.sort(key=lambda s: s.get('d', 999999))
    return all_servers[:limit]

def format_server_list(servers):
    lines = ["📡 **Closest Servers (by distance)**", ""]
    for i, server in enumerate(servers, 1):
        lines.append(
            f"{i}. ID: `{server['id']}` – {server['name']} ({server['country']}) – "
            f"{server.get('d', '?')} km, {server['host']}"
        )
    lines.append("\nUse `!speedtest --server <id>` to test a specific server.")
    return "\n".join(lines)

def format_output(result, detailed=False):
    lines = []
    lines.append("📶 **Speed Test Results**")
    lines.append(f"• Ping: `{result['ping']:.2f} ms`")
    lines.append(f"• Download: `{result['download_mbps']:.2f} Mbps` (`{result['download_mb_s']:.2f} MB/s`)")
    lines.append(f"• Upload: `{result['upload_mbps']:.2f} Mbps` (`{result['upload_mb_s']:.2f} MB/s`)")

    if detailed:
        server = result["server"]
        lines.append("\n🖥️ **Server Information:**")
        lines.append(f"  • Name: {server['name']}")
        lines.append(f"  • Sponsor: {server['sponsor']}")
        lines.append(f"  • Country: {server['country']}")
        lines.append(f"  • Host: {server['host']}")
        lines.append(f"  • Distance: {server['distance']:.2f} km")
        if server.get("lat") and server.get("lon"):
            lines.append(f"  • Location: ({server['lat']}, {server['lon']})")
        lines.append(f"  • Server ID: `{server['id']}`")

    return "\n".join(lines)

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!speedtest(?:\s+(.*))?$"))
    async def speedtest_cmd(event):
        if not HAS_SPEEDTEST:
            await event.edit("❌ Speedtest library not installed.\nInstall with: `pip install speedtest-cli`")
            return

        arg_str = event.pattern_match.group(1)
        args = shlex.split(arg_str) if arg_str else []

        if args and args[0].lower() == "list":
            msg = await event.edit("⏳ Fetching server list...")
            try:
                servers = get_server_list()
            except Exception as e:
                await msg.edit(f"❌ Failed to get server list: {e}")
                return
            output = format_server_list(servers)
            await msg.edit(output)
            return

        detailed = False
        server_id = None
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--detail":
                detailed = True
                i += 1
            elif arg == "--server":
                if i + 1 >= len(args):
                    await event.edit("❌ Missing server ID after `--server`")
                    return
                try:
                    server_id = int(args[i+1])
                except ValueError:
                    await event.edit("❌ Server ID must be a number")
                    return
                i += 2
            else:
                await event.edit(f"❌ Unknown option: {arg}\nUse `!speedtest` for help.")
                return

        msg = await event.edit("⏳ Starting speed test... (may take 30–60 seconds)")

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, run_test, server_id, detailed)
        except ValueError as e:
            await msg.edit(f"❌ {e}")
            return
        except Exception as e:
            await msg.edit(f"❌ Speed test failed: {e}")
            return

        output = format_output(result, detailed)
        await msg.edit(output)