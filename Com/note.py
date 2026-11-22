"""`!note` -- persistent notes, per chat by default with an optional global scope.

Scope model
-----------
* Default scope is **this chat**: `{"chats": {"<chat_id>": {"<name>": note}}}`.
* `-g` (or `--global`) switches the command to the **global** scope:
  `{"global": {"<name>": note}}`, readable from every chat.
* `!note get <name>` looks in the chat scope first, then falls back to a global
  note with the same name, so a global note behaves like a default. `-g` reads
  global only. The reply says which scope was used.
* `!note list` shows both, global entries first.

Names are trimmed, lower-cased, and limited to ``[a-z0-9_.-]`` up to 32 chars.
Quoted names are accepted (``!note save "my list" ...``) but still have to pass
that check, so a name can never contain whitespace or a path separator.

Notes are stored verbatim -- no markdown parsing, no entity handling.
"""
import logging
import re
import shlex
import time

from telethon import events

import Com.core.registry as registry
from Com.core import brand, confirm
from Com.core.reply import say
from Com.core.storage import load_store, save_json

log = logging.getLogger("selftg.note")

NOTE_FILE = "mode/notes.json"
SCHEMA_VERSION = 1
NAME_RE = re.compile(r"^[a-z0-9_.-]{1,32}$")
PREVIEW_CHARS = 60

SUBCOMMANDS = [
    ("!note save [-g] <name> <text>", "save or overwrite (text may be a reply)"),
    ("!note get [-g] <name>", "print the note"),
    ("!note list [-g]", "list names with a short preview"),
    ("!note delete [-g] <name>", "delete one note"),
    ("!note rename [-g] <old> <new>", "rename a note"),
    ("!note clear [-g]", "delete every note in the scope (asks for a token)"),
]

__HELP__ = registry.command(
    "note", SUBCOMMANDS,
    "Persistent notes; per-chat by default, -g for global.",
)
__CATEGORY__ = "Utilities"

ACTION_CLEAR = "!note clear"


#------------------------------
#State
#------------------------------

def _default():
    return {"global": {}, "chats": {}}


def load_state():
    try:
        state = load_store(NOTE_FILE, SCHEMA_VERSION, _default)
    except Exception:  # noqa: BLE001
        log.exception("note: could not read the store")
        return _default()
    if not isinstance(state.get("global"), dict):
        state["global"] = {}
    if not isinstance(state.get("chats"), dict):
        state["chats"] = {}
    return state


def save_state(state):
    try:
        save_json(NOTE_FILE, state)
    except Exception:  # noqa: BLE001
        log.exception("note: could not write the store")
        return False
    return True


def _scope(state, global_scope, chat_id):
    if global_scope:
        return state["global"]
    return state["chats"].setdefault(str(chat_id), {})


def normalize_name(raw):
    name = (raw or "").strip().lower()
    if not NAME_RE.match(name):
        raise ValueError(
            "note names are 1-32 chars of a-z, 0-9, '_', '-' or '.'"
            " (quote names with spaces — they are still rejected)"
        )
    return name


def _parse_flags(args):
    """Pull an optional -g flag out of the argument string."""
    tokens = shlex.split(args)
    flag = False
    kept = []
    for token in tokens:
        if not flag and token in ("-g", "--global"):
            flag = True
            continue
        kept.append(token)
    return flag, kept


def _preview(text):
    flat = " ".join((text or "").split())
    return flat if len(flat) <= PREVIEW_CHARS else flat[: PREVIEW_CHARS - 1] + "…"


