# Com/storage.py
"""Crash-safe JSON persistence helpers shared by the command modules.

Every state file in this project used to be written with

    with open(path, "w") as f:
        json.dump(data, f)

which truncates the file *before* writing. If the process is killed (Replit
restarts, `!update`, a crash) in that window, the file is left empty or
half-written and the next load raises and falls back to `{}` -- silently losing
all enemies / warns / mutes / stats for that file.

`save_json` writes to a temporary file in the same directory, fsyncs it, and
atomically renames it over the target, so readers always see either the old or
the new complete document.

This module intentionally has no `setup()` and no `__HELP__`: main.py imports it
during the command scan but registers nothing for it.
"""
import json
import os
import tempfile


def load_json(path, default=None):
    """Load JSON from `path`, returning `default` if it is missing or unreadable."""
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data, indent=2):
    """Atomically write `data` as JSON to `path`."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def ensure_json_file(path, initial):
    """Create `path` with `initial` content if it does not exist yet."""
    if not os.path.exists(path):
        save_json(path, initial)
