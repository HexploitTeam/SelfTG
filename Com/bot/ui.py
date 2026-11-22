"""Screens, flows and the callback router for the owner bot.

Every view is a :class:`Com.bot.kit.Screen`: an HTML message and a grid of
buttons. The bot edits one message as the owner walks through menus, so Back is
always the previous screen and no chat history is created by browsing.

Two rules shape the code:

* **Callbacks are always answered.** ``dispatch`` answers before doing work and
  the router answers again in ``finally`` if a screen forgot; an unanswered
  callback leaves the button spinning for ten seconds.
* **Nothing destructive happens on one press.** Deleting a warning, lifting a
  ban, stopping a timer or sending a message goes through
  ``botkit.new_pending`` and a single-use token, so a double tap cannot run the
  action twice.

The screens read the same JSON documents as the self-bot commands. Where a
change can be persisted (warns, mutes, reminders, notes, todos) the bot edits
the document directly -- one source of truth, no second implementation. Where
Telegram itself must act, or where a switch lives in a running handler
(``!log``, ``!cauto``, ``!setkill``, ``!reaction``), the bot queues an action
through :mod:`Com.bot.interop` for the user account to perform.
"""
import logging
import time

import Com.afk as afk
import Com.ban as ban
from Com.bot import interop
from Com.bot import kit
from Com.bot import registry as botregistry
import Com.cauto as cauto
import Com.enemy as enemy_mod
import Com.log as log_module
import Com.monitor as monitor
import Com.mute as mute
import Com.note as note
import Com.poll as poll_mod
import Com.remind as remind
import Com.setkill as setkill
import Com.todo as todo
import Com.warn as warn
from Com.core import brand
from Com.core import scheduler as scheduler_mod
from Com.core.durations import parse_duration
from Com.core.storage import load_json, save_json

log = logging.getLogger("selftg.botui")

REACTION_FILE = "mode/reactions.json"
ME = "me"          # Saved Messages
# Wizards start at a named step, not "text"
FLOW_START_STEPS = {"note_add": "name"}
MAX_ROWS = 8


#------------------------------
#Context
#------------------------------

class Ctx:
    """What a screen needs: the bot client and the single owner id."""

    def __init__(self, client, owner_id):
        self.client = client
        self.owner_id = owner_id


#------------------------------
#Data helpers
#------------------------------

def _self_info():
    return interop.load_runtime().get("selfbot", {})


def _self_online():
    return interop.is_online("selfbot")


def _uptime():
    started = float(_self_info().get("started_at", 0) or 0)
    return kit.age(time.time() - started) if started else "?"


def _chats():
    return interop.chats()


def _chat_title(chat_id):
    wanted = str(chat_id)
    for chat in _chats():
        if str(chat.get("id")) == wanted:
            return chat.get("title") or wanted
    return wanted


def _warn_chats():
    data = warn.load_warns()
    if not isinstance(data, dict):
        return []
    return [cid for cid, entry in data.items()
            if isinstance(entry, dict) and entry.get("warnings")]


def _mutes(chat_id):
    try:
        return mute.get_muted_users(chat_id)
    except Exception:  # noqa: BLE001 - a broken store reads as "nothing muted"
        return []


def _enemies(chat_id):
    try:
        return enemy_mod.get_enemy_data(chat_id)
    except Exception:  # noqa: BLE001 - a broken store reads as "no enemies"
        return []


def _last_poll(chat_id):
    try:
        state = poll_mod.load_state()
    except Exception:  # noqa: BLE001
        return None
    entry = (state.get("chats") or {}).get(str(chat_id))
    return entry if isinstance(entry, dict) else None


def _bans(chat_id):
    try:
        return ban.load_bans(chat_id)
    except Exception:  # noqa: BLE001
        return {}


def _banned_chats():
    data = load_json(ban.BAN_FILE, {})
    return list(data) if isinstance(data, dict) else []


def _timers(chat_id=None):
    data = setkill.load_timers()
    entries = data.get("timers", []) if isinstance(data, dict) else []
    if chat_id is None:
        return entries
    return [entry for entry in entries if str(entry.get("chat_id")) == str(chat_id)]


def _reactions():
    data = load_json(REACTION_FILE, {})
    return data if isinstance(data, dict) else {}


def _reminders():
    state = remind.load_state()
    items = state.get("items", [])
    return sorted(items, key=lambda item: float(item.get("due_at", 0) or 0))


def _todos(chat_id):
    state = todo.load_state()
    bucket = state.get("chats", {}).get(str(chat_id)) or {}
    items = bucket.get("items", [])
    return sorted(items, key=lambda item: int(item.get("id", 0)))


def _notes(scope, chat_id):
    state = note.load_state()
    if scope == "g":
        data = state.get("global", {})
    else:
        data = state.get("chats", {}).get(str(chat_id), {})
    return data if isinstance(data, dict) else {}


def _queue_counts():
    entries = interop.outbox()
    counts = {"pending": 0, "claimed": 0, "done": 0, "failed": 0, "unknown": 0}
    for entry in entries:
        state = entry.get("state")
        if state in counts:
            counts[state] += 1
    return counts


#------------------------------
#Home and status
#------------------------------

def home_screen():
    bot_info = interop.load_runtime().get("bot", {})
    online = _self_online()
    bot_online = interop.is_online("bot")
    counts = _queue_counts()
    username = f"@{bot_info['username']}" if bot_info.get("username") else "connected"
    alerts = len(interop.pending_events())

    text = (
        "🛰 <b>SelfTG control</b>\n"
        f"Self-bot: {'✅ online' if online else '⚠️ not responding'}"
        f" · up {_uptime() if online else '?'}\n"
        f"Bot: {'✅ ' + kit.h(username) if bot_online else '⚠️ stale'}\n"
        f"Queue: {counts['pending']} pending · {counts['failed'] + counts['unknown']} need review"
        + (f" · 🔔 {alerts}" if alerts else "")
    )
    rows = [
        [kit.btn("📊 Status", "status"), kit.btn("🧩 Moderation", "chats", "mod", 0)],
        [kit.btn("⚙️ Automations", "auto"), kit.btn("⏰ Reminders", "rem", 0)],
        [kit.btn("📝 Notes", "notescope", 0), kit.btn("✅ Todos", "chats", "todo", 0)],
        [kit.btn("💬 Send as me", "chats", "relay", 0), kit.btn("📡 Queue", "queue")],
        [kit.btn("⌨️ Commands", "commands"), kit.btn("🩺 Diagnostics", "diag")],
        [kit.btn("🔧 Settings", "settings")],
    ]
    return kit.Screen(text, rows)


