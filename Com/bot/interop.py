"""Runtime bridge between the self-bot and the owner bot.

The two clients share one process, but they must not share one *story* about
what is happening: the bot cannot see the owner's chats, cannot call the user
API, and does not exist at all when `BOT_TOKEN` is unset. So everything they
need to agree on is written to ``mode/runtime.json``:

``selfbot`` / ``bot``
    Heartbeats. Each side writes its own section every scheduler tick (self-bot)
    or every 30 s (bot). A stale timestamp is the only reliable "the other side
    is down" signal on a free Repl, because a killed process cannot warn anyone.

``chats``
    A small registry of the self-bot's recent dialogs. The bot uses it for its
    chat pickers; without it the bot has no way to name or address a chat.

``outbox``
    Actions the bot wants the *user account* to perform: send a message, or run
    one of a small allowlist of self-bot commands. The self-bot claims, executes
    and reports each one.

``events``
    One-way notes from the self-bot to the bot ("queued action failed"), polled
    by the bot and delivered to the owner as DMs.

Delivery is at-most-once by design. A send is not idempotent, so an action that
was claimed by a process that then died is marked ``unknown`` on the next boot
and surfaced in the bot's queue. It is never retried automatically; only the
owner can retry it, with the duplicate risk spelled out in the UI.
"""
import asyncio
import logging
import os
import time
import uuid

import Com.core.tgsend as tgsend
from Com.core import scheduler
from Com.core.storage import load_json, save_json

log = logging.getLogger("selftg.interop")

RUNTIME_FILE = "mode/runtime.json"
SCHEMA_VERSION = 1
BOOT_ID = uuid.uuid4().hex[:12]
HEARTBEAT_STALE = 90          # seconds before the other side counts as down
CHAT_REFRESH_SECONDS = 15 * 60
MAX_CHATS = 80
MAX_OUTBOX = 80
DONE_TTL = 24 * 3600
MAX_EVENTS = 20
MAX_TEXT = 3000

# Commands the bot may ask the self-bot to run. Anything else is refused here:
# the bot's screens are the UI, not a general remote control for the account.
COMMAND_ALLOWLIST = (
    "!afk",
    "!log on",
    "!log off",
    "!cauto on",
    "!cauto off",
    "!stats",
    "!sysinfo",
    "!uptime",
    "!ban unban",
    "!setkill stop",
    "!reaction stop",
    "!poll close",
    "!poll results",
)

_self_client = None
_my_id = None
_wake = asyncio.Event()
_started_at = time.time()
_chat_published_at = 0.0


#------------------------------
#State
#------------------------------

def _default():
    return {
        "_version": SCHEMA_VERSION,
        "selfbot": {},
        "bot": {},
        "chats": [],
        "outbox": [],
        "events": [],
    }


def load_runtime():
    data = load_json(RUNTIME_FILE, None)
    if not isinstance(data, dict):
        return _default()
    for key, empty in (("selfbot", {}), ("bot", {}), ("chats", []),
                       ("outbox", []), ("events", [])):
        if not isinstance(data.get(key), type(empty)):
            data[key] = empty
    data.setdefault("_version", SCHEMA_VERSION)
    return data


def _save(data):
    try:
        save_json(RUNTIME_FILE, data)
        return True
    except Exception:  # noqa: BLE001 - runtime state is best effort
        log.exception("interop: could not write %s", RUNTIME_FILE)
        return False


def update(mutate):
    """Read-modify-write the runtime document; `mutate` gets the dict."""
    data = load_runtime()
    result = mutate(data)
    _save(data)
    return result


#------------------------------
#Heartbeats
#------------------------------

def touch_self(client, user_id, username=None):
    """Called from the scheduler tick: this is the self-bot's liveness proof."""
    def mutate(data):
        data["selfbot"] = {
            "pid": os.getpid(),
            "boot_id": BOOT_ID,
            "started_at": _started_at,
            "heartbeat": time.time(),
            "connected": bool(client and client.is_connected()),
            "user_id": user_id,
            "username": username,
            "jobs": list(scheduler.jobs()),
        }
    return update(mutate)


def touch_bot(client, username=None, connected=True):
    def mutate(data):
        data["bot"] = {
            "pid": os.getpid(),
            "boot_id": BOOT_ID,
            "started_at": _started_at,
            "heartbeat": time.time(),
            "connected": bool(connected),
            "username": username,
        }
    return update(mutate)


def started_at():
    """Process start time, for uptime lines that must not touch privates."""
    return _started_at


