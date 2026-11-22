"""!list: named user lists stored as JSON under mode/lists."""
import os
import asyncio
from datetime import datetime
from telethon import events
from telethon.tl.types import User
import Com.core.tgsend as tgsend

from Com.core import brand
from Com.core.reply import say
from Com.core.storage import load_json, save_json

__HELP__ = (
    "!list create <name> → Create a new empty list\n"
    "!list add <name> (reply to a user) → Add user info to the list\n"
    "!list show <name> → Show all entries in the list\n"
    "!list remove <name> <index> → Remove entry by index (1‑based)\n"
    "!list delete <name> → Delete the entire list\n"
    "!list lists → Show all available lists"
)
__CATEGORY__ = "Utilities"

BASE_DIR = "mode/lists"
os.makedirs(BASE_DIR, exist_ok=True)

#------------------------------
#Storage
#------------------------------

def get_list_path(name):
    # No path traversal
    safe_name = "".join(c for c in name if c.isalnum() or c in "._-")
    return os.path.join(BASE_DIR, f"{safe_name}.json")

def load_list(name):
    path = get_list_path(name)
    if not os.path.exists(path):
        return None
    data = load_json(path, [])
    return data if isinstance(data, list) else []

def save_list(name, data):
    # Atomic write
    save_json(get_list_path(name), data)

def get_all_lists():
    files = os.listdir(BASE_DIR)
    return [f[:-5] for f in files if f.endswith(".json")]

#------------------------------
#Helpers
#------------------------------

async def get_user_info(client, user_id):
    try:
        user = await client.get_entity(user_id)
        info = {
            "id": user.id,
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "username": user.username or "",
            "phone": user.phone or "",
            "is_bot": getattr(user, "bot", False),
            "added": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        if info["first_name"] and info["last_name"]:
            info["name"] = f"{info['first_name']} {info['last_name']}"
        else:
            info["name"] = info["first_name"] or info["username"] or str(info["id"])
        return info
    except Exception as e:
        return None

def format_entry(info):
    name = brand.esc(info.get("name", "Unknown"))
    username = f"@{brand.esc(info['username'])}" if info.get("username") else "N/A"
    uid = brand.esc(info.get("id", "N/A"))
    added = brand.esc(info.get("added", "Unknown"))
    return (
        f"<b>{name}</b> ({username}) · ID <code>{uid}</code> · "
        f"added <code>{added}</code>"
    )

#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list create\s+(\S+)$"))
    async def list_create(event):
        name = event.pattern_match.group(1)
        if load_list(name) is not None:
            await say(
                event,
                f"❌ <b>List already exists.</b> <code>{brand.esc(name)}</code>",
                name="list",
                parse_mode="html",
            )
            return
        save_list(name, [])
        await say(
            event,
            f"✅ <b>List created.</b> <code>{brand.esc(name)}</code>",
            name="list",
            parse_mode="html",
        )
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list add\s+(\S+)$"))
    async def list_add(event):
        name = event.pattern_match.group(1)
        if not event.is_reply:
            await say(
                event, "❌ Reply to a user's message to add them.", name="list"
            )
            return
        reply = await event.get_reply_message()
        user_id = reply.sender_id
        if user_id is None:
            await say(event, "❌ Could not determine user.", name="list")
            return

        data = load_list(name)
        if data is None:
            await say(
                event,
                f"❌ <b>List does not exist.</b> <code>{brand.esc(name)}</code>\n"
                f"Create it first with <code>!list create "
                f"{brand.esc(name)}</code>.",
                name="list",
                parse_mode="html",
            )
            return

        if any(entry.get("id") == user_id for entry in data):
            await say(event, "❌ User already in this list.", name="list")
            return

        info = await get_user_info(client, user_id)
        if not info:
            await say(event, "❌ Failed to get user info.", name="list")
            return

        data.append(info)
        save_list(name, data)
        await say(
            event,
            f"✅ <b>Added</b> {brand.esc(info['name'])} "
            f"(<code>{user_id}</code>) to <code>{brand.esc(name)}</code>.",
            name="list",
            parse_mode="html",
        )
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list show\s+(\S+)$"))
    async def list_show(event):
        name = event.pattern_match.group(1)
        data = load_list(name)
        if data is None:
            await say(
                event,
                f"❌ <b>List does not exist.</b> <code>{brand.esc(name)}</code>",
                name="list",
                parse_mode="html",
            )
            return
        if not data:
            await say(
                event,
                f"📭 <b>List is empty.</b> <code>{brand.esc(name)}</code>",
                name="list",
                parse_mode="html",
            )
            return

        lines = []
        for idx, entry in enumerate(data, start=1):
            lines.append(f"{idx}. {format_entry(entry)}")

        msg = (
            f"📋 <b>List</b> · <code>{brand.esc(name)}</code> "
            f"({len(data)} entries)\n" + "\n".join(lines)
        )
        if len(msg) > 4000:
            import io
            bio = io.BytesIO(brand.plain(msg).encode("utf-8"))
            bio.name = f"{name}.txt"
            await client.send_file(
                await tgsend.peer(event),
                bio,
                caption=brand.sign(
                    f"📋 <b>List</b> · <code>{brand.esc(name)}</code>", "list"
                ),
                parse_mode="html",
            )
            await event.delete()
        else:
            await say(event, msg, name="list", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list remove\s+(\S+)\s+(\d+)$"))
    async def list_remove(event):
        name = event.pattern_match.group(1)
        idx = int(event.pattern_match.group(2)) - 1  # convert to 0-based
        data = load_list(name)
        if data is None:
            await say(
                event,
                f"❌ <b>List does not exist.</b> <code>{brand.esc(name)}</code>",
                name="list",
                parse_mode="html",
            )
            return
        if idx < 0 or idx >= len(data):
            await say(
                event,
                f"❌ <b>Invalid index.</b> Use 1 to <code>{len(data)}</code>.",
                name="list",
                parse_mode="html",
            )
            return
        removed = data.pop(idx)
        save_list(name, data)
        await say(
            event,
            f"✅ <b>Removed</b>\n{format_entry(removed)}",
            name="list",
            parse_mode="html",
        )
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list delete\s+(\S+)$"))
    async def list_delete(event):
        name = event.pattern_match.group(1)
        path = get_list_path(name)
        if not os.path.exists(path):
            await say(
                event,
                f"❌ <b>List does not exist.</b> <code>{brand.esc(name)}</code>",
                name="list",
                parse_mode="html",
            )
            return
        os.remove(path)
        await say(
            event,
            f"🗑️ <b>Deleted list</b> <code>{brand.esc(name)}</code>.",
            name="list",
            parse_mode="html",
        )
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list lists$"))
    async def list_lists(event):
        lists = get_all_lists()
        if not lists:
            await say(event, "📭 No lists created yet.", name="list")
            return
        msg = "📂 <b>Available lists</b>\n" + "\n".join(
            f"• <code>{brand.esc(name)}</code>" for name in lists
        )
        await say(event, msg, name="list", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list$"))
    async def list_help(event):
        await say(
            event,
            "📖 <b>List Commands</b>\n"
            "• <code>!list create &lt;name&gt;</code> – new list\n"
            "• <code>!list add &lt;name&gt;</code> (reply) – add user\n"
            "• <code>!list show &lt;name&gt;</code> – show entries\n"
            "• <code>!list remove &lt;name&gt; &lt;index&gt;</code> – remove by "
            "index\n"
            "• <code>!list delete &lt;name&gt;</code> – delete whole list\n"
            "• <code>!list lists</code> – show all lists",
            name="list",
            parse_mode="html",
        )