def _all_names(state):
    names = set(state["global"])
    for notes in state["chats"].values():
        names.update(notes)
    return names


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!note(?:\s+([\s\S]*))?$"))
    async def note_cmd(event):
        if not event.out or event.sender_id != my_id:
            return

        args = (event.pattern_match.group(1) or "").strip()
        if not args:
            await _say(event, "📖 " + brand.esc(__HELP__))
            return

        head, _, rest = args.partition(" ")
        sub = head.lower()

        try:
            global_scope, tokens = _parse_flags(rest)
        except ValueError as exc:
            await _say(event, f"❌ Could not parse arguments · {brand.esc(exc)}")
            return

        try:
            if sub == "save":
                await _cmd_save(event, tokens, global_scope)
            elif sub == "get":
                await _cmd_get(event, tokens, global_scope)
            elif sub == "list":
                await _cmd_list(event, global_scope)
            elif sub == "delete" or sub == "del":
                await _cmd_delete(event, tokens, global_scope)
            elif sub == "rename":
                await _cmd_rename(event, tokens, global_scope)
            elif sub == "clear":
                await _cmd_clear(event, rest if not tokens else " ".join(tokens), global_scope)
            else:
                await _say(event, "📖 " + brand.esc(__HELP__))
        except Exception:  # noqa: BLE001
            log.exception("note: command failed")
            await _say(event, "❌ <b>Note command failed.</b> See the Replit log.")

    async def _cmd_save(event, tokens, global_scope):
        if not tokens:
            await _say(
                event,
                "Usage · <code>!note save [-g] &lt;name&gt; &lt;text&gt;</code>",
            )
            return
        try:
            name = normalize_name(tokens[0])
        except ValueError as exc:
            await _say(event, f"❌ {brand.esc(exc)}")
            return

        text = " ".join(tokens[1:]).strip()
        if not text:
            if not event.is_reply:
                await _say(
                    event,
                    "❌ <b>Give the note text</b>, or reply to a message with it.",
                )
                return
            reply = await event.get_reply_message()
            text = (reply.raw_text or "").strip() if reply else ""
            if not text:
                await _say(event, "❌ <b>The replied message has no text to save.</b>")
                return

        state = load_state()
        scope = _scope(state, global_scope, event.chat_id)
        existed = name in scope
        scope[name] = {"text": text, "updated": time.time()}
        if not save_state(state):
            await _say(event, "❌ <b>Could not write the note store.</b>")
            return

        where = "global" if global_scope else "this chat"
        verb = "overwritten" if existed else "saved"
        await _say(
            event,
            f"📝 <b>Note</b> <code>{brand.esc(name)}</code> {verb} in {where} "
            f"<i>({len(text)} chars)</i>",
        )

    async def _cmd_get(event, tokens, global_scope):
        if not tokens:
            await _say(event, "Usage · <code>!note get [-g] &lt;name&gt;</code>")
            return
        try:
            name = normalize_name(tokens[0])
        except ValueError as exc:
            await _say(event, f"❌ {brand.esc(exc)}")
            return

        state = load_state()
        note = state["global"].get(name) if global_scope else None
        scope_label = "global"
        if note is None and not global_scope:
            note = state["chats"].get(str(event.chat_id), {}).get(name)
            scope_label = "this chat"
        if note is None and not global_scope:
            note = state["global"].get(name)
            scope_label = "global (fallback)"

        if note is None:
            await _say(
                event,
                f"❌ <b>No note</b> <code>{brand.esc(name)}</code> in "
                f"{'global scope' if global_scope else 'this chat or global'}.",
            )
            return

        updated = note.get("updated")
        stamp = (
            "\n\n<i>updated "
            + time.strftime('%Y-%m-%d %H:%M', time.localtime(updated))
            + "</i>"
        ) if updated else ""
        await _say(
            event,
            f"📄 <code>{brand.esc(name)}</code> <i>({scope_label})</i>\n\n"
            + brand.esc(note['text']) + stamp,
        )

    async def _cmd_list(event, global_scope):
        state = load_state()
        chat_notes = state["chats"].get(str(event.chat_id), {})
        lines = []

        if global_scope:
            source = state["global"]
            lines.append(f"🌍 <b>Global notes</b> · {len(source)}")
            scopes = [("", source)]
        else:
            lines.append(
                f"📒 <b>Notes here</b> · {len(chat_notes)} · "
                f"global · {len(state['global'])}"
            )
            scopes = [("", chat_notes), ("🌍 ", state["global"])]
            if not chat_notes and not state["global"]:
                await _say(
                    event,
                    "📭 <b>No notes yet.</b> Use "
                    "<code>!note save &lt;name&gt; &lt;text&gt;</code>.",
                )
                return

        for prefix, source in scopes:
            for name in sorted(source):
                lines.append(
                    f"• {prefix}<code>{brand.esc(name)}</code> · "
                    f"{brand.esc(_preview(source[name].get('text')))}"
                )
        await _say(event, "\n".join(lines))

    async def _cmd_delete(event, tokens, global_scope):
        if not tokens:
            await _say(event, "Usage · <code>!note delete [-g] &lt;name&gt;</code>")
            return
        try:
            name = normalize_name(tokens[0])
        except ValueError as exc:
            await _say(event, f"❌ {brand.esc(exc)}")
            return

        state = load_state()
        scope = _scope(state, global_scope, event.chat_id)
        if name not in scope:
            await _say(
                event,
                f"❌ <b>No note</b> <code>{brand.esc(name)}</code> in "
                f"{'global' if global_scope else 'this chat'}.",
            )
            return
        scope.pop(name)
        save_state(state)
        await _say(event, f"🗑️ <b>Deleted note</b> <code>{brand.esc(name)}</code>.")

    async def _cmd_rename(event, tokens, global_scope):
        if len(tokens) < 2:
            await _say(
                event,
                "Usage · <code>!note rename [-g] &lt;old&gt; &lt;new&gt;</code>",
            )
            return
        try:
            old = normalize_name(tokens[0])
            new = normalize_name(tokens[1])
        except ValueError as exc:
            await _say(event, f"❌ {brand.esc(exc)}")
            return

        state = load_state()
        scope = _scope(state, global_scope, event.chat_id)
        if old not in scope:
            await _say(event, f"❌ <b>No note</b> <code>{brand.esc(old)}</code>.")
            return
        if new in scope:
            await _say(
                event,
                f"❌ <code>{brand.esc(new)}</code> <b>already exists;</b> "
                "delete it first.",
            )
            return
        scope[new] = scope.pop(old)
        save_state(state)
        await _say(
            event,
            f"✏️ <b>Renamed</b> <code>{brand.esc(old)}</code> → "
            f"<code>{brand.esc(new)}</code>",
        )

    async def _cmd_clear(event, rest, global_scope):
        text = (rest or "").strip()
        where = "global" if global_scope else "this chat"

        if confirm.check(event.chat_id, ACTION_CLEAR, text):
            state = load_state()
            count = len(state["global"] if global_scope else state["chats"].get(str(event.chat_id), {}))
            if global_scope:
                state["global"] = {}
            else:
                state["chats"][str(event.chat_id)] = {}
            save_state(state)
            await _say(event, f"🗑️ <b>Deleted</b> {count} note(s) in {where}.")
            return

        if text and text.split()[0].lower() == "confirm":
            await _say(
                event,
                "❌ <b>That confirmation token is wrong or expired.</b> Run "
                "<code>!note clear</code> again.",
            )
            return

        prompt = confirm.request(
            event.chat_id, ACTION_CLEAR, f"This deletes every note in {where}."
        )
        await _say(event, prompt)

    async def _say(event, text):
        # Edit-then-reply is shared: see Com/core/reply.py.
        await say(event, text, name="note", parse_mode="html")