def section_age(name):
    """Seconds since that side's last heartbeat, or None if it never wrote one."""
    section = load_runtime().get(name) or {}
    stamp = float(section.get("heartbeat", 0) or 0)
    if not stamp:
        return None
    return max(0.0, time.time() - stamp)


def is_online(name):
    age = section_age(name)
    if age is None or age > HEARTBEAT_STALE:
        return False
    return bool((load_runtime().get(name) or {}).get("connected"))


#------------------------------
#Chat registry
#------------------------------

def chats():
    return load_runtime().get("chats", [])


def _dialog_title(entity, fallback):
    for attr in ("title", "first_name"):
        value = getattr(entity, attr, None)
        if value:
            return str(value)
    return str(fallback)


async def publish_chats(client, limit=MAX_CHATS):
    """Record the self-bot's dialogs so the bot can offer a chat picker."""
    global _chat_published_at
    rows = []
    try:
        async for dialog in client.iter_dialogs(limit=limit):
            entity = getattr(dialog, "entity", None)
            rows.append({
                "id": dialog.id,
                "title": _dialog_title(entity, dialog.id),
                "type": type(entity).__name__,
                "username": getattr(entity, "username", None),
            })
    except Exception:  # noqa: BLE001 - a picker with no chats still works
        log.warning("interop: could not list dialogs", exc_info=True)
    update(lambda data: data.__setitem__("chats", rows))
    _chat_published_at = time.time()
    log.info("interop: published %d chats for the bot", len(rows))


#------------------------------
#Outbox
#------------------------------

def _new_id():
    return uuid.uuid4().hex[:10]


def command_allowed(text):
    low = (text or "").strip().lower()
    return any(low == prefix or low.startswith(prefix + " ")
               for prefix in COMMAND_ALLOWLIST)


def enqueue(kind, chat_id, text, reply_to=None):
    """Queue an action for the self-bot. Returns (action_id, error)."""
    text = (text or "").strip()
    if kind not in ("message", "command"):
        return None, "unknown action type"
    if not text:
        return None, "nothing to send"
    if len(text) > MAX_TEXT:
        return None, f"message is longer than {MAX_TEXT} characters"
    if kind == "command" and not command_allowed(text):
        return None, "that command is not on the bot's allowlist"

    action = {
        "id": _new_id(),
        "kind": kind,
        "chat_id": chat_id,
        "text": text,
        "reply_to": reply_to,
        "state": "pending",
        "created": time.time(),
        "attempts": 0,
        "claimed_at": None,
        "claimed_by": None,
        "result": None,
        "finished": None,
    }

    def mutate(data):
        data["outbox"].append(action)
        data["outbox"] = data["outbox"][-MAX_OUTBOX:]
        return action["id"]

    action_id = update(mutate)
    _wake.set()
    return action_id, None


def outbox():
    return load_runtime().get("outbox", [])


def find_action(action_id):
    for entry in outbox():
        if entry.get("id") == action_id:
            return entry
    return None


def _set_state(action_id, state, result=None):
    def mutate(data):
        for entry in data["outbox"]:
            if entry.get("id") != action_id:
                continue
            entry["state"] = state
            if result is not None:
                entry["result"] = result
            if state in ("done", "failed", "unknown"):
                entry["finished"] = time.time()
    return update(mutate)


def _claim(action_id):
    """Atomically move one pending action to claimed; None if someone beat us."""
    claimed = {}

    def mutate(data):
        for entry in data["outbox"]:
            if entry.get("id") != action_id or entry.get("state") != "pending":
                continue
            entry["state"] = "claimed"
            entry["claimed_at"] = time.time()
            entry["claimed_by"] = BOOT_ID
            entry["attempts"] = int(entry.get("attempts", 0)) + 1
            claimed.update(entry)

    update(mutate)
    return claimed or None


def retry(action_id):
    """Owner-triggered retry. The caller warns about a possible duplicate."""
    def mutate(data):
        for entry in data["outbox"]:
            if entry.get("id") != action_id:
                continue
            if entry.get("state") not in ("failed", "unknown"):
                return False
            entry["state"] = "pending"
            entry["result"] = None
            entry["finished"] = None
            return True
        return False

    ok = update(mutate)
    if ok:
        _wake.set()
    return ok


def drop(action_id):
    def mutate(data):
        before = len(data["outbox"])
        data["outbox"] = [
            entry for entry in data["outbox"]
            if not (entry.get("id") == action_id
                    and entry.get("state") in ("failed", "unknown", "done"))
        ]
        return len(data["outbox"]) != before

    return update(mutate)


