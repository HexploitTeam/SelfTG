"""!timezone: list zones, show the current time and convert between zones."""
import shlex
from datetime import datetime
import re
from telethon import events

from Com.core import brand
from Com.core.reply import say
import Com.core.tgsend as tgsend

try:
    import zoneinfo
    TIMEZONE_MODULE = "zoneinfo"
    from zoneinfo import ZoneInfo
except ImportError:
    try:
        import pytz
        TIMEZONE_MODULE = "pytz"
        from pytz import timezone, all_timezones
    except ImportError:
        TIMEZONE_MODULE = None

__HELP__ = (
    "!timezone list → List all available timezones\n"
    "!timezone now <timezone> → Show current time in a timezone\n"
    "!timezone convert <datetime> <from_tz> <to_tz> → Convert datetime between timezones\n"
    "!timezone <timezone> → Show current time in that timezone (shortcut)\n"
    "Examples:\n"
    "  !timezone now Europe/London\n"
    "  !timezone convert '2026-07-16 14:30' UTC Asia/Tehran\n"
    "  !timezone Asia/Tehran\n"
    "Common timezones: UTC, Asia/Tehran, Europe/London, America/New_York, etc."
)
__CATEGORY__ = "Utilities"

#------------------------------
#Helpers
#------------------------------

def get_timezone(tz_name):
    if TIMEZONE_MODULE == "zoneinfo":
        return ZoneInfo(tz_name)
    elif TIMEZONE_MODULE == "pytz":
        return timezone(tz_name)
    else:
        return None

def get_all_timezones():
    if TIMEZONE_MODULE == "zoneinfo":
        return zoneinfo.available_timezones()
    elif TIMEZONE_MODULE == "pytz":
        return all_timezones
    else:
        return set()

def format_datetime(dt, tz_name):
    return dt.strftime("%Y-%m-%d %H:%M:%S") + f" ({tz_name})"

#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r'^!timezone(?:\s+(.*))?$'))
    async def timezone_cmd(event):
        try:
            if TIMEZONE_MODULE is None:
                await say(
                    event,
                    "❌ <b>Timezone module not installed.</b> Run "
                    "<code>pip install pytz</code>.",
                    name="timezone",
                    parse_mode="html",
                )
                return

            arg = event.pattern_match.group(1)
            if not arg:
                await say(
                    event,
                    "📖 <b>Timezone Help</b>\n" + brand.esc(__HELP__),
                    name="timezone",
                    parse_mode="html",
                )
                return

            args = shlex.split(arg)
            cmd = args[0].lower()

            # !timezone list
            if cmd == "list":
                tz_list = sorted(get_all_timezones())
                # Send as file if too many
                if len(tz_list) > 100:
                    import io
                    bio = io.BytesIO("\n".join(tz_list).encode("utf-8"))
                    bio.name = "timezones.txt"
                    await client.send_file(
                        await tgsend.peer(event),
                        bio,
                        caption=brand.sign("📋 <b>All timezones</b>", "timezone"),
                        parse_mode="html",
                    )
                    await event.delete()
                else:
                    await say(
                        event,
                        "📋 <b>Available timezones</b>\n"
                        + "\n".join(brand.esc(tz) for tz in tz_list),
                        name="timezone",
                        parse_mode="html",
                    )
                return

            # !timezone now <timezone>
            if cmd == "now":
                if len(args) < 2:
                    await say(
                        event,
                        "❌ Usage: <code>!timezone now &lt;timezone&gt;</code>",
                        name="timezone",
                        parse_mode="html",
                    )
                    return
                tz_name = args[1]
                try:
                    tz = get_timezone(tz_name)
                except Exception:
                    await say(
                        event,
                        f"❌ <b>Unknown timezone.</b> {brand.esc(tz_name)}",
                        name="timezone",
                        parse_mode="html",
                    )
                    return
                now = datetime.now(tz)
                await say(
                    event,
                    f"🕐 <b>Current time</b> · {brand.esc(tz_name)}\n"
                    f"<code>{brand.esc(format_datetime(now, tz_name))}</code>",
                    name="timezone",
                    parse_mode="html",
                )
                return

            # !timezone convert <datetime> <from_tz> <to_tz>
            if cmd == "convert":
                if len(args) < 4:
                    await say(
                        event,
                        "❌ Usage: <code>!timezone convert '&lt;datetime&gt;' "
                        "&lt;from_tz&gt; &lt;to_tz&gt;</code>",
                        name="timezone",
                        parse_mode="html",
                    )
                    return
                dt_str = args[1]
                from_tz_name = args[2]
                to_tz_name = args[3]

                # Parse datetime (try common formats)
                dt = None
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M"]:
                    try:
                        dt = datetime.strptime(dt_str, fmt)
                        break
                    except:
                        continue
                if dt is None:
                    await say(
                        event,
                        "❌ <b>Could not parse that datetime.</b> Try "
                        "<code>YYYY-MM-DD HH:MM</code>",
                        name="timezone",
                        parse_mode="html",
                    )
                    return

                # Get timezone objects
                try:
                    from_tz = get_timezone(from_tz_name)
                    to_tz = get_timezone(to_tz_name)
                except Exception:
                    await say(
                        event, "❌ Invalid timezone provided.", name="timezone"
                    )
                    return

                # Convert: first localize naive datetime as from_tz, then convert to to_tz
                if TIMEZONE_MODULE == "pytz":
                    # pytz requires localize
                    from_dt = from_tz.localize(dt)
                else:
                    # zoneinfo: you can replace tzinfo
                    from_dt = dt.replace(tzinfo=from_tz)

                to_dt = from_dt.astimezone(to_tz)

                output = (
                    "🔄 <b>Timezone Conversion</b>\n"
                    f"<b>Input</b> · <code>{brand.esc(dt_str)}</code> "
                    f"({brand.esc(from_tz_name)})\n"
                    f"<b>Result</b> · "
                    f"<code>{brand.esc(format_datetime(to_dt, to_tz_name))}</code>"
                )
                await say(event, output, name="timezone", parse_mode="html")
                return

            # !timezone <timezone>: current time there
            tz_name = cmd
            try:
                tz = get_timezone(tz_name)
            except Exception:
                await say(
                    event,
                    f"❌ <b>Unknown timezone.</b> {brand.esc(tz_name)}\n"
                    "Use <code>!timezone list</code> to see all.",
                    name="timezone",
                    parse_mode="html",
                )
                return
            now = datetime.now(tz)
            await say(
                event,
                f"🕐 <b>Current time</b> · {brand.esc(tz_name)}\n"
                f"<code>{brand.esc(format_datetime(now, tz_name))}</code>",
                name="timezone",
                parse_mode="html",
            )

        except Exception as e:
            await say(
                event,
                f"❌ <b>Timezone failed.</b> {brand.esc(e)}",
                name="timezone",
                parse_mode="html",
            )