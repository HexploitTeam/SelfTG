"""Primitives for the owner bot: callback data, keyboards, paging and flows.

Why this module exists
----------------------
The bot's whole interface is one message that is edited in place: pressing a
button replaces that message with the next screen, and Back returns to the
previous one. That only works if three things are boring and shared:

* **callback data** is short, parseable and never above Telegram's 64-byte cap;
* **keyboards and text** are built the same way on every screen;
* **multi-step flows** live in a file, not in memory, so a Replit restart in the
  middle of "send a message as me" does not silently drop the user's input.

Callback data is ``b1:<route>:<args…>``. Anything unknown or stale is answered
with a plain "this menu is out of date" and replaced by the main menu, so no
button can spin forever (Telegram hides the spinner after ~10 s, and an
unanswered callback looks like a dead button).
"""
import html
import logging
import secrets
import time
from dataclasses import dataclass, field

from telethon.errors import MessageNotModifiedError
from telethon.tl.types import (
    KeyboardButtonCallback,
    KeyboardButtonCopy,
    KeyboardButtonRow,
    KeyboardButtonStyle,
    KeyboardButtonUrl,
    ReplyInlineMarkup,
)

from Com.core.storage import load_json, save_json

log = logging.getLogger("selftg.botkit")

STATE_FILE = "mode/botstate.json"
SCHEMA_VERSION = 1
FLOW_TTL = 15 * 60
PENDING_TTL = 5 * 60
CALLBACK_LIMIT = 64
PREFIX = "b1"
DEFAULT_PAGE_SIZE = 5

DEFAULT_SETTINGS = {
    "page_size": DEFAULT_PAGE_SIZE,
    "alerts": True,
}


#------------------------------
#State
#------------------------------

def _default_state():
    return {
        "_version": SCHEMA_VERSION,
        "settings": dict(DEFAULT_SETTINGS),
        "flows": {},
        "pending": {},
    }