def status_screen():
    runtime = interop.load_runtime()
    info = runtime.get("selfbot", {})
    bot_info = runtime.get("bot", {})
    self_age = interop.section_age("selfbot")
    bot_age = interop.section_age("bot")
    jobs = info.get("jobs") or []
    counts = _queue_counts()

    try:
        import psutil

        rss = psutil.Process().memory_info().rss / (1024 * 1024)
        memory = f"{rss:.0f} MiB RSS"
    except Exception:  # noqa: BLE001 - status must render without psutil too
        memory = "unavailable"

    def side(name, section, age):
        if age is None:
            return f"{name}: no heartbeat yet"
        state = "✅" if age <= interop.HEARTBEAT_STALE and section.get("connected", True) else "⚠️"
        return f"{name}: {state} heartbeat {kit.age(age)} ago"

    text = "\n".join([
        "📊 <b>Status</b>",
        side("Self-bot", info, self_age),
        side("Bot", bot_info, bot_age),
        f"Self-bot pid {info.get('pid', '?')} · boot <code>{kit.h(info.get('boot_id', '?'))}</code>",
        f"Up {_uptime()} · {len(jobs)} scheduler job(s)",
        f"Dialogs published: {len(_chats())}",
        f"Queue: {counts['pending']} pending · {counts['failed']} failed"
        f" · {counts['unknown']} unknown · {counts['done']} done",
        f"Process memory: {memory}",
    ])
    rows = [[kit.btn("🔄 Refresh", "status"), kit.btn("🏠 Menu", "home")]]
    return kit.Screen(text, rows)


#------------------------------
#Chat pickers
#------------------------------

def chat_picker(mode, page):
    chats = _chats()
    title = {
        "mod": "🧩 Moderation — choose a chat",
        "relay": "💬 Act as the self-bot — choose a chat",
        "todo": "✅ Todos — choose a chat",
    }.get(mode, "Choose a chat")

    if not chats:
        return kit.Screen(
            f"{title}\n\nNo dialogs published yet. The self-bot writes them on "
            "its first tick after connecting.",
            [[kit.btn("🏠 Menu", "home")]],
        )

    chunk, page, pages = kit.paginate(chats, page)
    rows = []
    for chat in chunk:
        label = f"{chat.get('title') or chat.get('id')}"
        if len(label) > 34:
            label = label[:33] + "…"
        target = {"mod": "mod", "relay": "relay", "todo": "todo"}[mode]
        rows.append([kit.btn(label, target, chat.get("id"))])
    pager = kit.pager_row(("chats", mode), page, pages)
    if pager:
        rows.append(pager)
    rows.append([kit.btn("🏠 Menu", "home")])
    return kit.Screen(f"{title}\nPage {page + 1}/{pages}", rows)


#------------------------------
#Moderation
#------------------------------

def mod_screen(chat_id):
    title = kit.h(_chat_title(chat_id), 48)
    warns = warn.load_warns().get(str(chat_id)) or {}
    warn_users = warns.get("warnings") or {}
    mutes = _mutes(chat_id)
    bans = _bans(chat_id)
    timers = _timers(chat_id)
    text = (
        f"🧩 <b>{title}</b>\n"
        f"<code>{kit.h(chat_id)}</code>\n\n"
        f"⚠️ Warns: {len(warn_users)} user(s), limit {warns.get('limit', 3)}\n"
        f"🔇 Mutes: {len(mutes)}\n"
        f"🛑 Tracked bans: {len(bans)}\n"
        f"⏱ Timers: {len(timers)}"
    )
    rows = [
        [kit.btn(f"⚠️ Warns ({len(warn_users)})", "warns", chat_id, 0),
         kit.btn(f"🔇 Mutes ({len(mutes)})", "mutes", chat_id)],
        [kit.btn(f"🛑 Bans ({len(bans)})", "bans", chat_id),
         kit.btn(f"⏱ Timers ({len(timers)})", "timers", chat_id)],
        [kit.btn(f"😈 Enemies ({len(_enemies(chat_id))})", "enemies", chat_id),
         kit.btn("🗳 Poll", "poll", chat_id)],
        [kit.btn("➖ Warn limit", "do", "warnlimit", chat_id, -1),
         kit.btn(f"limit {warns.get('limit', 3)}", "mod", chat_id),
         kit.btn("➕ Warn limit", "do", "warnlimit", chat_id, 1)],
        [kit.btn("💬 Act as self-bot", "relay", chat_id)],
        [kit.copy_btn("📋 Copy chat id", str(chat_id))],
        [kit.btn("‹ Chats", "chats", "mod", 0), kit.btn("🏠 Menu", "home")],
    ]
    return kit.Screen(text, rows)


def warns_screen(chat_id, page):
    warnings = (warn.load_warns().get(str(chat_id)) or {}).get("warnings") or {}
    title = kit.h(_chat_title(chat_id), 48)
    if not warnings:
        return kit.Screen(
            f"⚠️ <b>Warns — {title}</b>\n\nNo warnings in this chat.",
            [[kit.btn("‹ Back", "mod", chat_id), kit.btn("🏠 Menu", "home")]],
        )
    users = sorted(warnings.items(), key=lambda pair: -len(pair[1]))
    chunk, page, pages = kit.paginate(users, page)
    rows = []
    for uid, reasons in chunk:
        label = f"{uid} · {len(reasons)} warning(s)"
        rows.append([kit.btn(label, "warnu", chat_id, uid)])
    pager = kit.pager_row(("warns", chat_id), page, pages)
    if pager:
        rows.append(pager)
    rows.append([kit.btn("‹ Back", "mod", chat_id), kit.btn("🏠 Menu", "home")])
    return kit.Screen(
        f"⚠️ <b>Warns — {title}</b>\n{len(users)} user(s), page {page + 1}/{pages}",
        rows,
    )


def warn_user_screen(chat_id, uid):
    entry = warn.load_warns().get(str(chat_id)) or {}
    reasons = (entry.get("warnings") or {}).get(str(uid), [])
    if not reasons:
        return kit.Screen(
            f"No warnings for <code>{kit.h(uid)}</code> any more.",
            [[kit.btn("‹ Back", "warns", chat_id, 0), kit.btn("🏠 Menu", "home")]],
        )
    lines = [f"⚠️ <b>User <code>{kit.h(uid)}</code></b>",
             f"Chat: {kit.h(_chat_title(chat_id), 40)}",
             f"Limit: {entry.get('limit', 3)}", ""]
    for index, reason in enumerate(reasons, 1):
        lines.append(f"{index}. {kit.h(reason, 120)}")
    token_last = kit.new_pending("unwarn", {
        "chat": str(chat_id), "uid": str(uid), "index": len(reasons) - 1,
        "back": ["warnu", str(chat_id), str(uid)],
    })
    token_clear = kit.new_pending("warnclear", {
        "chat": str(chat_id), "uid": str(uid),
        "back": ["warns", str(chat_id), "0"],
    })
    rows = [
        [kit.btn("➖ Remove last", "confirm", token_last)],
        [kit.btn("🗑 Clear all", "confirm", token_clear)],
        [kit.btn("‹ Back", "warns", chat_id, 0), kit.btn("🏠 Menu", "home")],
    ]
    return kit.Screen("\n".join(lines), rows)


def mutes_screen(chat_id):
    entries = _mutes(chat_id)
    title = kit.h(_chat_title(chat_id), 48)
    if not entries:
        return kit.Screen(
            f"🔇 <b>Mutes — {title}</b>\n\nNobody is muted here.",
            [[kit.btn("‹ Back", "mod", chat_id), kit.btn("🏠 Menu", "home")]],
        )
    rows = []
    for entry in entries[:MAX_ROWS]:
        uid = entry.get("user_id")
        mode = entry.get("mode", "admin")
        token = kit.new_pending("unmute", {
            "chat": str(chat_id), "uid": str(uid),
            "back": ["mutes", str(chat_id)],
        })
        rows.append([kit.btn(f"🔓 {uid} ({mode})", "confirm", token)])
    rows.append([kit.btn("‹ Back", "mod", chat_id), kit.btn("🏠 Menu", "home")])
    return kit.Screen(
        f"🔇 <b>Mutes — {title}</b>\n{len(entries)} user(s). Tap one to unmute.",
        rows,
    )