def recover_stale_claims():
    """Called once at self-bot start: never replay an interrupted send."""
    def mutate(data):
        recovered = 0
        for entry in data["outbox"]:
            if entry.get("state") != "claimed":
                continue
            if entry.get("claimed_by") == BOOT_ID:
                continue
            entry["state"] = "unknown"
            entry["result"] = (
                "interrupted by a restart; not retried automatically so a "
                "message cannot be sent twice"
            )
            entry["finished"] = time.time()
            recovered += 1
        if recovered:
            log.warning("interop: %d interrupted action(s) need review", recovered)
        return recovered

    return update(mutate)


def _prune():
    def mutate(data):
        now = time.time()
        kept = []
        for entry in data["outbox"]:
            finished = entry.get("finished")
            if entry.get("state") == "done" and finished and now - float(finished) > DONE_TTL:
                continue
            kept.append(entry)
        data["outbox"] = kept[-MAX_OUTBOX:]
    update(mutate)


async def _execute(client, action):
    peer = await tgsend.resolve(client, action.get("chat_id"))
    if action.get("kind") == "message":
        message = await client.send_message(
            peer, action.get("text", ""), reply_to=action.get("reply_to")
        )
        return f"sent as message #{getattr(message, 'id', '?')}"
    if action.get("kind") == "command":
        await client.send_message(peer, action.get("text", ""))
        return "command sent to the self-bot"
    raise ValueError(f"unknown action kind {action.get('kind')!r}")


async def consume(client, limit=3):
    """Claim and run pending actions. Safe to call from the tick and a wake."""
    ran = 0
    pending = [entry for entry in outbox() if entry.get("state") == "pending"]
    for entry in pending[:limit]:
        action = _claim(entry.get("id"))
        if not action:
            continue
        try:
            result = await _execute(client, action)
        except Exception as exc:  # noqa: BLE001 - report, never crash the tick
            detail = f"{type(exc).__name__}: {exc}"
            _set_state(action["id"], "failed", detail)
            notify(f"Queued action failed: {action.get('kind')} → {detail}")
            log.warning("interop: action %s failed: %s", action["id"], detail)
        else:
            _set_state(action["id"], "done", result)
            log.info("interop: action %s done (%s)", action["id"], result)
        ran += 1
    if ran:
        _prune()
    return ran


async def wait_result(action_id, timeout=10.0):
    """Poll for the terminal state of one action (no shared futures to leak)."""
    deadline = time.monotonic() + timeout
    while True:
        entry = find_action(action_id)
        if entry and entry.get("state") in ("done", "failed", "unknown"):
            return entry
        if time.monotonic() >= deadline:
            return entry
        await asyncio.sleep(0.25)


#------------------------------
#Events (self-bot → bot)
#------------------------------

def notify(text):
    def mutate(data):
        data["events"].append({
            "id": uuid.uuid4().hex[:8],
            "at": time.time(),
            "text": str(text)[:500],
        })
        data["events"] = data["events"][-MAX_EVENTS:]
    update(mutate)


def pending_events():
    return load_runtime().get("events", [])


def ack_event(event_id):
    def mutate(data):
        data["events"] = [e for e in data["events"] if e.get("id") != event_id]
    update(mutate)


#------------------------------
#Self-bot side
#------------------------------

async def _worker(client):
    """Run an action as soon as the bot queues it, not on the next 20 s tick."""
    while True:
        await _wake.wait()
        _wake.clear()
        try:
            await consume(client)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the scheduler tick is the fallback
            log.exception("interop: wake-up consumer failed")


async def interop_tick(client):
    """Scheduler job: heartbeat, chat refresh and the outbox fallback."""
    me = None
    try:
        me = await client.get_me()
    except Exception:  # noqa: BLE001 - offline is reported, not raised
        log.debug("interop: get_me failed", exc_info=True)
    touch_self(
        client,
        getattr(me, "id", _my_id),
        getattr(me, "username", None) if me else None,
    )
    await consume(client)
    if time.time() - _chat_published_at > CHAT_REFRESH_SECONDS:
        await publish_chats(client)


def setup(client, my_id):
    """Register the bridge on the self-bot side (called by main's module scan)."""
    global _self_client, _my_id
    _self_client = client
    _my_id = my_id
    recovered = recover_stale_claims()
    scheduler.register("interop", interop_tick)
    asyncio.create_task(_worker(client), name="selftg-interop")
    log.info(
        "interop: bridge ready (boot %s, %d interrupted action(s))",
        BOOT_ID, recovered or 0,
    )
