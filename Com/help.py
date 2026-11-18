"""`!help` -- categories, one command, and searching by name.

Lookup order for `!help <word>`:

1. `all`            -- every command, grouped by category (as before);
2. a category       -- `!help utilities`;
3. a command family -- `!help afk` (rendered from `Com/core/registry.py`);
4. an exact command -- `!help ping` shows that command's usage and notes;
5. a name search    -- `!help pin` / a typo like `!help pign` lists every
   command whose name contains the word, or is close to it, as
   "There are N commands …: `!a`, `!b`" with a one-line description each;
6. nothing          -- suggests the closest names instead of a dead end.

The command index is built from each module's `__HELP__`, i.e. the same text
that `!help all` prints, so a command added or renamed anywhere shows up here
without a second list to maintain.
"""
from telethon import events
import difflib
import importlib
import logging
import os
from io import BytesIO

import Com.core.tgsend as tgsend
from Com.core import registry

log = logging.getLogger("selftg.help")
CHUNK = 3500  # Telegram's hard limit is 4096; leave room for the prefix
EDIT_LIMIT = 4000

__HELP__ = (
    "!help → Show available command categories\n"
    "!help all → Every command, grouped by category\n"
    "!help <category> → Commands in one category\n"
    "!help <command> → Details for one command (e.g. !help ping)\n"
    "!help <text> → Search command names (typos included)"
)
__CATEGORY__ = "Setup"

# Category mapping (folders → display name + emoji)
CATEGORY_MAP = {
    "Information": "ℹ️ Information Commands",
    "Setup": "⚙️ Setup Commands",
    "Utilities": "🛠️ Utilities Commands",
}

MAX_MATCHES = 20


#------------------------------
#Command index
#------------------------------

def _category_for(modulename):
    if any(k in modulename for k in
           ["block", "finduser", "ginfo", "whois", "info", "log"]):
        return "Information"
    if any(k in modulename for k in
           ["help", "ping", "setreaction", "update"]):
        return "Setup"
    return "Utilities"


def _command_name(line):
    """'!ban temp <user> [reason] → ...' -> '!ban'."""
    token = line.split()[0]
    return token.strip("`*_[]()<>,.;:").lower()


def _description(line):
    """The part after the arrow, for the one-line summaries."""
    for marker in ("→", "->"):
        if marker in line:
            text = line.split(marker, 1)[1].strip()
            return text
    return line


def _format_usage(line):
    """Bold + monospace the command part, like the old listing did."""
    split = line.split(" ", 1)
    cmd = f"**`{split[0]}`**"
    return f"{cmd} {split[1]}" if len(split) > 1 else cmd


def collect_commands():
    """Return (commands_by_cat, index).

    `commands_by_cat` is the display listing used by `!help all` / categories.
    `index` maps command name -> {usages, notes, module, category} for search.
    """
    commands_by_cat = {cat: [] for cat in CATEGORY_MAP}
    index = {}
    com_folder = "Com"

    for filename in sorted(os.listdir(com_folder)):
        if not filename.endswith(".py") or filename == "__init__.py":
            continue
        modulename = filename[:-3]
        try:
            module = importlib.import_module(f"{com_folder}.{modulename}")
        except Exception as exc:  # noqa: BLE001
            log.warning("help: could not import %s (%s)", modulename, exc)
            continue

        if not hasattr(module, "__HELP__"):
            continue

        category = _category_for(modulename)
        current = None
        for raw in module.__HELP__.strip().split("\n"):
            line = raw.strip()
            if not line:
                continue

            if line.startswith("!"):
                name = _command_name(line)
                entry = index.setdefault(
                    name,
                    {"name": name, "usages": [], "notes": [],
                     "module": modulename, "category": category},
                )
                entry["usages"].append(line)
                current = entry
                commands_by_cat[category].append(_format_usage(line))
            elif current is not None:
                # Continuation lines ("Subcommands:", "  geo <IP> ...").
                current["notes"].append(line)

    # The v3 families render their `__HELP__` from Com/core/registry.py, so those
    # lines are markdown ("**!afk** — …") and never start with "!". Merge their
    # declared subcommands into the index so `!help unpin` or `!help here`
    # resolve like any other command name.
    for key in registry.names():
        family = registry.get(key)
        for usage, description in family["subcommands"]:
            name = _command_name(usage)
            entry = index.setdefault(
                name,
                {"name": name, "usages": [], "notes": [],
                 "module": f"registry:{key}", "category": "Utilities"},
            )
            line = usage if "→" in usage else f"{usage} → {description}"
            if line not in entry["usages"]:
                entry["usages"].append(line)

    return commands_by_cat, index


#------------------------------
#Search
#------------------------------