def bans_screen(chat_id):
    entries = _bans(chat_id)
    title = kit.h(_chat_title(chat_id), 48)
    if not entries:
        return kit.Screen(
            f"🛑 <b>Tracked bans — {title}</b>\n\nNothing tracked here.",
            [[kit.btn("‹ Back", "mod", chat_id), kit.btn("🏠 Menu", "home")]],
        )
    rows = []
    for uid, entry in list(entries.items())[:MAX_ROWS]:
        kind = entry.get("kind", "ban")
        token = kit.new_pending("unban", {
            "chat": str(chat_id), "uid": str(uid),
            "back": ["bans", str(chat_id)],
        })
        rows.append([kit.btn(f"🔓 {uid} ({kind})", "confirm", token)])
    rows.append([kit.btn("‹ Back", "mod", chat_id), kit.btn("🏠 Menu", "home")])
    return kit.Screen(
        f"🛑 <b>Tracked bans — {title}</b>\n"
        f"{len(entries)} entry(ies). Unbanning runs <code>!ban unban</code> as the self-bot.",
        rows,
    )


def timers_screen(chat_id):
    entries = _timers(chat_id)
    title = kit.h(_chat_title(chat_id), 48)
    if not entries:
        return kit.Screen(
            f"⏱ <b>Timers — {title}</b>\n\nNo timer is running here.",
            [[kit.btn("‹ Back", "mod", chat_id), kit.btn("🏠 Menu", "home")]],
        )
    rows = []
    for entry in entries[:MAX_ROWS]:
        label = f"⏹ #{entry.get('id')} every {entry.get('interval')}s"
        token = kit.new_pending("stoptimer", {
            "chat": str(chat_id), "timer": str(entry.get("id")),
            "back": ["timers", str(chat_id)],
        })
        rows.append([kit.btn(label, "confirm", token)])
    rows.append([kit.btn("‹ Back", "mod", chat_id), kit.btn("🏠 Menu", "home")])
    return kit.Screen(
        f"⏱ <b>Timers — {title}</b>\nTap one to stop it.", rows
    )


#------------------------------
#Automations
#------------------------------

def auto_screen():
    state = afk.load_state()
    global_afk = state.get("global")
    per_chat = state.get("chats") or {}
    log_on = str(getattr(log_module, "LOG_MODE", "OFF")).upper() == "ON"
    monitor_data = monitor.load_data()
    monitor_on = bool((monitor_data.get("__settings") or {}).get("global_enabled"))
    reactions = _reactions()

    lines = [
        "⚙️ <b>Automations</b>",
        f"💤 AFK: {'on (global)' if global_afk else 'off'}"
        + (f" · {len(per_chat)} chat(s)" if per_chat else ""),
        f"📝 Logging: {'on' if log_on else 'off'}",
        f"🧠 Challenge solver: {'on' if cauto.AUTO_SOLVE else 'off'}",
        f"👀 Monitor: {'on (global)' if monitor_on else 'off'}",
        f"❤️ Reaction tasks: {len(reactions)}",
    ]
    rows = []
    if global_afk or per_chat:
        token = kit.new_pending("afkoff", {"back": ["auto"]})
        rows.append([kit.btn("💤 Turn AFK off", "confirm", token)])
    log_token = kit.new_pending("logtoggle", {"back": ["auto"]})
    solver_token = kit.new_pending("cautotoggle", {"back": ["auto"]})
    rows.append([
        kit.btn(f"📝 Logging {'off' if log_on else 'on'}", "confirm", log_token),
        kit.btn(f"🧠 Solver {'off' if cauto.AUTO_SOLVE else 'on'}", "confirm", solver_token),
    ])
    rows.append([kit.btn(f"👀 Monitor {'off' if monitor_on else 'on'}", "do", "togglemonitor")])
    if reactions:
        for tid, info in list(reactions.items())[:4]:
            token = kit.new_pending("stopreaction", {
                "tid": str(tid), "back": ["auto"],
            })
            rows.append([kit.btn(
                f"⏹ reaction #{tid} → {info.get('emoji')}", "confirm", token
            )])
    rows.append([kit.btn("🏠 Menu", "home")])
    return kit.Screen("\n".join(lines), rows)


#------------------------------
#Reminders
#------------------------------

def reminders_screen(page):
    items = _reminders()
    if not items:
        return kit.Screen(
            "⏰ <b>Reminders</b>\n\nNothing pending.",
            [[kit.btn("➕ Add reminder", "do", "flow", "remind_add"),
              kit.btn("🏠 Menu", "home")]],
        )
    tz, _ = remind.owner_timezone()
    chunk, page, pages = kit.paginate(items, page)
    rows = []
    for item in chunk:
        due = float(item.get("due_at", 0) or 0)
        left = kit.age(max(0, due - time.time()))
        label = f"⏹ #{item.get('id')} · {left} · {str(item.get('text', ''))[:24]}"
        token = kit.new_pending("remcancel", {
            "rid": str(item.get("id")), "back": ["rem", str(page)],
        })
        rows.append([kit.btn(label, "confirm", token)])
    pager = kit.pager_row(("rem",), page, pages)
    if pager:
        rows.append(pager)
    rows.append([
        kit.btn("➕ Add reminder", "do", "flow", "remind_add"),
        kit.btn("🏠 Menu", "home"),
    ])
    lines = ["⏰ <b>Reminders</b>", f"{len(items)} pending · page {page + 1}/{pages}", ""]
    for item in chunk:
        due = float(item.get("due_at", 0) or 0)
        lines.append(
            f"<b>#{item.get('id')}</b> {kit.h(remind._fmt_due(due, tz))} · "
            f"{kit.h(item.get('text', ''), 80)}"
        )
    return kit.Screen("\n".join(lines), rows)


#------------------------------
#Notes and todos
#------------------------------

def note_scope_screen(page):
    chats = _chats()
    rows = [[kit.btn("🌍 Global notes", "notes", "g", "0", 0)]]
    chunk, page, pages = kit.paginate(chats, page)
    for chat in chunk:
        rows.append([kit.btn(
            f"📝 {str(chat.get('title') or chat.get('id'))[:30]}",
            "notes", "c", chat.get("id"), 0,
        )])
    pager = kit.pager_row(("notescope",), page, pages)
    if pager:
        rows.append(pager)
    rows.append([kit.btn("🏠 Menu", "home")])
    return kit.Screen(
        "📝 <b>Notes</b>\nGlobal notes are visible from every chat; per-chat "
        "notes stay in that chat.\nChoose a scope:", rows,
    )


