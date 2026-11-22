"""`!creator` -- the credit line this account prints when asked who made it.

Scope
-----
All three forms are **owner-only**. Every self-bot command is registered with
``from_users=my_id``; that filter is the project's single owner check. A public
``!creator`` would need a second, differently shaped handler that answers other
people in every chat, costs an outgoing message per stranger, and could drift
from the owner gate used everywhere else. The owner runs it and copies the line
wherever it is needed.

Storage
-------
The username lives in ``mode/settings.json`` -- the same store ``!remind tz``
uses -- under ``creator_username``. It is not a secret, so it does not belong in
Replit Secrets, and it has to survive a restart, so it is not a constant.

Reads and writes go through ``Com.core.storage``; ``save_json`` writes a
temporary file and renames it over the target, so a Repl restart in the middle
of a write cannot leave a truncated document.

Existing installs have an unversioned settings file (``dashboard.py`` writes it
without ``_version``). ``load_store`` reads it as-is, every other key is kept,
and the next write stamps ``_version: 1``. No migration function is needed; the
dashboard toggles and ``timezone`` survive untouched.

When the write fails (read-only ``mode/``, disk error, unreadable file) the
command says so and does not claim the username was saved. A read that fails is
treated as "not set", which is the same fail-open behaviour the other stores in
the project have.

Why no confirmation token for ``clear``
---------------------------------------
``clear`` removes one value that the owner can put back with one command. The
token flow in ``Com/core/confirm.py`` exists for jobs that delete many entries;
asking for a token here would be ceremony, not safety.
"""
import logging
import re

from telethon import events

import Com.core.registry as registry
from Com.core.reply import say
from Com.core.storage import load_store, save_json

log = logging.getLogger("selftg.creator")

SETTINGS_FILE = "mode/settings.json"
SETTINGS_VERSION = 1
KEY = "creator_username"

# Telegram's username shape: 5-32 characters, a letter first, then letters,
# digits or '_'. This is a format check only: the command never resolves the
# name, because that would be a network request and a flood cost for one line
# of text. A typo in a valid-looking name is the owner's typo, printed as-is.
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")

SUBCOMMANDS = [
    ("!creator", "show `Made by @<username>`"),
    ("!creator set <username>", "save the username (a leading @ is optional)"),
    ("!creator clear", "remove the saved username"),
]

__HELP__ = registry.command(
    "creator", SUBCOMMANDS,
    "Credit line for this account; owner-only, stored in `mode/settings.json`.",
)
__CATEGORY__ = "Utilities"


#------------------------------
#State
#------------------------------

def normalize_username(raw):
    """``@Some_User`` -> ``some_user``; raises ValueError on a bad shape."""
    name = (raw or "").strip()
    if name.startswith("@"):
        name = name[1:].strip()
    if not name:
        raise ValueError("give a username, e.g. `!creator set @yourname`")
    if not USERNAME_RE.match(name):
        raise ValueError(
            "that is not a Telegram username (5-32 characters, a letter first, "
            "then letters, digits or `_`)"
        )
    # Usernames are case-insensitive; one canonical form avoids @Foo vs @foo.
    return name.lower()


def load_username():
    """Return the stored username in canonical form, or None. Never raises."""
    try:
        data = load_store(SETTINGS_FILE, SETTINGS_VERSION, dict)
    except Exception:  # noqa: BLE001 - an unreadable store means "not set"
        log.exception("creator: could not read %s", SETTINGS_FILE)
        return None
    value = data.get(KEY) if isinstance(data, dict) else None
    if not isinstance(value, str):
        return None
    value = value.strip().lstrip("@").lower()
    return value or None


def store_username(username):
    """Save `username`, or remove it when falsy. True only on a real write."""
    try:
        data = load_store(SETTINGS_FILE, SETTINGS_VERSION, dict)
    except Exception:  # noqa: BLE001 - refuse rather than clobber an unknown file
        log.exception("creator: could not read %s", SETTINGS_FILE)
        return False
    if not isinstance(data, dict):
        data = {}
    if username:
        data[KEY] = username
    else:
        data.pop(KEY, None)
    data.setdefault("_version", SETTINGS_VERSION)
    try:
        save_json(SETTINGS_FILE, data)
    except Exception:  # noqa: BLE001 - report it; save_json kept the old file
        log.exception("creator: could not write %s", SETTINGS_FILE)
        return False
    return True


#------------------------------
#Command handler
#------------------------------

def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!creator(?:\s+([\s\S]*))?$"))
    async def creator_cmd(event):
        if not event.out or event.sender_id != my_id:
            return

        args = (event.pattern_match.group(1) or "").strip()
        head, _, rest = args.partition(" ")
        sub = head.lower()
        rest = rest.strip()

        try:
            if not args:
                username = load_username()
                if username is None:
                    await _say(
                        event,
                        "❌ No creator set yet. Use `!creator set @yourname`.",
                    )
                else:
                    await _say(event, f"Made by @{username}")
                return

            if sub == "set":
                try:
                    username = normalize_username(rest)
                except ValueError as exc:
                    await _say(event, f"❌ {exc}")
                    return
                if not store_username(username):
                    await _say(
                        event,
                        f"❌ Could not save the username: `{SETTINGS_FILE}` is "
                        "unavailable. Nothing was changed.",
                    )
                    return
                await _say(event, f"✅ Creator set to `@{username}`.")
                return

            if sub == "clear":
                if rest:
                    await _say(event, "Usage: `!creator clear`")
                    return
                existing = load_username()
                if existing is None:
                    await _say(event, "ℹ️ No creator was set; nothing to clear.")
                    return
                if not store_username(None):
                    await _say(
                        event,
                        f"❌ Could not update `{SETTINGS_FILE}`; nothing was "
                        "changed.",
                    )
                    return
                await _say(event, f"🗑️ Creator `@{existing}` cleared.")
                return

            await _say(event, "📖 " + __HELP__)

        except Exception:  # noqa: BLE001 - never take the client down
            log.exception("creator: command failed")
            await _say(event, "❌ Creator command failed; see the Replit log.")

    async def _say(event, text):
        # Edit-then-reply is shared: see Com/core/reply.py.
        await say(event, text, name="creator")
