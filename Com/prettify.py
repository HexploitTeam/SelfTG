"""!prettify: re-indent JSON, XML and HTML."""
import json
import re
import shlex
import textwrap
from xml.dom import minidom
from telethon import events
import Com.core.tgsend as tgsend

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

__HELP__ = (
    "!prettify [flags] (reply or text) → Pretty‑print JSON, XML, or HTML.\n"
    "Flags:\n"
    "  --type <json|xml|html>  Force a specific format (auto‑detect by default).\n"
    "  --indent <N>            Indentation spaces (default: 2).\n"
    "  --width <N>             Line width for text wrapping (default: 80).\n"
    "Examples:\n"
    "  !prettify (reply to JSON/XML/HTML)\n"
    "  !prettify --type xml '<root><item>test</item></root>'\n"
    "  !prettify --indent 4 --type json '{\"a\":1,\"b\":2}'\n"
    "Without arguments, shows this help."
)
__CATEGORY__ = "Utilities"

#------------------------------
#Detection
#------------------------------

def detect_type(text):
    """Detect if text is JSON, XML, or plain text."""
    text_stripped = text.strip()
    try:
        json.loads(text_stripped)
        return "json"
    except:
        pass
    if text_stripped.startswith("<") and text_stripped.endswith(">"):
        if re.search(r'<[^>]+>[^<]*</[^>]+>', text_stripped) or text_stripped.startswith("<?xml"):
            return "xml"
        if re.search(r'<html|<body|<div|<span|<p|<a', text_stripped, re.IGNORECASE):
            return "html"
    return "text"

#------------------------------
#Formatters
#------------------------------

def prettify_json(text, indent=2):
    try:
        data = json.loads(text)
        return json.dumps(data, indent=indent, ensure_ascii=False)
    except Exception as e:
        return f"❌ Invalid JSON: {e}"

def prettify_xml(text, indent=2):
    try:
        dom = minidom.parseString(text)
        pretty = dom.toprettyxml(indent=" " * indent)
        # Remove extra newlines that minidom adds
        lines = [line for line in pretty.splitlines() if line.strip()]
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Invalid XML: {e}"

def prettify_html(text, indent=2):
    if HAS_BS4:
        try:
            soup = BeautifulSoup(text, "html.parser")
            return soup.prettify(formatter="html", indent=" " * indent)
        except Exception as e:
            return f"❌ HTML prettify failed: {e}"
    else:
        # Fallback: try using XML parser (may fail for non-well-formed HTML)
        # We'll give a warning and try anyway
        try:
            dom = minidom.parseString(text)
            pretty = dom.toprettyxml(indent=" " * indent)
            lines = [line for line in pretty.splitlines() if line.strip()]
            return lines
        except Exception:
            return "❌ BeautifulSoup not installed.\nInstall: pip install beautifulsoup4"

def prettify_text(text, width=80):
    wrapper = textwrap.TextWrapper(width=width, replace_whitespace=False, break_long_words=False)
    wrapped = wrapper.wrap(text)
    return "\n".join(wrapped)

def parse_flags(args):
    flags = {'type': None, 'indent': 2, 'width': 80}
    remaining = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith('--'):
            if arg == '--type':
                if i+1 >= len(args):
                    raise ValueError("Missing value for --type")
                flags['type'] = args[i+1].lower()
                if flags['type'] not in ('json', 'xml', 'html'):
                    raise ValueError("Type must be 'json', 'xml', or 'html'")
                i += 2
            elif arg == '--indent':
                if i+1 >= len(args):
                    raise ValueError("Missing value for --indent")
                try:
                    flags['indent'] = int(args[i+1])
                    if flags['indent'] < 0:
                        flags['indent'] = 0
                except:
                    raise ValueError("Indent must be a number")
                i += 2
            elif arg == '--width':
                if i+1 >= len(args):
                    raise ValueError("Missing value for --width")
                try:
                    flags['width'] = int(args[i+1])
                    if flags['width'] < 10:
                        flags['width'] = 10
                except:
                    raise ValueError("Width must be a number")
                i += 2
            else:
                raise ValueError(f"Unknown flag: {arg}")
        else:
            remaining.append(arg)
            i += 1
    return flags, remaining

#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r'^!prettify(?:\s+(.*))?$'))
    async def prettify_cmd(event):
        try:
            arg_str = event.pattern_match.group(1)
            if not arg_str and not event.is_reply:
                await event.edit("📖 **Prettify Help**\n" + __HELP__)
                return

            text = None
            flags = {'type': None, 'indent': 2, 'width': 80}
            remaining = []
            if arg_str:
                args = shlex.split(arg_str)
                flags, remaining = parse_flags(args)
                if remaining:
                    text = ' '.join(remaining)

            if not text and event.is_reply:
                reply = await event.get_reply_message()
                text = reply.text or reply.raw_text
            if not text:
                await event.edit("❌ No text provided. Reply to a message or pass text in the command.")
                return

            if flags['type'] is None:
                detected = detect_type(text)
            else:
                detected = flags['type']

            output = ""
            if detected == "json":
                output = prettify_json(text, flags['indent'])
            elif detected == "xml":
                output = prettify_xml(text, flags['indent'])
            elif detected == "html":
                output = prettify_html(text, flags['indent'])
            else:
                output = prettify_text(text, flags['width'])

            if output.startswith("❌"):
                await event.edit(output)
                return

            final = f"**{detected.upper()}** prettified:\n```\n{output}\n```"
            if len(final) > 4000:
                import io
                bio = io.BytesIO(output.encode("utf-8"))
                bio.name = f"prettified.{detected}.txt"
                await client.send_file(await tgsend.peer(event), bio, caption=f"📝 Prettified ({detected})")
                await event.delete()
            else:
                await event.edit(final)

        except ValueError as e:
            await event.edit(f"❌ {e}")
        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")