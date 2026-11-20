"""!mute: the mute ledger and the admin actions behind it."""
import os
from telethon import events

from Com.core.storage import ensure_json_file, load_json, save_json

__HELP__ = (
    "!mute add <user> (or reply) → Mute (admin mode: tries to delete)\n"
    "!mute addm <user> (or reply) → Mute (manual mode: always replies with 'del')\n"
    "!mute remove <user> (or reply) → Unmute a user\n"
    "!mute list → List muted users in this chat\n\n"
    "Admin mode deletes messages if possible; manual mode always replies 'del'."
)
__CATEGORY__ = "Utilities"

BASE_DIR = "mode"
MUTE_FILE = os.path.join(BASE_DIR, "mute.json")
os.makedirs(BASE_DIR, exist_ok=True)

ensure_json_file(MUTE_FILE, {})

#------------------------------
#State
#------------------------------

def load_mutes():
    data = load_json(MUTE_FILE, {})
    return data if isinstance(data, dict) else {}

def save_mutes(data):
    save_json(MUTE_FILE, data)

def migrate_user_list(users):
    new_list = []
    for item in users:
        if isinstance(item, int):
            new_list.append({"user_id": item, "mode": "admin"})
        elif isinstance(item, dict) and "user_id" in item:
            new_list.append(item)
    return new_list

def get_muted_users(chat_id):
    data = load_mutes()
    chat_id_str = str(chat_id)
    if chat_id_str not in data:
        return []
    users = data[chat_id_str]
    if not isinstance(users, list):
        return []
    migrated = migrate_user_list(users)
    if migrated != users:
        data[chat_id_str] = migrated
        save_mutes(data)
    return migrated

def set_muted_users(chat_id, users):
    data = load_mutes()
    data[str(chat_id)] = users
    save_mutes(data)

#------------------------------
#Helpers
#------------------------------

async def get_username(client, user_id):
    # Same fix as Com/warn.py
    try:
        user = await client.get_entity(user_id)
        return f"@{user.username}" if user.username else f"ID:{user_id}"
    except Exception:
        return f"ID:{user_id}"

#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage)
    async def mute_handler(event):
        if event.sender_id == my_id:
            return
        if not event.raw_text and not event.message.media:
            return
        if event.raw_text and event.raw_text.startswith("!"):
            return

        chat_id = event.chat_id
        muted_list = get_muted_users(chat_id)
        entry = next((e for e in muted_list if e["user_id"] == event.sender_id), None)
        if not entry:
            return

        mode = entry.get("mode", "admin")
        if mode == "admin":
            try:
                await event.delete()
                return
            except Exception:
                try:
                    await event.reply("del")
                except:
                    pass
        else:
            try:
                await event.reply("del")
            except:
                pass

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!mute add(?:\s+(.+))?$"))
    async def mute_add(event):
        await _add_mute(event, mode="admin")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!mute addm(?:\s+(.+))?$"))
    async def mute_add_manual(event):
        await _add_mute(event, mode="manual")

    async def _add_mute(event, mode):
        try:
            target_user_id = None
            arg = event.pattern_match.group(1)
            if arg:
                if arg.isdigit():
                    target_user_id = int(arg)
                else:
                    try:
                        entity = await client.get_entity(arg)
                        target_user_id = entity.id
                    except:
                        await event.edit(f"❌ Could not find user: {arg}")
                        return
            else:
                if not event.is_reply:
                    await event.edit("❌ Reply to a user or provide a username/ID.")
                    return
                reply = await event.get_reply_message()
                target_user_id = reply.sender_id

            if target_user_id is None:
                await event.edit("❌ Could not determine target user.")
                return

            chat_id = event.chat_id
            muted_list = get_muted_users(chat_id)
            if any(e["user_id"] == target_user_id for e in muted_list):
                await event.edit("❌ User is already muted.")
                return

            muted_list.append({"user_id": target_user_id, "mode": mode})
            set_muted_users(chat_id, muted_list)
            username = await get_username(client, target_user_id)
            mode_label = "admin" if mode == "admin" else "manual"
            await event.edit(f"✅ Muted {username} ({mode_label} mode)")
            await event.delete()

        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!mute remove(?:\s+(.+))?$"))
    async def mute_remove(event):
        try:
            target_user_id = None
            arg = event.pattern_match.group(1)
            if arg:
                if arg.isdigit():
                    target_user_id = int(arg)
                else:
                    try:
                        entity = await client.get_entity(arg)
                        target_user_id = entity.id
                    except:
                        await event.edit(f"❌ Could not find user: {arg}")
                        return
            else:
                if not event.is_reply:
                    await event.edit("❌ Reply to a user or provide a username/ID.")
                    return
                reply = await event.get_reply_message()
                target_user_id = reply.sender_id

            if target_user_id is None:
                await event.edit("❌ Could not determine target user.")
                return

            chat_id = event.chat_id
            muted_list = get_muted_users(chat_id)
            new_list = [e for e in muted_list if e["user_id"] != target_user_id]
            if len(new_list) == len(muted_list):
                await event.edit("❌ User is not muted.")
                return

            set_muted_users(chat_id, new_list)
            username = await get_username(client, target_user_id)
            await event.edit(f"✅ Unmuted {username}")
            await event.delete()

        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!mute list$"))
    async def mute_list(event):
        chat_id = event.chat_id
        muted_list = get_muted_users(chat_id)
        if not muted_list:
            await event.edit("📭 No muted users in this chat.")
            return

        lines = []
        for entry in muted_list:
            uid = entry["user_id"]
            mode = entry.get("mode", "admin")
            name = await get_username(client, uid)
            lines.append(f"• {name} ({mode} mode)")
        msg = "📋 **Muted users in this chat:**\n" + "\n".join(lines)
        await event.edit(msg)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!mute$"))
    async def mute_help(event):
        await event.edit(
            "📖 **Mute Commands**\n"
            "• `!mute add <user>` (or reply) – admin mode (try delete)\n"
            "• `!mute addm <user>` (or reply) – manual mode (always reply del)\n"
            "• `!mute remove <user>` (or reply) – unmute\n"
            "• `!mute list` – list muted users"
        )