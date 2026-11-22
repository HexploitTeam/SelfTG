"""`!typo` -- one "command not found" answer for a name nothing handles.

Why a fallback instead of a dispatcher
--------------------------------------
Every command registers its own `client.on(events.NewMessage(pattern=...))`;
there is no central table with a "no match" branch, and adding one would mean
rewriting dispatch. This module answers only when *no* registered pattern
matches the message, so it cannot take a message away from a real command.

Matching reuses the handlers' own compiled patterns -- the same regex Telethon
runs -- so case-insensitive patterns (`(?i)^!reaction`) and alternations behave
exactly as they do in dispatch; there is no second list of names to keep in
step with the code. Two handlers are skipped: this module's own (it matches
every `!word`) and `Com/alias.py`'s (its pattern matches every Persian word, so
`PERSIAN_ALIASES` is consulted instead).

A name `!help` advertises also counts as known. Many commands only match with
their arguments (`!imgresize <w>x<h>`, `!kill <N>`), so a bare `!imgresize`
matches no pattern while still being a real command; calling that "not found"
would be a lie.

Registered from `main._on_ready` after `load_commands()`, not by `Com/`'s
auto-loader: the handler list has to be complete, including the modules whose
filenames sort after this file.

This module has no ``__HELP__``: `!help` must not list it as a command.
"""
import logging

from telethon import events

from Com.core import brand
from Com.core.reply import say

log = logging.getLogger("selftg.notfound")


#------------------------------
#Known commands
#------------------------------

def _handled(client, text):
    """True when a registered handler pattern already matches `text`."""
    try:
        handlers = client.list_event_handlers()
    except Exception:  # noqa: BLE001 - a missing answer must not crash the client
        log.info("notfound: could not list handlers", exc_info=True)
        return False

    for callback, builder in handlers:
        # Ours matches every `!word`; Com/alias.py matches every Persian word
        if getattr(callback, "__module__", "") in ("Com.alias", __name__):
            continue
        pattern = getattr(builder, "pattern", None)
        if not pattern:
            continue
        try:
            if pattern(text):
                return True
        except Exception:  # noqa: BLE001 - a broken pattern is not this module's job
            continue
    return False


def _aliases():
    """The Persian alias table, or an empty map when it cannot be imported."""
    try:
        from Com.alias import PERSIAN_ALIASES
    except Exception:  # noqa: BLE001
        log.info("notfound: alias table unavailable", exc_info=True)
        return {}
    return PERSIAN_ALIASES


def _documented():
    """Command names `!help` advertises, lowercased."""
    try:
        from Com.help import collect_commands

        _, index = collect_commands()
    except Exception:  # noqa: BLE001
        log.info("notfound: help index unavailable", exc_info=True)
        return set()
    return {name.lstrip("!").lower() for name in index}


def _is_known(client, text, name, aliases, documented):
    """True when `!name` belongs to a command: a handler pattern or `!help`."""
    if name in aliases or name.lower() in documented:
        return True
    return _handled(client, text)


#------------------------------
#Command handler
#------------------------------

def setup(client, my_id):
    aliases = _aliases()
    documented = _documented()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!(\S+)"))
    async def unknown_command(event):
        if not event.out or event.sender_id != my_id:
            return

        name = event.pattern_match.group(1)
        if _is_known(client, event.raw_text, name, aliases, documented):
            return

        # A typo can carry markup; it must not break the answer's own formatting
        shown = name.replace("`", "").replace("*", "").replace("_", "")
        await say(
            event,
            f"❌ <b>Command not found</b> · <code>!{brand.esc(shown)}</code>\n"
            "💡 <code>!help all</code> lists every command, "
            "<code>!help &lt;name&gt;</code> explains one.",
            name="notfound",
            parse_mode="html",
        )