def load_state():
    data = load_json(STATE_FILE, None)
    if not isinstance(data, dict):
        return _default_state()
    data.setdefault("_version", SCHEMA_VERSION)
    settings = data.get("settings")
    if not isinstance(settings, dict):
        data["settings"] = dict(DEFAULT_SETTINGS)
    else:
        for key, value in DEFAULT_SETTINGS.items():
            settings.setdefault(key, value)
    for key in ("flows", "pending"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    return data


def save_state(state):
    try:
        save_json(STATE_FILE, state)
        return True
    except Exception:  # noqa: BLE001 - a broken UI store must not kill the bot
        log.exception("botkit: could not write %s", STATE_FILE)
        return False


def settings():
    return load_state()["settings"]


def set_setting(key, value):
    state = load_state()
    state["settings"][key] = value
    return save_state(state)


def page_size():
    try:
        return max(1, min(10, int(settings().get("page_size", DEFAULT_PAGE_SIZE))))
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE


#------------------------------
#Callback data
#------------------------------

def cb(*parts):
    """Encode callback data, refusing anything Telegram would reject."""
    data = (PREFIX + ":" + ":".join(str(part) for part in parts)).encode("utf-8")
    if len(data) > CALLBACK_LIMIT:
        raise ValueError(f"callback data is {len(data)} bytes: {data!r}")
    return data


def parse_cb(raw):
    """Decode callback data into a route tuple; raises ValueError when foreign."""
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    parts = text.split(":")
    if len(parts) < 2 or parts[0] != PREFIX:
        raise ValueError(f"not a {PREFIX} callback: {text!r}")
    return tuple(parts[1:])


#------------------------------
#Screens
#------------------------------

@dataclass
class Screen:
    """One bot message: HTML text plus a grid of (label, data) buttons."""
    text: str
    rows: list = field(default_factory=list)


@dataclass(frozen=True)
class Copy:
    """Button data that copies text instead of calling back.

    Layer 227's ``keyboardButtonCopy`` is documented as inline-only, which is
    exactly what this bot sends. No callback arrives, so nothing to route.
    """
    text: str


# Named styles, as the clients show them; unknown names simply drop the style
BUTTON_STYLES = {
    "primary": KeyboardButtonStyle(bg_primary=True),
    "success": KeyboardButtonStyle(bg_success=True),
    "danger": KeyboardButtonStyle(bg_danger=True),
}


def btn(label, *parts, style=None):
    return (label, cb(*parts), style)


def url_btn(label, url, style=None):
    return (label, url, style)


def copy_btn(label, text, style=None):
    return (label, Copy(text), style)


def markup(rows):
    built = []
    for row in rows:
        buttons = []
        for entry in row:
            label, data = entry[0], entry[1]
            style = BUTTON_STYLES.get(entry[2]) if len(entry) > 2 else None
            if isinstance(data, Copy):
                buttons.append(KeyboardButtonCopy(label, data.text, style=style))
            elif isinstance(data, str) and data.startswith("http"):
                buttons.append(KeyboardButtonUrl(label, data, style=style))
            else:
                buttons.append(KeyboardButtonCallback(label, data, style=style))
        if buttons:
            built.append(KeyboardButtonRow(buttons))
    return ReplyInlineMarkup(built) if built else None


def h(value, limit=None):
    """HTML-escape user data; truncate before escaping so entities stay whole."""
    text = str(value)
    if limit is not None and len(text) > limit:
        text = text[: max(0, limit - 1)] + "…"
    return html.escape(text, quote=False)


def age(seconds):
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m"
    return f"{seconds // 86400}d {seconds % 86400 // 3600}h"


def clock(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return "?"


def paginate(items, page):
    """Return (chunk, page, pages) with page clamped to the real range."""
    size = page_size()
    pages = max(1, (len(items) + size - 1) // size)
    try:
        page = max(0, min(int(page), pages - 1))
    except (TypeError, ValueError):
        page = 0
    return items[page * size:(page + 1) * size], page, pages


def pager_row(route, page, pages, *fixed):
    """A ‹ Prev | n/m | Next › row; the page is always the last callback arg."""
    if pages <= 1:
        return []
    prev_label = "‹ Prev" if page > 0 else "· Prev"
    next_label = "Next ›" if page < pages - 1 else "Next ·"
    return [
        btn(prev_label, *route, *fixed, max(0, page - 1)),
        btn(f"{page + 1}/{pages}", *route, *fixed, page),
        btn(next_label, *route, *fixed, min(pages - 1, page + 1)),
    ]


#------------------------------
#Sending
#------------------------------

async def send(ctx, screen, chat_id=None, reply_to=None):
    return await ctx.client.send_message(
        chat_id or ctx.owner_id,
        screen.text,
        buttons=markup(screen.rows),
        parse_mode="html",
        link_preview=False,
        reply_to=reply_to,
    )


async def edit(event, screen):
    """Edit the menu message; returns False when it cannot be edited any more."""
    try:
        await event.edit(
            screen.text,
            buttons=markup(screen.rows),
            parse_mode="html",
            link_preview=False,
        )
        return True
    except MessageNotModifiedError:
        return True
    except Exception:  # noqa: BLE001 - old message, deleted chat, no rights
        log.info("botkit: menu message could not be edited", exc_info=True)
        return False


async def answer(event, text=None, alert=False):
    """Answer a callback at most once; the spinner must never be left hanging.

    Both the router and the screen dispatcher want to answer, so the guard lives
    on the event: Telegram rejects a second answer for the same query id, and a
    toast from the router would otherwise overwrite the screen's own toast.
    """
    if getattr(event, "_selftg_answered", False):
        return True
    event._selftg_answered = True
    try:
        await event.answer(text or "", alert=alert)
        return True
    except Exception:  # noqa: BLE001 - query expired between tap and answer
        return False


#------------------------------
#Flows
#------------------------------

def prune():
    """Drop expired flows and pending tokens; returns how many were removed.

    Expiry used to be lazy: an entry disappeared only when the owner opened that
    screen again, so `mode/botstate.json` kept dead flows -- and the chat ids in
    them -- for as long as the bot ran. The bot heartbeat calls this every 30 s,
    which bounds the file without adding a task.
    """
    now = time.time()
    state = load_state()
    removed = 0
    for bucket in ("flows", "pending"):
        for key, entry in list(state[bucket].items()):
            expires = float(entry.get("expires", 0) or 0) if isinstance(entry, dict) else 0
            if expires <= now:
                state[bucket].pop(key, None)
                removed += 1
    if removed:
        save_state(state)
    return removed


def start_flow(owner_id, name, step, data=None, ttl=FLOW_TTL):
    state = load_state()
    state["flows"][str(owner_id)] = {
        "name": name,
        "step": step,
        "data": dict(data or {}),
        "expires": time.time() + ttl,
    }
    if not save_state(state):
        return False
    return True


def active_flow(owner_id):
    """Return the live flow for this owner, dropping it if it has expired."""
    state = load_state()
    flow = state["flows"].get(str(owner_id))
    if not isinstance(flow, dict):
        return None
    if float(flow.get("expires", 0) or 0) <= time.time():
        state["flows"].pop(str(owner_id), None)
        save_state(state)
        return None
    return flow


def update_flow(owner_id, *, step=None, data=None):
    state = load_state()
    flow = state["flows"].get(str(owner_id))
    if not isinstance(flow, dict):
        return None
    if step is not None:
        flow["step"] = step
    if data:
        flow.setdefault("data", {}).update(data)
    flow["expires"] = time.time() + FLOW_TTL
    save_state(state)
    return flow


def clear_flow(owner_id):
    state = load_state()
    if state["flows"].pop(str(owner_id), None) is not None:
        save_state(state)


#------------------------------
#Pending actions (confirmations)
#------------------------------

def new_pending(action, payload, ttl=PENDING_TTL):
    """Store a destructive action behind a single-use token."""
    token = secrets.token_hex(4)
    state = load_state()
    now = time.time()
    state["pending"] = {
        key: value
        for key, value in state["pending"].items()
        if isinstance(value, dict) and float(value.get("expires", 0) or 0) > now
    }
    state["pending"][token] = {
        "action": action,
        "payload": payload,
        "expires": now + ttl,
    }
    save_state(state)
    return token


def peek_pending(token):
    entry = load_state()["pending"].get(token)
    if not isinstance(entry, dict):
        return None
    if float(entry.get("expires", 0) or 0) <= time.time():
        return None
    return entry


def take_pending(token):
    """Consume a token: a second Confirm press must not run the action twice."""
    state = load_state()
    entry = state["pending"].pop(token, None)
    if entry is None:
        return None
    save_state(state)
    if float(entry.get("expires", 0) or 0) <= time.time():
        return None
    return entry