def notes_screen(scope, chat_id, page):
    data = _notes(scope, chat_id)
    where = "Global" if scope == "g" else kit.h(_chat_title(chat_id), 40)
    if not data:
        return kit.Screen(
            f"📝 <b>Notes — {where}</b>\n\nNo notes saved here.",
            [[kit.btn("➕ New note", "do", "flow", "note_add", scope, chat_id)],
             [kit.btn("‹ Back", "notescope", 0), kit.btn("🏠 Menu", "home")]],
        )
    names = sorted(data)
    chunk, page, pages = kit.paginate(names, page)
    rows = []
    for name in chunk:
        token = kit.new_pending("notedel", {
            "scope": scope, "chat": str(chat_id), "name": name,
            "back": ["notes", scope, str(chat_id), str(page)],
        })
        rows.append([kit.btn(f"🗑 {name}", "confirm", token)])
    pager = kit.pager_row(("notes", scope, chat_id), page, pages)
    if pager:
        rows.append(pager)
    rows.append([kit.btn("➕ New note", "do", "flow", "note_add", scope, chat_id)])
    rows.append([kit.btn("‹ Back", "notescope", 0), kit.btn("🏠 Menu", "home")])
    lines = [f"📝 <b>Notes — {where}</b>", f"{len(names)} note(s), page {page + 1}/{pages}", ""]
    for name in chunk:
        lines.append(f"<b>{kit.h(name)}</b> — {kit.h(data[name], 90)}")
    return kit.Screen("\n".join(lines), rows)


def todo_screen(chat_id):
    items = _todos(chat_id)
    where = kit.h(_chat_title(chat_id), 40)
    if not items:
        return kit.Screen(
            f"✅ <b>Todos — {where}</b>\n\nNothing here.",
            [[kit.btn("➕ New todo", "do", "flow", "todo_add", chat_id)],
             [kit.btn("‹ Chats", "chats", "todo", 0), kit.btn("🏠 Menu", "home")]],
        )
    rows = []
    for item in items[:MAX_ROWS]:
        mark = "✅" if item.get("done") else "⬜"
        rows.append([kit.btn(
            f"{mark} {item.get('id')}. {str(item.get('text', ''))[:26]}",
            "do", "todotoggle", chat_id, item.get("id"),
        )])
    for item in items[:3]:
        token = kit.new_pending("tododel", {
            "chat": str(chat_id), "tid": str(item.get("id")),
            "back": ["todo", str(chat_id)],
        })
        rows.append([kit.btn(f"🗑 delete {item.get('id')}", "confirm", token)])
    rows.append([kit.btn("➕ New todo", "do", "flow", "todo_add", chat_id)])
    rows.append([kit.btn("‹ Chats", "chats", "todo", 0), kit.btn("🏠 Menu", "home")])
    pending = sum(1 for item in items if not item.get("done"))
    return kit.Screen(
        f"✅ <b>Todos — {where}</b>\n{pending} pending, {len(items) - pending} done.\n"
        "Tap an item to toggle it.", rows,
    )


#------------------------------
#Acting as the self-bot
#------------------------------

def relay_screen(chat_id):
    title = kit.h(_chat_title(chat_id), 48)
    text = (
        f"💬 <b>Act as the self-bot — {title}</b>\n"
        f"<code>{kit.h(chat_id)}</code>\n\n"
        "These actions are queued for the user account, which is the only side "
        "that can see this chat."
    )
    rows = [
        [kit.btn("✏️ Send a message", "do", "flow", "relay_text", chat_id)],
        [kit.btn("⌨️ Run a self-bot command", "relaycmds", chat_id)],
        [kit.btn("‹ Chats", "chats", "relay", 0), kit.btn("🏠 Menu", "home")],
    ]
    return kit.Screen(text, rows)


RELAY_COMMANDS = [
    ("!stats", "chat statistics here"),
    ("!sysinfo", "system snapshot here"),
    ("!uptime", "runtime and resources here"),
    ("!afk here", "mark this chat AFK"),
    ("!afk off", "clear AFK"),
]


def relay_commands_screen(chat_id):
    rows = []
    for command, description in RELAY_COMMANDS:
        token = kit.new_pending("relay_cmd", {
            "chat": str(chat_id), "command": command,
            "back": ["relay", str(chat_id)],
        })
        rows.append([kit.btn(f"{command} — {description}", "confirm", token)])
    rows.append([kit.btn("‹ Back", "relay", chat_id), kit.btn("🏠 Menu", "home")])
    return kit.Screen(
        f"⌨️ <b>Commands — {kit.h(_chat_title(chat_id), 40)}</b>\n"
        "The command is typed into the chat by the user account, so its reply "
        "appears there.", rows,
    )


#------------------------------
#Queue and settings
#------------------------------

def queue_screen():
    entries = list(reversed(interop.outbox()))[:MAX_ROWS]
    counts = _queue_counts()
    if not entries:
        return kit.Screen(
            "📡 <b>Queue</b>\n\nNothing has been queued yet.",
            [[kit.btn("🏠 Menu", "home")]],
        )
    lines = [
        "📡 <b>Queue</b>",
        f"{counts['pending']} pending · {counts['failed']} failed"
        f" · {counts['unknown']} unknown",
        "",
    ]
    rows = []
    for entry in entries:
        kind = entry.get("kind")
        state = entry.get("state")
        icon = {"pending": "⏳", "claimed": "▶️", "done": "✅",
                "failed": "❌", "unknown": "❓"}.get(state, "•")
        lines.append(
            f"{icon} <code>{kit.h(entry.get('id'))}</code> {kind} · "
            f"{kit.h(entry.get('text', ''), 40)}"
        )
        if state in ("failed", "unknown"):
            rows.append([
                kit.btn(f"↻ {entry.get('id')}", "do", "qretry", entry.get("id"),
                        style="primary"),
                kit.btn(f"🗑 {entry.get('id')}", "do", "qdrop", entry.get("id"),
                        style="danger"),
            ])
    rows.append([kit.btn("🔄 Refresh", "queue"), kit.btn("🏠 Menu", "home")])
    return kit.Screen("\n".join(lines), rows)


def settings_screen():
    settings = kit.settings()
    size = kit.page_size()
    alerts = bool(settings.get("alerts", True))
    lines = [
        "🔧 <b>Settings</b>",
        f"Bot alerts in DM: {'on' if alerts else 'off'}",
        f"Rows per page: {size}",
        "",
        "Destructive actions always ask for confirmation.",
    ]
    rows = [
        [kit.btn(f"🔔 Alerts {'off' if alerts else 'on'}", "do", "togglealerts")],
        [kit.btn("➖ Rows", "do", "pagesize", -1), kit.btn("➕ Rows", "do", "pagesize", 1)],
        [kit.btn("🏠 Menu", "home")],
    ]
    return kit.Screen("\n".join(lines), rows)


#------------------------------
#Confirmations
#------------------------------

DESCRIPTIONS = {
    "unwarn": "Remove the most recent warning from this user.",
    "warnclear": "Clear every warning for this user.",
    "unmute": "Unmute this user in the chat.",
    "unban": "Lift this ban by running !ban unban as the self-bot.",
    "stoptimer": "Stop this repeating timer.",
    "afkoff": "Clear the global AFK and every per-chat AFK entry.",
    "logtoggle": "Toggle message logging on the self-bot.",
    "cautotoggle": "Toggle the maths-challenge solver.",
    "stopreaction": "Remove this reaction task.",
    "remcancel": "Cancel this reminder.",
    "tododel": "Delete this todo item.",
    "notedel": "Delete this note.",
    "relay_cmd": "Type this command into the chat as your account.",
    "relay_send": "Send this message as your account.",
    "remind_add": "Create this reminder.",
    "enemydel": "Remove this user from the chat's enemy list.",
    "poll_close": "Close the latest poll in this chat (as you).",
    "poll_results": "Fetch the latest poll's results (as you).",
}


