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


#------------------------------
#Read-through cache
#------------------------------

# Five features keep a catch-all NewMessage handler that re-read a JSON file for
# *every* message in every chat (enemy, monitor, reply, cauto, stats). On a
# 0.5 vCPU box that is the most expensive thing the bot does while idle, and it
# is waste: the file only changes when this process writes it, or when the
# dashboard (a separate process) does.
#
# So: memoise by path, validate by (st_mtime_ns, st_size). A write from anywhere
# changes the stat key and the next read reloads, so a same-process write or a
# dashboard edit is never served stale. The cache holds one parsed document per
# state file in use (a dozen), not one per chat.

_cached = {}   # path -> ((mtime_ns, size), document)


def _stat_key(path):
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def cached_json(path, default=None):
    """`load_json` with a per-path memo that follows the file's mtime.

    Same contract as :func:`load_json`: a missing or unreadable file returns
    `default` (``{}`` when omitted), never raises.
    """
    key = _stat_key(path)
    if key is None:
        _cached.pop(path, None)
        return load_json(path, default)

    hit = _cached.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]

    document = load_json(path, default)
    _cached[path] = (key, document)
    return document


def clear_cache(path=None):
    """Drop one path's memo (or all of it); used by !update and tests."""
    if path is None:
        _cached.clear()
    else:
        _cached.pop(path, None)


#------------------------------
#Schemas and migrations
#------------------------------

# The v3 owner commands all keep their state in JSON documents written by
# `save_json`. Each document carries a `_version` key so a schema change is a
# deliberate migration step instead of "whatever shape the old file had".
#
# `load_store` is the only entry point: it returns a document that is guaranteed
# to be a dict at the requested version, upgrading older documents through the
# `migrations` map ({from_version: callable(old) -> new}). A document that is
# not even a dict (the v2 reminders file was a bare list) is handed to the
# version-0 migration; without one it is replaced by a fresh document rather
# than crashing the caller.
def load_store(path, version, default_factory, migrations=None):
    """Load a versioned JSON document, migrating it to `version` if needed."""
    raw = load_json(path, None)
    if raw is None:
        document = default_factory()
        document["_version"] = version
        return document

    migrations = migrations or {}

    if not isinstance(raw, dict):
        migrate = migrations.get(0)
        document = migrate(raw) if migrate else default_factory()
        if not isinstance(document, dict):
            document = default_factory()
        document["_version"] = version
        return document

    current = int(raw.get("_version", 0) or 0)
    if current > version:
        # Written by a newer build: keep the data, do not invent a downgrade.
        return raw

    while current < version:
        migrate = migrations.get(current)
        if migrate:
            migrated = migrate(raw)
            raw = migrated if isinstance(migrated, dict) else raw
        current += 1
        raw["_version"] = current
    return raw
