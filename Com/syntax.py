"""!syntax: Pygments highlighting with line numbers."""
import os
import sys
import re
from telethon import events
import Com.core.tgsend as tgsend
from Com.core import brand
from Com.core.reply import say
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer, get_all_lexers
from pygments.formatters import TerminalFormatter
from pygments.util import ClassNotFound

__HELP__ = (
    "!syntax [lang] (reply to code) → Syntax highlight code with line numbers.\n"
    "If language is not provided, it will be auto-detected.\n"
    "Example: !syntax python (reply to code)\n"
    "Common languages: python, javascript, typescript, java, cpp, csharp, go, ruby,\n"
    "  php, html, css, json, yaml, xml, sql, bash, rust, swift, kotlin, dart,\n"
    "  scala, r, matlab, perl, lua, haskell, elixir, clojure, erlang, groovy,\n"
    "  julia, nim, zig, vlang, crystal, ... (over 500 languages supported)\n"
    "Use !syntax --list to see all languages."
)
__CATEGORY__ = "Utilities"

#------------------------------
#Detection
#------------------------------

def detect_language(code):
    """Try to guess the language using Pygments."""
    try:
        lexer = guess_lexer(code)
        return lexer.name.lower()
    except:
        # Fallback: shebang detection
        lines = code.splitlines()
        if lines:
            first = lines[0].strip()
            if first.startswith("#!"):
                shebang = first[2:].lower()
                if "python" in shebang:
                    return "python"
                elif "node" in shebang or "js" in shebang:
                    return "javascript"
                elif "bash" in shebang or "sh" in shebang:
                    return "bash"
                elif "php" in shebang:
                    return "php"
                elif "perl" in shebang:
                    return "perl"
                elif "ruby" in shebang:
                    return "ruby"
                elif "deno" in shebang:
                    return "typescript"
        return "text"

def format_code_with_lines(code, lang):
    lines = code.splitlines()
    max_digits = len(str(len(lines)))
    numbered = []
    for i, line in enumerate(lines, 1):
        num = str(i).rjust(max_digits)
        numbered.append(f"{num}  {line}")
    return "\n".join(numbered)

def get_all_languages():
    """Return a sorted list of all lexer names."""
    names = set()
    for lexer in get_all_lexers():
        names.add(lexer[0].lower())
    return sorted(names)

#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!syntax(?:\s+(\S+))?$"))
    async def syntax_cmd(event):
        try:
            arg = event.pattern_match.group(1)

            if arg and arg == "--list":
                langs = get_all_languages()
                msg = (f"📚 <b>Supported languages</b> "
                       f"<i>({len(langs)} total)</i>\n"
                       f"{brand.esc(', '.join(langs[:100]))}…")
                if len(msg) > 4000:
                    import io
                    bio = io.BytesIO(("\n".join(langs)).encode("utf-8"))
                    bio.name = "languages.txt"
                    await client.send_file(
                        await tgsend.peer(event), bio,
                        caption=brand.sign("📚 <b>All supported languages</b>",
                                           "syntax"),
                        parse_mode="html")
                    await event.delete()
                else:
                    await say(event, msg, name="syntax", parse_mode="html")
                return

            lang = arg
            code = None

            if event.is_reply:
                reply_msg = await event.get_reply_message()
                code = reply_msg.text or reply_msg.raw_text
            else:
                await say(event,
                          "❌ Reply to a message containing code.\n"
                          "Usage · <code>!syntax [lang]</code> "
                          "<i>(reply to code)</i>",
                          name="syntax", parse_mode="html")
                return

            if not code:
                await say(event, "❌ No code found in the replied message.",
                          name="syntax")
                return

            if not lang:
                lang = detect_language(code)
            else:
                try:
                    get_lexer_by_name(lang)
                except ClassNotFound:
                    langs = get_all_languages()
                    suggestions = [l for l in langs if lang.lower() in l]
                    if suggestions:
                        await say(event,
                                  f"❌ Language <code>{brand.esc(lang)}</code> "
                                  "not recognized.\n"
                                  f"Did you mean · "
                                  f"<code>{', '.join(suggestions[:5])}</code>?\n"
                                  "Use <code>!syntax --list</code> for all "
                                  "languages.",
                                  name="syntax", parse_mode="html")
                    else:
                        await say(event,
                                  f"❌ Language <code>{brand.esc(lang)}</code> "
                                  "not recognized.\n"
                                  "Use <code>!syntax --list</code> for all "
                                  "languages.",
                                  name="syntax", parse_mode="html")
                    return

            code_with_lines = format_code_with_lines(code, lang)
            output = (f"📝 <b>Language</b> · <code>{brand.esc(lang)}</code>\n"
                      f"<code>{brand.esc(code_with_lines)}</code>")

            if len(output) > 4000:
                import io
                bio = io.BytesIO(brand.plain(output).encode("utf-8"))
                bio.name = f"syntax.{lang}.txt"
                await client.send_file(
                    await tgsend.peer(event), bio,
                    caption=brand.sign(
                        f"📝 <b>Syntax</b> · <code>{brand.esc(lang)}</code>",
                        "syntax"),
                    parse_mode="html")
                await event.delete()
            else:
                await say(event, output, name="syntax", parse_mode="html")

        except Exception as e:
            await say(event, f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="syntax", parse_mode="html")