def confirm_screen(token):
    entry = kit.peek_pending(token)
    if not entry:
        return home_screen(), "That confirmation expired; nothing was changed."
    action = entry.get("action")
    description = DESCRIPTIONS.get(action, action)
    return kit.Screen(
        f"⚠️ <b>Confirm</b>\n{kit.h(description)}\n\n"
        "This token works once and expires in five minutes.",
        [[kit.btn("✅ Confirm", "do", "confirm", token, style="success"),
          kit.btn("✖️ Cancel", "do", "cancel", token, style="danger")]],
    ), None


#------------------------------
#Flow entry
#------------------------------

def flow_prompt(name, data):
    if name == "relay_text":
        chat_id = data.get("chat")
        return kit.Screen(
            f"✏️ <b>Message for {kit.h(_chat_title(chat_id), 40)}</b>\n"
            "Send the text as your next message. It will not be sent until you "
            "confirm on the next screen.\n\n"
            "Send /cancel to stop.",
            [[kit.btn("✖️ Cancel", "do", "flowcancel")]],
        )
    if name == "remind_add":
        return kit.Screen(
            "⏰ <b>New reminder</b>\n"
            "Send it as <code>duration text</code>, for example "
            "<code>30m tea</code>, <code>2h call back</code> or "
            "<code>1d renew</code>.\n\nMinimum 5 seconds.\n\n"
            "Send /cancel to stop.",
            [[kit.btn("✖️ Cancel", "do", "flowcancel")]],
        )
    if name == "note_add":
        where = ("global" if data.get("scope") == "g"
                 else _chat_title(data.get("chat")))
        return kit.Screen(
            f"📝 <b>New note — {kit.h(where, 40)}</b>\n"
            "Send the note name next: 1-32 characters of a-z, 0-9, '_', '-' or "
            "'.'. An existing name is replaced.\n\n"
            "Send /cancel to stop.",
            [[kit.btn("✖️ Cancel", "do", "flowcancel")]],
        )
    if name == "todo_add":
        return kit.Screen(
            f"✅ <b>New todo — {kit.h(_chat_title(data.get('chat')), 40)}</b>\n"
            "Send the todo text as your next message.\n\n"
            "Send /cancel to stop.",
            [[kit.btn("✖️ Cancel", "do", "flowcancel")]],
        )
    if name == "enemy_add":
        return kit.Screen(
            f"😈 <b>New enemy — {kit.h(_chat_title(data.get('chat')), 40)}</b>\n"
            "Send the user id, optionally followed by a category, for example "
            "<code>123456789 spam</code>.\n\n"
            "Send /cancel to stop.",
            [[kit.btn("✖️ Cancel", "do", "flowcancel")]],
        )
    return kit.Screen("That flow is not available.", [[kit.btn("🏠 Menu", "home")]])


#------------------------------
#Executing confirmed actions
#------------------------------

def _screen_for(route):
    name = route[0]
    args = route[1:]
    if name == "home":
        return home_screen()
    if name == "status":
        return status_screen()
    if name == "auto":
        return auto_screen()
    if name == "queue":
        return queue_screen()
    if name == "settings":
        return settings_screen()
    if name == "mod":
        return mod_screen(args[0])
    if name == "warns":
        return warns_screen(args[0], args[1] if len(args) > 1 else 0)
    if name == "warnu":
        return warn_user_screen(args[0], args[1])
    if name == "mutes":
        return mutes_screen(args[0])
    if name == "bans":
        return bans_screen(args[0])
    if name == "timers":
        return timers_screen(args[0])
    if name == "rem":
        return reminders_screen(args[0] if args else 0)
    if name == "notes":
        return notes_screen(args[0], args[1], args[2] if len(args) > 2 else 0)
    if name == "todo":
        return todo_screen(args[0])
    if name == "relay":
        return relay_screen(args[0])
    if name == "relaycmds":
        return relay_commands_screen(args[0])
    if name == "chats":
        return chat_picker(args[0], args[1] if len(args) > 1 else 0)
    if name == "commands":
        return commands_screen()
    if name == "diag":
        return diag_screen()
    if name == "enemies":
        return enemies_screen(args[0])
    if name == "poll":
        return poll_screen(args[0])
    return home_screen()


def _remove_warning(chat_id, uid, index):
    data = warn.load_warns()
    entry = data.get(str(chat_id)) or {}
    warnings = entry.get("warnings") or {}
    reasons = warnings.get(str(uid)) or []
    try:
        reasons.pop(int(index))
    except (IndexError, TypeError, ValueError):
        return "That warning is already gone."
    if reasons:
        warnings[str(uid)] = reasons
    else:
        warnings.pop(str(uid), None)
    entry["warnings"] = warnings
    data[str(chat_id)] = entry
    save_json(warn.WARN_FILE, data)
    return "Warning removed."


def _clear_warnings(chat_id, uid):
    data = warn.load_warns()
    entry = data.get(str(chat_id)) or {}
    warnings = entry.get("warnings") or {}
    if warnings.pop(str(uid), None) is None:
        return "No warnings left for that user."
    data[str(chat_id)] = entry
    save_json(warn.WARN_FILE, data)
    return "Warnings cleared."


def _cancel_reminder(rid):
    state = remind.load_state()
    kept = [item for item in state.get("items", [])
            if str(item.get("id")) != str(rid)]
    if len(kept) == len(state.get("items", [])):
        return "That reminder is already gone."
    state["items"] = kept
    save_json(remind.REMINDER_FILE, state)
    return "Reminder cancelled."


def _delete_todo(chat_id, tid):
    state = todo.load_state()
    bucket = state.get("chats", {}).get(str(chat_id))
    if not isinstance(bucket, dict):
        return "That todo is already gone."
    before = len(bucket.get("items", []))
    bucket["items"] = [item for item in bucket.get("items", [])
                       if str(item.get("id")) != str(tid)]
    if len(bucket["items"]) == before:
        return "That todo is already gone."
    save_json(todo.TODO_FILE, state)
    return "Todo deleted."


def _delete_note(scope, chat_id, name):
    state = note.load_state()
    if scope == "g":
        data = state.get("global", {})
    else:
        data = state.get("chats", {}).get(str(chat_id), {})
    if not isinstance(data, dict) or data.pop(name, None) is None:
        return "That note is already gone."
    save_json(note.NOTE_FILE, state)
    return "Note deleted."


def _toggle_todo(chat_id, tid):
    state = todo.load_state()
    bucket = state.get("chats", {}).get(str(chat_id))
    if not isinstance(bucket, dict):
        return "That todo is already gone."
    for item in bucket.get("items", []):
        if str(item.get("id")) == str(tid):
            item["done"] = not item.get("done")
            item["done_at"] = time.time() if item["done"] else None
            save_json(todo.TODO_FILE, state)
            return "Marked done." if item["done"] else "Marked pending."
    return "That todo is already gone."


