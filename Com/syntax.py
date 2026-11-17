# Com/syntax.py
import os
import sys
import re
from telethon import events
import Com.tgsend as tgsend
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
    "Use `!syntax --list` to see all languages."
)
__CATEGORY__ = "Utilities"

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

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!syntax(?:\s+(\S+))?$"))
    async def syntax_cmd(event):
        try:
            arg = event.pattern_match.group(1)

            # Handle --list flag
            if arg and arg == "--list":
                langs = get_all_languages()
                # Send in chunks if too long
                msg = "📚 **Supported languages:**\n" + ", ".join(langs[:100]) + "..."
                if len(msg) > 4000:
                    import io
                    bio = io.BytesIO(("\n".join(langs)).encode("utf-8"))
                    bio.name = "languages.txt"
                    await client.send_file(await tgsend.peer(event), bio, caption="📚 All supported languages")
                    await event.delete()
                else:
                    await event.edit(msg)
                return

            # Determine input (reply or provided text)
            lang = arg
            code = None

            if event.is_reply:
                reply_msg = await event.get_reply_message()
                code = reply_msg.text or reply_msg.raw_text
            else:
                await event.edit("❌ Reply to a message containing code.\n"
                                 "Usage: `!syntax [lang]` (reply to code)")
                return

            if not code:
                await event.edit("❌ No code found in the replied message.")
                return

            # Auto-detect language if not provided
            if not lang:
                lang = detect_language(code)
            else:
                # Validate that the language exists
                try:
                    get_lexer_by_name(lang)
                except ClassNotFound:
                    # Try a fuzzy match
                    langs = get_all_languages()
                    suggestions = [l for l in langs if lang.lower() in l]
                    if suggestions:
                        await event.edit(f"❌ Language '{lang}' not recognized.\n"
                                         f"Did you mean: {', '.join(suggestions[:5])}?\n"
                                         f"Use `!syntax --list` for all languages.")
                    else:
                        await event.edit(f"❌ Language '{lang}' not recognized.\n"
                                         "Use `!syntax --list` for all languages.")
                    return

            # Build output
            code_with_lines = format_code_with_lines(code, lang)
            output = f"📝 **Language:** {lang}\n```{lang}\n{code_with_lines}\n```"

            if len(output) > 4000:
                import io
                bio = io.BytesIO(output.encode("utf-8"))
                bio.name = f"syntax.{lang}.txt"
                await client.send_file(await tgsend.peer(event), bio, caption=f"📝 Syntax: {lang}")
                await event.delete()
            else:
                await event.edit(output)

        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")