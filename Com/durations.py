# Com/durations.py
"""The one duration parser for the whole project.

`!ban temp` and `!remind` both need to read strings like ``30m``, ``2h``, ``7d``,
``1h30m`` and ``1d12h``. They must agree on the grammar and on the error text,
so the parser lives here and both modules import it.

Bounds are parameters rather than constants because the two features have
different limits: Telegram treats a ban shorter than 30s as permanent, while a
5-second reminder is perfectly fine.

This module has no ``setup()`` and no ``__HELP__``, so main.py's loader imports
it and registers nothing.
"""
import re

UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)

FORMAT_HINT = "use forms like 30s, 10m, 2h, 7d, 1w or 1h30m"


def parse_duration(text, *, minimum=1, maximum=None):
    """Parse a human duration into seconds. Raises ValueError with a clear text.

    `minimum` / `maximum` are inclusive bounds in seconds; `maximum=None` means
    unbounded.
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError(f"no duration given — {FORMAT_HINT}")

    total = 0
    position = 0
    for match in _DURATION_RE.finditer(raw):
        if match.start() != position:
            raise ValueError(f"could not read {raw!r}; {FORMAT_HINT}")
        total += int(match.group(1)) * UNIT_SECONDS[match.group(2).lower()]
        position = match.end()

    if position != len(raw) or total <= 0:
        raise ValueError(f"could not read {raw!r}; {FORMAT_HINT}")

    if minimum is not None and total < minimum:
        raise ValueError(f"{total}s is below the {minimum}s minimum")
    if maximum is not None and total > maximum:
        raise ValueError(
            f"{total}s is above the {format_duration(maximum)} maximum"
        )
    return total


def format_duration(seconds):
    """Seconds -> compact '1d 2h 3m 4s' string."""
    seconds = int(max(0, seconds))
    parts = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            value, seconds = divmod(seconds, size)
            parts.append(f"{value}{unit}")
    return " ".join(parts) or "0s"


def looks_like_duration(text):
    """True when `text` parses as a duration (used to disambiguate arguments)."""
    try:
        parse_duration(text)
        return True
    except ValueError:
        return False
