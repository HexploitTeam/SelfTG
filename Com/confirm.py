# Com/confirm.py
"""The one confirmation-token helper for destructive subcommands.

`!note clear`, `!todo clear all` and `!remind clear` all have to be impossible to
trigger by accident, and they must all ask in the same way. A random token is
generated per (chat, action), stored with an expiry in `mode/confirm.json`, and
the command only executes when the owner repeats it with that exact token.

Why a random token instead of the word "confirm": "confirm" is muscle memory —
a user who typed `!remind clear confirm` once will type it again. A token that
is only in the message the bot just printed cannot be guessed.

This module has no ``setup()`` and no ``__HELP__``.
"""
import os
import secrets
import time

from Com.storage import load_json, save_json

CONFIRM_FILE = "mode/confirm.json"
TOKEN_TTL = 300  # seconds the prompt stays valid
os.makedirs("mode", exist_ok=True)


def _load():
    data = load_json(CONFIRM_FILE, {})
    return data if isinstance(data, dict) else {}


def _save(data):
    now = time.time()
    # Drop expired prompts so the file cannot grow without bound.
    pruned = {
        key: value
        for key, value in data.items()
        if isinstance(value, dict) and float(value.get("expires", 0)) > now
    }
    save_json(CONFIRM_FILE, pruned)


def _key(chat_id, action):
    return f"{chat_id}:{action}"


def request(chat_id, action, summary):
    """Create a prompt: returns the message text including the token."""
    token = secrets.token_hex(3)  # 6 hex chars: short to type, not guessable
    data = _load()
    data[_key(chat_id, action)] = {"token": token, "expires": time.time() + TOKEN_TTL}
    _save(data)
    return (
        f"⚠️ {summary}\n"
        f"Confirm within {TOKEN_TTL // 60} minutes: "
        f"`{action} confirm {token}`"
    )


def check(chat_id, action, text):
    """True when `text` carries the live token for this chat/action."""
    data = _load()
    entry = data.get(_key(chat_id, action))
    if not entry:
        return False
    if float(entry.get("expires", 0)) <= time.time():
        data.pop(_key(chat_id, action), None)
        _save(data)
        return False

    words = (text or "").split()
    if not words:
        return False
    if words[-1] != entry["token"]:
        return False

    data.pop(_key(chat_id, action), None)  # single use
    _save(data)
    return True


def clear(chat_id, action=None):
    """Forget a pending prompt (after a successful action or an explicit cancel)."""
    data = _load()
    if action is None:
        prefix = f"{chat_id}:"
        for key in [k for k in data if k.startswith(prefix)]:
            data.pop(key, None)
    else:
        data.pop(_key(chat_id, action), None)
    _save(data)
