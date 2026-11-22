"""Single source of truth for the v3 owner commands and their subcommands.

Each command module declares its subcommands once, as data::

    SUBCOMMANDS = [
        ("!afk [reason]", "set away status"),
        ...
    ]
    __HELP__ = registry.command(
        "afk", SUBCOMMANDS, "Away status with DM auto-replies.",
        aliases=["!afk back"],
    )

The same table produces the module's ``__HELP__`` (which the existing `!help`
already renders) and the registry entry that `!help afk` looks up, so the help
text cannot drift from the subcommand list: they are the same object.

This module has no ``setup()`` and no ``__HELP__``.
"""

_REGISTRY = {}


def command(name, subcommands, description, aliases=None):
    """Register a command family and return its rendered help text."""
    key = name.lstrip("!").lower()
    _REGISTRY[key] = {
        "name": f"!{key}",
        "subcommands": list(subcommands),
        "description": description,
        "aliases": list(aliases or []),
    }
    return render(key)


def render(name):
    """Render one command family's help text (`name` with or without '!')."""
    entry = _REGISTRY.get(name.lstrip("!").lower())
    if not entry:
        return None
    # Plain text: modules embed this in HTML bodies through brand.esc, and
    # `!help` escapes it too, so markdown markers must not be here.
    lines = [f"{entry['name']} — {entry['description']}"]
    for usage, description in entry["subcommands"]:
        lines.append(f"• {usage} — {description}")
    if entry["aliases"]:
        lines.append("aliases: " + ", ".join(entry["aliases"]))
    return "\n".join(lines)


def get(name):
    return _REGISTRY.get(name.lstrip("!").lower())


def names():
    return sorted(_REGISTRY)
