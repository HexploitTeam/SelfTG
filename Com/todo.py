"""`!todo` -- a per-chat todo list with stable ids.

Ids are allocated from a per-chat counter and stored with each item, so deleting
item 3 never renumbers item 4 and `!todo done 4` keeps meaning the same thing
after a restart. The list itself is ordered by id.

Scope is always the current chat: todos from one chat are never mixed into
another.
"""
import logging
import time

from telethon import events

import Com.core.registry as registry
from Com.core import confirm
from Com.core.storage import load_store, save_json

log = logging.getLogger("selftg.todo")

TODO_FILE = "mode/todos.json"
SCHEMA_VERSION = 1
MAX_ITEMS = 200

SUBCOMMANDS = [
    ("!todo add <text>", "add an item (gets a stable index)"),
    ("!todo done <index>", "mark done"),
    ("!todo undone <index>", "mark not done"),
    ("!todo list", "pending items"),
    ("!todo list all", "pending and done"),
    ("!todo edit <index> <text>", "replace the text"),
    ("!todo delete <index>", "remove an item"),
    ("!todo clear", "remove completed items"),
    ("!todo clear all", "remove everything (asks for a token)"),
]

__HELP__ = registry.command(
    "todo", SUBCOMMANDS,
    "Per-chat todo list; ids stay stable across edits and restarts.",
)
__CATEGORY__ = "Utilities"

ACTION_CLEAR_ALL = "!todo clear all"


#------------------------------
#State
#------------------------------

def _default():
    return {"chats": {}}


def load_state():
    try:
        state = load_store(TODO_FILE, SCHEMA_VERSION, _default)
    except Exception:  # noqa: BLE001
        log.exception("todo: could not read the store")
        return _default()
    if not isinstance(state.get("chats"), dict):
        state["chats"] = {}
    return state


def save_state(state):
    try:
        save_json(TODO_FILE, state)
        return True
    except Exception:  # noqa: BLE001
        log.exception("todo: could not write the store")
        return False


def _chat(state, chat_id):
    bucket = state["chats"].get(str(chat_id))
    if not isinstance(bucket, dict):
        bucket = {"next_id": 1, "items": []}
        state["chats"][str(chat_id)] = bucket
    if not isinstance(bucket.get("items"), list):
        bucket["items"] = []
    bucket.setdefault("next_id", 1)
    return bucket


def _find(bucket, index):
    for item in bucket["items"]:
        if item.get("id") == index:
            return item
    return None