def _add_reminder(seconds, text):
    state = remind.load_state()
    if len(state.get("items", [])) >= remind.MAX_REMINDERS:
        return None, f"Already {remind.MAX_REMINDERS} reminders pending."
    item_id = int(state.get("next_id", 1))
    state["next_id"] = item_id + 1
    state.setdefault("items", []).append({
        "id": item_id,
        "text": text[:remind.MAX_TEXT],
        "due_at": time.time() + seconds,
        "created_at": time.time(),
        "chat_id": None,
    })
    save_json(remind.REMINDER_FILE, state)
    return item_id, None


def _set_warn_limit(chat_id, delta):
    data = warn.load_warns()
    entry = data.get(str(chat_id)) or {}
    limit = int(entry.get("limit", 3) or 3)
    limit = max(1, min(20, limit + int(delta)))
    entry["limit"] = limit
    entry.setdefault("warnings", {})
    data[str(chat_id)] = entry
    save_json(warn.WARN_FILE, data)
    return limit


def _save_note(scope, chat_id, name, body):
    state = note.load_state()
    bucket = (state["global"] if scope == "g"
              else state["chats"].setdefault(str(chat_id), {}))
    replaced = name in bucket
    bucket[name] = body
    note.save_state(state)
    return replaced


def _add_todo(chat_id, text):
    state = todo.load_state()
    bucket = todo._chat(state, chat_id)  # the module's own bucket shape
    if len(bucket["items"]) >= todo.MAX_ITEMS:
        return None, f"This chat already has {todo.MAX_ITEMS} todos."
    item_id = int(bucket.get("next_id", 1))
    bucket["next_id"] = item_id + 1
    bucket["items"].append({
        "id": item_id, "text": text[:500], "done": False,
        "created": time.time(), "done_at": None,
    })
    todo.save_state(state)
    return item_id, None


def _add_enemy(chat_id, uid, category):
    entries = _enemies(chat_id)
    if any(int(entry.get("user_id", 0)) == uid for entry in entries):
        return False
    entries.append({"user_id": uid, "category": category or "default",
                    "custom_text": ""})
    enemy_mod.save_enemy_data(chat_id, entries)
    return True


def _remove_enemy(chat_id, uid):
    entries = _enemies(chat_id)
    kept = [entry for entry in entries
            if int(entry.get("user_id", 0)) != int(uid)]
    if len(kept) == len(entries):
        return "That enemy is already gone."
    enemy_mod.save_enemy_data(chat_id, kept)
    return "Enemy removed."


async def _relay_and_report(ctx, kind, chat_id, text):
    action_id, error = interop.enqueue(kind, chat_id, text)
    if error:
        return f"❌ {error}"
    if not _self_online():
        return "⏳ Queued. The self-bot is not responding; it will run the action when it returns."
    # Answer inside Telegram's 4s callback window
    entry = await interop.wait_result(action_id, timeout=4)
    state = (entry or {}).get("state")
    if state == "done":
        return f"✅ {(entry or {}).get('result') or 'done'}"
    if state == "failed":
        return f"❌ {(entry or {}).get('result') or 'failed'}"
    if state in ("pending", "claimed"):
        return "⏳ Queued; the self-bot has not finished it yet. See the Queue screen."
    return "❓ The action was interrupted. Check the Queue screen."


async def _run_pending(ctx, action, payload):
    """Run one confirmed action. Returns (toast, screen)."""
    if action == "unwarn":
        toast = _remove_warning(payload["chat"], payload["uid"], payload.get("index", 0))
        return toast, _screen_for(payload.get("back", ["home"]))
    if action == "warnclear":
        toast = _clear_warnings(payload["chat"], payload["uid"])
        return toast, _screen_for(payload.get("back", ["home"]))
    if action == "unmute":
        chat_id = payload["chat"]
        uid = int(payload["uid"])
        entries = [entry for entry in _mutes(chat_id)
                   if int(entry.get("user_id", 0)) != uid]
        mute.set_muted_users(chat_id, entries)
        return "User unmuted.", _screen_for(payload.get("back", ["home"]))
    if action == "unban":
        toast = await _relay_and_report(ctx, "command", payload["chat"],
                                        f"!ban unban {payload['uid']}")
        return toast, _screen_for(payload.get("back", ["home"]))
    if action == "stoptimer":
        toast = await _relay_and_report(ctx, "command", payload["chat"],
                                        f"!setkill stop {payload['timer']}")
        return toast, _screen_for(payload.get("back", ["home"]))
    if action == "stopreaction":
        toast = await _relay_and_report(ctx, "command", ME,
                                        f"!reaction stop {payload['tid']}")
        return toast, _screen_for(payload.get("back", ["home"]))
    if action == "afkoff":
        afk.clear_scope(None, everything=True)
        return "AFK cleared.", _screen_for(payload.get("back", ["home"]))
    if action == "logtoggle":
        current = str(getattr(log_module, "LOG_MODE", "OFF")).upper() == "ON"
        toast = await _relay_and_report(ctx, "command", ME,
                                        "!log OFF" if current else "!log ON")
        return toast, _screen_for(payload.get("back", ["home"]))
    if action == "cautotoggle":
        toast = await _relay_and_report(ctx, "command", ME,
                                        "!cauto off" if cauto.AUTO_SOLVE else "!cauto on")
        return toast, _screen_for(payload.get("back", ["home"]))
    if action == "remcancel":
        return _cancel_reminder(payload["rid"]), _screen_for(payload.get("back", ["home"]))
    if action == "tododel":
        return (_delete_todo(payload["chat"], payload["tid"]),
                _screen_for(payload.get("back", ["home"])))
    if action == "notedel":
        return (_delete_note(payload["scope"], payload["chat"], payload["name"]),
                _screen_for(payload.get("back", ["home"])))
    if action == "relay_send":
        toast = await _relay_and_report(ctx, "message", payload["chat"], payload["text"])
        return toast, queue_screen()
    if action == "relay_cmd":
        toast = await _relay_and_report(ctx, "command", payload["chat"], payload["command"])
        return toast, _screen_for(payload.get("back", ["home"]))
    if action == "remind_add":
        item_id, error = _add_reminder(payload["seconds"], payload["text"])
        if error:
            return f"❌ {error}", reminders_screen(0)
        return f"Reminder #{item_id} created.", reminders_screen(0)
    if action == "enemydel":
        return (_remove_enemy(payload["chat"], payload["uid"]),
                _screen_for(payload.get("back", ["home"])))
    if action == "poll_close":
        toast = await _relay_and_report(ctx, "command", payload["chat"], "!poll close")
        return toast, _screen_for(payload.get("back", ["home"]))
    if action == "poll_results":
        toast = await _relay_and_report(ctx, "command", payload["chat"], "!poll results")
        return toast, _screen_for(payload.get("back", ["home"]))
    return "Unknown action.", home_screen()


#------------------------------
#Command centre and diagnostics
#------------------------------

def commands_screen():
    """The registry is the only list of bot commands; this screen renders it."""
    rows = [
        [kit.btn("🔄 Publish menu to Telegram", "do", "registercmds")],
        [kit.btn("🩺 Diagnostics", "diag"), kit.btn("🏠 Menu", "home")],
    ]
    return kit.Screen(botregistry.render_html(), rows)


