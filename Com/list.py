"""!list: named user lists stored as JSON under mode/lists."""
import os
import json
import asyncio
from datetime import datetime
from telethon import events
from telethon.tl.types import User
import Com.core.tgsend as tgsend

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
    # Sanitize name to avoid path traversal
    safe_name = "".join(c for c in name if c.isalnum() or c in "._-")
    return os.path.join(BASE_DIR, f"{safe_name}.json")

def load_list(name):
    path = get_list_path(name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_list(name, data):
    path = get_list_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

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
    name = info.get("name", "Unknown")
    username = f"@{info['username']}" if info.get("username") else "N/A"
    uid = info.get("id", "N/A")
    added = info.get("added", "Unknown")
    return f"{name} ({username}) – ID: {uid} (added: {added})"

#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list create\s+(\S+)$"))
    async def list_create(event):
        name = event.pattern_match.group(1)
        if load_list(name) is not None:
            await event.edit(f"❌ List '{name}' already exists.")
            return
        save_list(name, [])
        await event.edit(f"✅ List '{name}' created.")
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list add\s+(\S+)$"))
    async def list_add(event):
        name = event.pattern_match.group(1)
        if not event.is_reply:
            await event.edit("❌ Reply to a user's message to add them.")
            return
        reply = await event.get_reply_message()
        user_id = reply.sender_id
        if user_id is None:
            await event.edit("❌ Could not determine user.")
            return

        data = load_list(name)
        if data is None:
            await event.edit(f"❌ List '{name}' does not exist. Create it first with `!list create {name}`.")
            return

        if any(entry.get("id") == user_id for entry in data):
            await event.edit("❌ User already in this list.")
            return

        info = await get_user_info(client, user_id)
        if not info:
            await event.edit("❌ Failed to get user info.")
            return

        data.append(info)
        save_list(name, data)
        await event.edit(f"✅ Added {info['name']} (ID: {user_id}) to '{name}'.")
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list show\s+(\S+)$"))
    async def list_show(event):
        name = event.pattern_match.group(1)
        data = load_list(name)
        if data is None:
            await event.edit(f"❌ List '{name}' does not exist.")
            return
        if not data:
            await event.edit(f"📭 List '{name}' is empty.")
            return

        lines = []
        for idx, entry in enumerate(data, start=1):
            lines.append(f"{idx}. {format_entry(entry)}")

        msg = f"📋 **List: {name}** ({len(data)} entries)\n" + "\n".join(lines)
        if len(msg) > 4000:
            import io
            bio = io.BytesIO(msg.encode("utf-8"))
            bio.name = f"{name}.txt"
            await client.send_file(await tgsend.peer(event), bio, caption=f"📋 List: {name}")
            await event.delete()
        else:
            await event.edit(msg)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list remove\s+(\S+)\s+(\d+)$"))
    async def list_remove(event):
        name = event.pattern_match.group(1)
        idx = int(event.pattern_match.group(2)) - 1  # convert to 0-based
        data = load_list(name)
        if data is None:
            await event.edit(f"❌ List '{name}' does not exist.")
            return
        if idx < 0 or idx >= len(data):
            await event.edit(f"❌ Invalid index. Use 1 to {len(data)}.")
            return
        removed = data.pop(idx)
        save_list(name, data)
        await event.edit(f"✅ Removed: {format_entry(removed)}")
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list delete\s+(\S+)$"))
    async def list_delete(event):
        name = event.pattern_match.group(1)
        path = get_list_path(name)
        if not os.path.exists(path):
            await event.edit(f"❌ List '{name}' does not exist.")
            return
        os.remove(path)
        await event.edit(f"🗑️ Deleted list '{name}'.")
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list lists$"))
    async def list_lists(event):
        lists = get_all_lists()
        if not lists:
            await event.edit("📭 No lists created yet.")
            return
        msg = "📂 **Available lists:**\n" + "\n".join(f"• {l}" for l in lists)
        await event.edit(msg)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!list$"))
    async def list_help(event):
        await event.edit(
            "📖 **List Commands**\n"
            "• `!list create <name>` – new list\n"
            "• `!list add <name>` (reply) – add user\n"
            "• `!list show <name>` – show entries\n"
            "• `!list remove <name> <index>` – remove by index\n"
            "• `!list delete <name>` – delete whole list\n"
            "• `!list lists` – show all lists"
        )