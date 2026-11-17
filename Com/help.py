# Com/help.py
from telethon import events
import Com.tgsend as tgsend
import importlib
import logging
import os
from io import BytesIO

from Com import registry

log = logging.getLogger("selftg.help")
CHUNK = 3500  # Telegram's hard limit is 4096; leave room for the prefix

__HELP__ = "!help → Show available command categories or commands in a category"
__CATEGORY__ = "Setup"

# Category mapping (folders → display name + emoji)
CATEGORY_MAP = {
    "Information": "ℹ️ Information Commands",
    "Setup": "⚙️ Setup Commands",
    "Utilities": "🛠️ Utilities Commands",
}


def setup(client, my_id):

    def collect_commands():
        """Collect commands from Com/*.py and organize by category."""
        commands_by_cat = {cat: [] for cat in CATEGORY_MAP.keys()}
        com_folder = "Com"

        for filename in os.listdir(com_folder):
            if filename.endswith(".py") and filename != "__init__.py":
                modulename = filename[:-3]
                try:
                    module = importlib.import_module(
                        f"{com_folder}.{modulename}")
                except Exception as e:
                    print(f"❌ Failed to import {modulename}: {e}")
                    continue

                if hasattr(module, "__HELP__"):
                    help_text = module.__HELP__.strip()
                    parts = [
                        p.strip() for p in help_text.split("\n") if p.strip()
                    ]

                    # Try to map by folder name (default Utilities)
                    folder = "Utilities"
                    if any(
                            k in modulename for k in
                        ["block", "finduser", "ginfo", "whois", "info", "log"
                         ]):
                        folder = "Information"
                    elif any(k in modulename for k in
                             ["help", "ping", "setreaction", "update"]):
                        folder = "Setup"

                    for part in parts:
                        # Format command bold + monospace
                        if part.startswith("!"):
                            split = part.split(" ", 1)
                            cmd = f"**`{split[0]}`**"
                            part = f"{cmd} {split[1]}" if len(
                                split) > 1 else cmd
                        commands_by_cat[folder].append(part)
        return commands_by_cat

    async def send_text_file(event, content, name="help.txt"):
        """Send the long help as a .txt file, falling back to plain messages.

        The file upload used to raise `ValueError: Could not find the input entity`
        in private chats because it targeted `event.chat_id` directly (see
        Com/tgsend.py). The peer is now resolved from the event, and if the upload
        still fails for any reason the text is delivered in chunks instead of
        leaving `help_cmd` with an unhandled exception.
        """
        bio = BytesIO()
        bio.write(content.encode("utf-8"))
        bio.seek(0)
        bio.name = name
        try:
            await client.send_file(await tgsend.peer(event), bio, caption="📖 Help Commands")
            return
        except Exception as exc:  # noqa: BLE001 - degrade, never crash the handler
            log.warning("help: file delivery failed (%s), sending text chunks", type(exc).__name__)

        for start in range(0, len(content), CHUNK):
            try:
                await event.reply(content[start:start + CHUNK])
            except Exception:  # noqa: BLE001
                log.warning("help: could not deliver help chunk at offset %d", start)
                return

    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!help(\s+\w+)?$"))
    async def help_cmd(event):
        arg = event.pattern_match.group(1)
        commands_by_cat = collect_commands()

        if not arg:
            text = "📖 **Available Command Categories**\n\n"
            for cat, title in CATEGORY_MAP.items():
                count = len(commands_by_cat[cat])
                text += f"{title} ({count}) → **`!help {cat.lower()}`**\n"
            text += "\n💡 Tip: Use **`!help all`** to see everything."
            if len(text) > 4000:
                await send_text_file(event, text)
            else:
                await event.edit(text)
            return

        arg = arg.strip().lower()
        if arg == "all":
            text = "📖 **All Commands**\n\n"
            for cat, title in CATEGORY_MAP.items():
                cmds = sorted(commands_by_cat[cat])
                if not cmds:
                    continue
                text += f"-----------------------------\n{title} ({len(cmds)})\n\n"
                last_prefix = None
                for cmd in cmds:
                    prefix = cmd.split()[0]
                    if last_prefix and not cmd.startswith(last_prefix):
                        text += "\n"
                    text += f"  • {cmd}\n"
                    last_prefix = prefix
                text += "\n"
            text += "💡 Tip: Use **`!help <Category>`** to view only one category."
            if len(text) > 4000:
                await send_text_file(event, text)
            else:
                await event.edit(text)
            return

        # Single command family (`!help afk`) -- rendered from the registry the
        # module itself declared, so subcommands cannot drift from the code.
        if registry.get(arg):
            text = "📖 " + registry.render(arg)
            if len(text) > 4000:
                await send_text_file(event, text)
            else:
                await event.edit(text)
            return

        # Category-specific
        for cat, title in CATEGORY_MAP.items():
            if arg == cat.lower():
                cmds = sorted(commands_by_cat[cat])
                text = f"-----------------------------\n{title} ({len(cmds)})\n\n"
                last_prefix = None
                for cmd in cmds:
                    prefix = cmd.split()[0]
                    if last_prefix and not cmd.startswith(last_prefix):
                        text += "\n"
                    text += f"  • {cmd}\n"
                    last_prefix = prefix
                text += "\n💡 Tip: Use **`!help all`** to see all categories together."
                if len(text) > 4000:
                    await send_text_file(event, text)
                else:
                    await event.edit(text)
                return

        await event.edit(
            "❌ Unknown category. Use **`!help`** to see available ones.")