def diag_screen():
    runtime = interop.load_runtime()
    self_info = runtime.get("selfbot", {})
    bot_info = runtime.get("bot", {})
    jobs = self_info.get("jobs") or []
    counts = _queue_counts()
    state = kit.load_state()
    flows = len(state.get("flows") or {})
    pending = len(state.get("pending") or {})
    try:
        import psutil

        proc = psutil.Process()
        memory = f"{proc.memory_info().rss / (1024 * 1024):.0f} MiB"
        threads = str(proc.num_threads())
    except Exception:  # noqa: BLE001 - diagnostics render without psutil too
        memory, threads = "unavailable", "?"

    text = "\n".join([
        "🩺 <b>Diagnostics</b>",
        f"Self-bot: pid {self_info.get('pid', '?')} · boot "
        f"<code>{kit.h(self_info.get('boot_id', '?'))}</code> · heartbeat "
        f"{kit.age(interop.section_age('selfbot') or 0)} ago",
        f"Bot: pid {bot_info.get('pid', '?')} · heartbeat "
        f"{kit.age(interop.section_age('bot') or 0)} ago",
        f"Scheduler: {len(jobs)} job(s), tick every {scheduler_mod.TICK_SECONDS}s",
        "Jobs: " + (", ".join(f"<code>{kit.h(job)}</code>" for job in jobs) or "none"),
        f"Registry: {len(botregistry.COMMANDS)} bot command(s)",
        f"Chats published: {len(_chats())} · flows {flows} · pending tokens {pending}",
        f"Queue: {counts['pending']} pending · {counts['failed']} failed"
        f" · {counts['unknown']} unknown · {counts['done']} done",
        f"Memory {memory} · threads {threads}",
    ])
    rows = [
        [kit.btn("🔄 Refresh", "diag"), kit.btn("🔁 Re-publish menu", "do", "registercmds")],
        [kit.btn("🏠 Menu", "home")],
    ]
    return kit.Screen(text, rows)


#------------------------------
#Enemies and polls
#------------------------------

def enemies_screen(chat_id):
    entries = _enemies(chat_id)
    title = kit.h(_chat_title(chat_id), 48)
    if not entries:
        return kit.Screen(
            f"😈 <b>Enemies — {title}</b>\n\nNobody on the list.",
            [[kit.btn("➕ Add enemy", "do", "flow", "enemy_add", chat_id)],
             [kit.btn("‹ Back", "mod", chat_id), kit.btn("🏠 Menu", "home")]],
        )
    rows = []
    for entry in entries[:MAX_ROWS]:
        uid = entry.get("user_id")
        category = entry.get("category", "default")
        token = kit.new_pending("enemydel", {
            "chat": str(chat_id), "uid": str(uid),
            "back": ["enemies", str(chat_id)],
        })
        rows.append([kit.btn(f"🗑 {uid} ({category})", "confirm", token)])
    rows.append([kit.btn("➕ Add enemy", "do", "flow", "enemy_add", chat_id)])
    rows.append([kit.btn("‹ Back", "mod", chat_id), kit.btn("🏠 Menu", "home")])
    return kit.Screen(
        f"😈 <b>Enemies — {title}</b>\n{len(entries)} user(s). Tap one to remove it.",
        rows,
    )


def poll_screen(chat_id):
    entry = _last_poll(chat_id)
    title = kit.h(_chat_title(chat_id), 48)
    if not entry:
        return kit.Screen(
            f"🗳 <b>Poll — {title}</b>\n\nNo poll recorded here yet. Start one "
            "with <code>!poll</code> from the chat.",
            [[kit.btn("💬 Act as self-bot", "relay", chat_id)],
             [kit.btn("‹ Back", "mod", chat_id), kit.btn("🏠 Menu", "home")]],
        )
    options = entry.get("options") or []
    back = ["poll", str(chat_id)]
    results_token = kit.new_pending("poll_results", {"chat": str(chat_id), "back": back})
    close_token = kit.new_pending("poll_close", {"chat": str(chat_id), "back": back})
    text = "\n".join([
        f"🗳 <b>Poll — {title}</b>",
        f"<b>{kit.h(entry.get('question', '?'), 200)}</b>",
        f"{len(options)} option(s) · created {kit.age(time.time() - float(entry.get('created', 0) or 0))} ago",
        "Tapping results or close types the command in the chat as you.",
    ])
    rows = [
        [kit.btn("📊 Results", "confirm", results_token)],
        [kit.btn("🛑 Close poll", "confirm", close_token)],
        [kit.btn("‹ Back", "mod", chat_id), kit.btn("🏠 Menu", "home")],
    ]
    return kit.Screen(text, rows)


#------------------------------
#Callback dispatch
#------------------------------

async def dispatch(ctx, event, route):
    """Render one screen route into the pressed message."""
    name = route[0] if route else "home"
    args = list(route[1:])

    if name == "do":
        action = args[0] if args else ""
        rest = args[1:]
        return await _dispatch_do(ctx, event, action, rest)

    if name == "confirm":
        screen, toast = confirm_screen(args[0] if args else "")
        await kit.edit(event, screen)
        await kit.answer(event, toast or "Confirm?")
        return

    if name == "notescope":
        screen = note_scope_screen(args[0] if args else 0)
    elif name == "chats":
        screen = chat_picker(args[0], args[1] if len(args) > 1 else 0)
    else:
        try:
            screen = _screen_for(route)
        except Exception:  # noqa: BLE001 - a broken store must not kill the menu
            log.exception("botui: screen %s failed", route)
            await kit.edit(event, kit.Screen(
                "❌ That screen could not be built. See the Replit log.",
                [[kit.btn("🏠 Menu", "home")]],
            ))
            await kit.answer(event, "Screen failed.")
            return
    await kit.edit(event, screen)
    await kit.answer(event)


