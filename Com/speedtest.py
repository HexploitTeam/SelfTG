"""!speedtest: bandwidth test driven by speedtest-cli."""
import asyncio
import shlex
from telethon import events
from Com.core import brand
from Com.core.reply import say

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

#------------------------------
#Helpers
#------------------------------

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
    lines = ["📡 <b>Closest Servers</b> <i>(by distance)</i>", ""]
    for i, server in enumerate(servers, 1):
        lines.append(
            f"{i}. <code>{brand.esc(server['id'])}</code> · "
            f"{brand.esc(server['name'])} ({brand.esc(server['country'])})\n"
            f"   {brand.esc(server.get('d', '?'))} km · "
            f"<code>{brand.esc(server['host'])}</code>"
        )
    lines.append("\nUse <code>!speedtest --server &lt;id&gt;</code> "
                 "to test a specific server.")
    return "\n".join(lines)

def format_output(result, detailed=False):
    lines = ["📶 <b>Speed Test Results</b>"]
    lines.append(f"Ping · <code>{result['ping']:.2f} ms</code>")
    lines.append(f"Download · <b>{result['download_mbps']:.2f} Mbps</b> "
                 f"(<code>{result['download_mb_s']:.2f} MB/s</code>)")
    lines.append(f"Upload · <b>{result['upload_mbps']:.2f} Mbps</b> "
                 f"(<code>{result['upload_mb_s']:.2f} MB/s</code>)")

    if detailed:
        server = result["server"]
        lines.append("\n🖥️ <b>Server</b>")
        lines.append(f"Name · {brand.esc(server['name'])}")
        lines.append(f"Sponsor · {brand.esc(server['sponsor'])}")
        lines.append(f"Country · {brand.esc(server['country'])}")
        lines.append(f"Host · <code>{brand.esc(server['host'])}</code>")
        lines.append(f"Distance · <code>{server['distance']:.2f} km</code>")
        if server.get("lat") and server.get("lon"):
            lines.append(f"Location · <code>{server['lat']}, {server['lon']}</code>")
        lines.append(f"Server ID · <code>{brand.esc(server['id'])}</code>")

    return "\n".join(lines)

#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!speedtest(?:\s+(.*))?$"))
    async def speedtest_cmd(event):
        if not HAS_SPEEDTEST:
            await say(event,
                      "❌ <b>speedtest-cli is not installed</b>\n"
                      "Install with · <code>pip install speedtest-cli</code>",
                      name="speedtest", parse_mode="html")
            return

        arg_str = event.pattern_match.group(1)
        args = shlex.split(arg_str) if arg_str else []

        if args and args[0].lower() == "list":
            msg = await event.edit(
                brand.sign("⏳ <b>Fetching server list</b>…", "speedtest"),
                parse_mode="html")
            try:
                servers = get_server_list()
            except Exception as e:
                await msg.edit(
                    brand.sign(
                        f"❌ <b>Server list failed</b> · "
                        f"<code>{brand.esc(e)}</code>", "speedtest"),
                    parse_mode="html")
                return
            output = format_server_list(servers)
            await msg.edit(brand.sign(output, "speedtest"), parse_mode="html")
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
                    await say(event,
                              "❌ Missing server ID after "
                              "<code>--server</code>",
                              name="speedtest", parse_mode="html")
                    return
                try:
                    server_id = int(args[i+1])
                except ValueError:
                    await say(event, "❌ Server ID must be a number.",
                              name="speedtest")
                    return
                i += 2
            else:
                await say(event,
                          f"❌ Unknown option · <code>{brand.esc(arg)}</code>\n"
                          "Use <code>!speedtest</code> for help.",
                          name="speedtest", parse_mode="html")
                return

        msg = await event.edit(
            brand.sign("⏳ <b>Starting speed test</b>… "
                       "<i>(may take 30–60 seconds)</i>", "speedtest"),
            parse_mode="html")

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, run_test, server_id, detailed)
        except ValueError as e:
            await msg.edit(brand.sign(f"❌ {brand.esc(e)}", "speedtest"),
                           parse_mode="html")
            return
        except Exception as e:
            await msg.edit(
                brand.sign(f"❌ <b>Speed test failed</b> · "
                           f"<code>{brand.esc(e)}</code>", "speedtest"),
                parse_mode="html")
            return

        output = format_output(result, detailed)
        await msg.edit(brand.sign(output, "speedtest"), parse_mode="html")