def _render(bucket, show_done):
    items = [item for item in bucket["items"] if show_done or not item.get("done")]
    if not items:
        return None
    lines = []
    for item in sorted(items, key=lambda entry: entry["id"]):
        mark = "✅" if item.get("done") else "⬜"
        lines.append(f"{mark} `{item['id']}.` {item['text']}")
    done = sum(1 for item in bucket["items"] if item.get("done"))
    lines.append(f"\n_{len(bucket['items'])} total · {done} done · {len(bucket['items']) - done} pending_")
    return "\n".join(lines)


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!todo(?:\s+([\s\S]*))?$"))
    async def todo_cmd(event):
        if not event.out or event.sender_id != my_id:
            return

        args = (event.pattern_match.group(1) or "").strip()
        if not args:
            await _say(event, "📖 " + __HELP__)
            return

        head, _, rest = args.partition(" ")
        sub = head.lower()
        rest = rest.strip()

        try:
            if sub == "add":
                await _cmd_add(event, rest)
            elif sub in ("done", "undone", "delete", "del", "edit"):
                await _cmd_item(event, sub, rest)
            elif sub == "list":
                await _cmd_list(event, rest)
            elif sub == "clear":
                await _cmd_clear(event, rest)
            else:
                await _say(event, "📖 " + __HELP__)
        except Exception:  # noqa: BLE001
            log.exception("todo: command failed")
            await _say(event, "❌ Todo command failed; see the Replit log.")

    async def _cmd_add(event, text):
        if not text:
            await _say(event, "Usage: `!todo add <text>`")
            return

        state = load_state()
        bucket = _chat(state, event.chat_id)
        if len(bucket["items"]) >= MAX_ITEMS:
            await _say(event, f"❌ This list already has {MAX_ITEMS} items.")
            return

        duplicate = any(
            (item.get("text") or "").strip().lower() == text.strip().lower()
            for item in bucket["items"]
        )
        item_id = int(bucket["next_id"])
        bucket["next_id"] = item_id + 1
        bucket["items"].append(
            {"id": item_id, "text": text, "done": False, "created": time.time(), "done_at": None}
        )
        if not save_state(state):
            await _say(event, "❌ Could not write the todo store.")
            return

        note = "\n⚠️ There is already an item with the same text." if duplicate else ""
        await _say(event, f"➕ Added `{item_id}.` {text}{note}")

    async def _cmd_item(event, sub, rest):
        raw_index, _, text = rest.partition(" ")
        raw_index = raw_index.strip().strip("#").rstrip(".")
        if not raw_index.isdigit():
            await _say(event, f"Usage: `!todo {sub} <index>` (see `!todo list all`)")
            return
        index = int(raw_index)

        state = load_state()
        bucket = _chat(state, event.chat_id)
        item = _find(bucket, index)
        if item is None:
            await _say(event, f"❌ No item `{index}` in this chat.")
            return

        if sub == "done":
            item["done"] = True
            item["done_at"] = time.time()
            message = f"✅ `{index}.` marked done."
        elif sub == "undone":
            item["done"] = False
            item["done_at"] = None
            message = f"⬜ `{index}.` marked pending."
        elif sub == "edit":
            if not text.strip():
                await _say(event, "Usage: `!todo edit <index> <text>`")
                return
            item["text"] = text.strip()
            message = f"✏️ `{index}.` updated."
        else:
            bucket["items"] = [entry for entry in bucket["items"] if entry.get("id") != index]
            message = f"🗑️ `{index}.` deleted."

        if not save_state(state):
            await _say(event, "❌ Could not write the todo store.")
            return
        await _say(event, message)

    async def _cmd_list(event, rest):
        show_done = rest.strip().lower() in ("all", "everything")
        state = load_state()
        bucket = _chat(state, event.chat_id)
        body = _render(bucket, show_done)
        if body is None:
            if show_done:
                await _say(event, "📭 Nothing here yet. Add one with `!todo add <text>`.")
            else:
                await _say(event, "🎉 Nothing pending. `!todo list all` shows completed items.")
            return
        await _say(event, ("📋 **Todos**\n" + body))

    async def _cmd_clear(event, rest):
        keyword = rest.strip().lower()

        if keyword.startswith("all"):
            tail = keyword[len("all"):].strip()
            if confirm.check(event.chat_id, ACTION_CLEAR_ALL, rest):
                state = load_state()
                bucket = _chat(state, event.chat_id)
                count = len(bucket["items"])
                bucket["items"] = []
                save_state(state)
                await _say(event, f"🗑️ Deleted all {count} item(s).")
                return
            if tail:
                await _say(event, "❌ Wrong or expired confirmation token. Run `!todo clear all` again.")
                return
            prompt = confirm.request(
                event.chat_id, ACTION_CLEAR_ALL, "This deletes every todo item in this chat."
            )
            await _say(event, prompt)
            return

        state = load_state()
        bucket = _chat(state, event.chat_id)
        before = len(bucket["items"])
        bucket["items"] = [item for item in bucket["items"] if not item.get("done")]
        removed = before - len(bucket["items"])
        save_state(state)
        await _say(
            event,
            f"🗑️ Removed {removed} completed item(s)." if removed else "📭 No completed items to remove.",
        )

    async def _say(event, text):
        try:
            await event.edit(text)
        except Exception:
            try:
                await event.reply(text)
            except Exception:
                log.info("todo: response could not be delivered")