async def _dispatch_do(ctx, event, action, rest):
    if action == "togglemonitor":
        data = monitor.load_data()
        settings = data.setdefault("__settings", {})
        settings["global_enabled"] = not bool(settings.get("global_enabled"))
        monitor.save_data(data)
        await kit.edit(event, auto_screen())
        await kit.answer(event, "Monitor toggled.")
        return

    if action == "todotoggle":
        toast = _toggle_todo(rest[0], rest[1])
        await kit.edit(event, todo_screen(rest[0]))
        await kit.answer(event, toast)
        return

    if action == "togglealerts":
        current = bool(kit.settings().get("alerts", True))
        kit.set_setting("alerts", not current)
        await kit.edit(event, settings_screen())
        await kit.answer(event, "Alerts off." if current else "Alerts on.")
        return

    if action == "pagesize":
        step = int(rest[0]) if rest else 1
        size = max(1, min(10, kit.page_size() + step))
        kit.set_setting("page_size", size)
        await kit.edit(event, settings_screen())
        await kit.answer(event, f"{size} rows per page.")
        return

    if action == "flow":
        flow_name = rest[0] if rest else ""
        if len(rest) > 2:
            data = {"scope": rest[1], "chat": rest[2]}
        elif len(rest) > 1:
            data = {"chat": rest[1]}
        else:
            data = {}
        if not kit.start_flow(ctx.owner_id, flow_name,
                              FLOW_START_STEPS.get(flow_name, "text"), data):
            await kit.answer(event, "Could not start that flow.", alert=True)
            return
        await kit.edit(event, flow_prompt(flow_name, data))
        await kit.answer(event, "Send the next message.")
        return

    if action == "flowcancel":
        kit.clear_flow(ctx.owner_id)
        await kit.edit(event, home_screen())
        await kit.answer(event, "Cancelled.")
        return

    if action == "cancel":
        token = rest[0] if rest else ""
        entry = kit.take_pending(token)
        back = (entry or {}).get("payload", {}).get("back", ["home"])
        await kit.edit(event, _screen_for(back))
        await kit.answer(event, "Cancelled." if entry else "Already expired.")
        return

    if action == "confirm":
        token = rest[0] if rest else ""
        entry = kit.take_pending(token)
        if not entry:
            await kit.edit(event, home_screen())
            await kit.answer(event, "That confirmation expired.", alert=True)
            return
        try:
            toast, screen = await _run_pending(ctx, entry.get("action"), entry.get("payload") or {})
        except Exception:  # noqa: BLE001
            log.exception("botui: confirmed action %s failed", entry.get("action"))
            toast, screen = "❌ The action failed; see the Replit log.", home_screen()
        await kit.edit(event, screen)
        await kit.answer(event, toast)
        return

    if action == "warnlimit":
        limit = _set_warn_limit(rest[0], rest[1])
        await kit.edit(event, mod_screen(rest[0]))
        await kit.answer(event, f"Warn limit is now {limit}.")
        return

    if action == "registercmds":
        ok = await botregistry.register(ctx.client)
        await kit.edit(event, commands_screen())
        await kit.answer(
            event,
            "Menu published to Telegram." if ok else "Telegram refused the menu; see the log.",
            alert=not ok,
        )
        return

    if action == "qretry":
        ok = interop.retry(rest[0])
        await kit.edit(event, queue_screen())
        await kit.answer(
            event,
            "Queued again. If the first attempt did reach Telegram, this may duplicate it."
            if ok else "Only failed or interrupted actions can be retried.",
            alert=True,
        )
        return

    if action == "qdrop":
        interop.drop(rest[0])
        await kit.edit(event, queue_screen())
        await kit.answer(event, "Removed.")
        return

    await kit.answer(event, "Unknown action.", alert=True)


#------------------------------
#Text flows
#------------------------------

def _note_body_prompt(scope, chat_id, name):
    where = "global" if scope == "g" else _chat_title(chat_id)
    return kit.Screen(
        f"📝 <b>{kit.h(name)} — {kit.h(where, 40)}</b>\n"
        "Send the note body now (up to 3500 characters).\n\n"
        "Send /cancel to stop.",
        [[kit.btn("✖️ Cancel", "do", "flowcancel")]],
    )


async def on_text(ctx, event):
    """Consume the owner's next message when a flow is waiting for text."""
    if event.sender_id != ctx.owner_id:
        return False
    text = (event.raw_text or "").strip()
    if not text or text.startswith("/"):
        return False
    flow = kit.active_flow(ctx.owner_id)
    if not flow:
        return False
    name = flow.get("name")
    step = flow.get("step")
    data = flow.get("data") or {}

    if name == "relay_text" and step == "text":
        chat_id = data.get("chat")
        token = kit.new_pending("relay_send", {
            "chat": str(chat_id), "text": text, "back": ["relay", str(chat_id)],
        })
        kit.clear_flow(ctx.owner_id)
        screen, _ = confirm_screen(token)
        await kit.send(ctx, screen)
        return True

    if name == "remind_add" and step == "text":
        first, _, remainder = text.partition(" ")
        try:
            seconds = parse_duration(first, minimum=5, maximum=365 * 86400)
        except ValueError as exc:
            await ctx.client.send_message(
                ctx.owner_id,
                brand.sign(f"❌ {kit.h(exc)}\nSend it again, or /cancel."),
                parse_mode="html",
            )
            return True
        if not remainder.strip():
            await ctx.client.send_message(
                ctx.owner_id,
                brand.sign(
                    "❌ Add what to remind you about: <code>30m tea</code>."
                ),
                parse_mode="html",
            )
            return True
        token = kit.new_pending("remind_add", {
            "seconds": seconds, "text": remainder.strip()[:remind.MAX_TEXT],
            "back": ["rem", "0"],
        })
        kit.clear_flow(ctx.owner_id)
        screen, _ = confirm_screen(token)
        await kit.send(ctx, screen)
        return True

    if name == "note_add" and step == "name":
        try:
            clean = note.normalize_name(text)
        except ValueError as exc:
            await ctx.client.send_message(
                ctx.owner_id,
                brand.sign(f"❌ {kit.h(exc)}\nSend another name, or /cancel."),
                parse_mode="html",
            )
            return True
        kit.update_flow(ctx.owner_id, step="text", data={"name": clean})
        await kit.send(ctx, _note_body_prompt(
            data.get("scope", "g"), data.get("chat"), clean))
        return True

    if name == "note_add" and step == "text":
        clean = data.get("name")
        scope = data.get("scope", "g")
        chat_id = data.get("chat")
        if not clean:
            kit.clear_flow(ctx.owner_id)
            await ctx.client.send_message(
                ctx.owner_id,
                brand.sign("That note flow lost its name; start again."),
                parse_mode="html",
            )
            return True
        replaced = _save_note(scope, chat_id, clean, text[:3500])
        kit.clear_flow(ctx.owner_id)
        await kit.send(ctx, notes_screen(scope, chat_id, 0))
        await ctx.client.send_message(
            ctx.owner_id,
            brand.sign(
                f"{'♻️ Replaced' if replaced else '✅ Saved'} note "
                f"<code>{kit.h(clean)}</code>."
            ),
            parse_mode="html",
        )
        return True

    if name == "todo_add" and step == "text":
        chat_id = data.get("chat")
        item_id, error = _add_todo(chat_id, text)
        kit.clear_flow(ctx.owner_id)
        await kit.send(ctx, todo_screen(chat_id))
        await ctx.client.send_message(
            ctx.owner_id,
            brand.sign(
                f"❌ {kit.h(error)}" if error
                else f"✅ Added todo <code>#{item_id}</code>."
            ),
            parse_mode="html",
        )
        return True

    if name == "enemy_add" and step == "text":
        chat_id = data.get("chat")
        first, _, rest = text.partition(" ")
        try:
            uid = int(first)
        except ValueError:
            await ctx.client.send_message(
                ctx.owner_id,
                brand.sign(
                    "❌ Send a numeric user id, optionally followed by a "
                    "category."
                ),
                parse_mode="html",
            )
            return True
        raw_category = rest.strip().split()[0] if rest.strip() else "default"
        category = "".join(ch for ch in raw_category
                           if ch.isalnum() or ch in "_-")[:24] or "default"
        added = _add_enemy(chat_id, uid, category)
        kit.clear_flow(ctx.owner_id)
        await kit.send(ctx, enemies_screen(chat_id))
        await ctx.client.send_message(
            ctx.owner_id,
            brand.sign(
                f"✅ Added <code>{uid}</code> as {kit.h(category)}." if added
                else f"❌ <code>{uid}</code> is already on that list."
            ),
            parse_mode="html",
        )
        return True

    kit.clear_flow(ctx.owner_id)
    await ctx.client.send_message(
        ctx.owner_id,
        brand.sign("That flow is no longer available."),
        parse_mode="html",
    )
    return True