def search(index, query):
    """Return (names, kind). kind is 'exact', 'partial', 'similar' or 'none'."""
    q = query.strip().lower().lstrip("!")
    if not q:
        return [], "none"

    if q in index:
        return [q], "exact"

    names = sorted(index)
    partial = [name for name in names if q in name.lstrip("!")]
    if partial:
        return partial[:MAX_MATCHES], "partial"

    close = difflib.get_close_matches(q, [n.lstrip("!") for n in names],
                                      n=MAX_MATCHES, cutoff=0.6)
    similar = [f"!{name}" for name in close if f"!{name}" in index]
    return similar, ("similar" if similar else "none")


def render_command(index, name):
    entry = index[name]
    lines = [f"📖 **`{entry['name']}`** — _{entry['module']} · {entry['category']}_"]
    for usage in entry["usages"]:
        lines.append(f"• {_format_usage(usage)}")
    if entry["notes"]:
        lines.append("")
        lines.extend(entry["notes"])
    family = registry.get(entry["name"])
    if family:
        lines.append(f"\n💡 Full family help: `!help {entry['name'].lstrip('!')}`")
    return "\n".join(lines)


def render_matches(index, names, kind, query):
    if not names:
        return None
    heading = (
        f"🗂️ There are {len(names)} commands matching `{query.strip().lstrip('!')}`:"
        if len(names) > 1
        else f"🗂️ There is 1 command matching `{query.strip().lstrip('!')}`:"
    )
    if kind == "similar":
        heading = f"🤔 No exact match for `{query.strip().lstrip('!')}`. Closest commands:"

    lines = [heading]
    for name in names:
        first = index[name]["usages"][0]
        description = _description(first)
        if len(description) > 90:
            description = description[:89] + "…"
        lines.append(f"• `{name}` — {description}")

    if kind != "similar":
        lines.append("\n💡 `!help <command>` for details.")
    return "\n".join(lines)


#------------------------------
#Command
#------------------------------

def setup(client, my_id):

    async def send_text_file(event, content, name="help.txt"):
        """Send long help as a .txt file, falling back to plain messages."""
        bio = BytesIO()
        bio.write(content.encode("utf-8"))
        bio.seek(0)
        bio.name = name
        try:
            await client.send_file(await tgsend.peer(event), bio, caption="📖 Help Commands")
            return
        except Exception as exc:  # noqa: BLE001 - degrade, never crash the handler
            log.warning("help: file delivery failed (%s), sending text chunks",
                        type(exc).__name__)

        for start in range(0, len(content), CHUNK):
            try:
                await event.reply(content[start:start + CHUNK])
            except Exception:  # noqa: BLE001
                log.warning("help: could not deliver help chunk at offset %d", start)
                return

    async def deliver(event, text, name="help.txt"):
        if len(text) > EDIT_LIMIT:
            await send_text_file(event, text, name)
        else:
            await event.edit(text)

    def render_listing(title, cmds):
        text = f"-----------------------------\n{title} ({len(cmds)})\n\n"
        last_prefix = None
        for cmd in sorted(cmds):
            prefix = cmd.split()[0]
            if last_prefix and not cmd.startswith(last_prefix):
                text += "\n"
            text += f"  • {cmd}\n"
            last_prefix = prefix
        return text + "\n"

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!help(?:\s+([\s\S]+))?$"))
    async def help_cmd(event):
        try:
            arg = (event.pattern_match.group(1) or "").strip()
            commands_by_cat, index = collect_commands()

            # no argument: category overview
            if not arg:
                text = "📖 **Available Command Categories**\n\n"
                for cat, title in CATEGORY_MAP.items():
                    text += f"{title} ({len(commands_by_cat[cat])}) → **`!help {cat.lower()}`**\n"
                text += (f"\n💡 **`!help all`** lists everything, "
                         f"**`!help ping`** shows one command, "
                         f"**`!help pin`** searches by name.")
                await deliver(event, text)
                return

            # `!help all`
            if arg.lower() == "all":
                text = "📖 **All Commands**\n\n"
                for cat, title in CATEGORY_MAP.items():
                    if commands_by_cat[cat]:
                        text += render_listing(title, commands_by_cat[cat])
                text += "💡 Tip: **`!help <command>`** for details."
                await deliver(event, text, "all_commands.txt")
                return

            # a command family from the registry
            if registry.get(arg):
                await deliver(event, "📖 " + registry.render(arg))
                return

            # a category
            for cat, title in CATEGORY_MAP.items():
                if arg.lower() == cat.lower():
                    text = render_listing(title, commands_by_cat[cat])
                    text += "\n💡 Tip: **`!help all`** to see everything."
                    await deliver(event, text)
                    return

            # exact command or name search
            names, kind = search(index, arg)
            if kind == "exact":
                await deliver(event, render_command(index, names[0]))
                return

            text = render_matches(index, names, kind, arg)
            if text:
                await deliver(event, text)
                return

            await deliver(
                event,
                f"❌ No command matches `{arg.strip().lstrip('!')}`.\n"
                "Try `!help` for categories or `!help all` for everything.",
            )

        except Exception:  # noqa: BLE001 - a help lookup must never crash the client
            log.exception("help: command failed")
            try:
                await event.edit("❌ Help failed; see the Replit log.")
            except Exception:
                pass
