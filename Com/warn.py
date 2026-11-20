"""!warn: the warning ledger, its limits and the actions they trigger."""
import os
import json
from telethon import events
import Com.core.tgsend as tgsend

from Com.core.storage import save_json

__HELP__ = (
    "!warn add <user> [reason] (or reply) → Add a warning to a user\n"
    "!warn limit <number> → Set warning limit for this chat (default: 3)\n"
    "!warn list → Show all warnings in this chat\n"
    "!warn clear <user> (or reply) → Clear all warnings for a user\n"
    "!warn del <user> <index> → Delete a specific warning by index (1‑based)\n"
    "When a user reaches the limit, a notification is sent."
)
__CATEGORY__ = "Utilities"

BASE_DIR = "mode"
WARN_FILE = os.path.join(BASE_DIR, "warn.json")
os.makedirs(BASE_DIR, exist_ok=True)

#------------------------------
#State
#------------------------------

# Default structure
DEFAULT_DATA = {
    # "chat_id": {
    #     "limit": 3,
    #     "warnings": { "user_id": ["reason1", "reason2"] }
    # }
}

def load_warns():
    if not os.path.exists(WARN_FILE):
        return {}
    try:
        with open(WARN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_warns(data):
    save_json(WARN_FILE, data)

def get_chat_data(chat_id):
    data = load_warns()
    chat_id_str = str(chat_id)
    if chat_id_str not in data:
        data[chat_id_str] = {"limit": 3, "warnings": {}}
        save_warns(data)
    return data[chat_id_str]

def save_chat_data(chat_id, chat_data):
    data = load_warns()
    data[str(chat_id)] = chat_data
    save_warns(data)

#------------------------------
#Helpers
#------------------------------

async def get_username(client, user_id):
    # Was run_until_complete() inside a running loop: always raised
    try:
        user = await client.get_entity(user_id)
        return f"@{user.username}" if user.username else f"ID:{user_id}"
    except Exception:
        return f"ID:{user_id}"

#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!warn add(?:\s+(.+))?$"))
    async def warn_add(event):
        try:
            reason = ""
            target_user_id = None

            # "!warn add @user reason", or "!warn add reason" in reply
            arg = event.pattern_match.group(1)
            if arg:
                parts = arg.split(maxsplit=1)
                target_str = parts[0]
                reason = parts[1] if len(parts) > 1 else "No reason"
                if target_str.isdigit():
                    target_user_id = int(target_str)
                else:
                    try:
                        entity = await client.get_entity(target_str)
                        target_user_id = entity.id
                    except:
                        await event.edit(f"❌ Could not find user: {target_str}")
                        return
            else:
                if not event.is_reply:
                    await event.edit("❌ Reply to a user or provide a username/ID.")
                    return
                reply = await event.get_reply_message()
                target_user_id = reply.sender_id
                reason = "No reason"

            if target_user_id is None:
                await event.edit("❌ Could not determine target user.")
                return

            chat_id = event.chat_id
            chat_data = get_chat_data(chat_id)
            limit = chat_data.get("limit", 3)
            warnings = chat_data.get("warnings", {})

            user_warnings = warnings.get(str(target_user_id), [])
            user_warnings.append(reason)
            warnings[str(target_user_id)] = user_warnings
            chat_data["warnings"] = warnings
            save_chat_data(chat_id, chat_data)

            username = await get_username(client, target_user_id)
            count = len(user_warnings)
            response = f"⚠️ Warning added to {username} (now {count}/{limit}): {reason}"
            if count >= limit:
                response += f"\n\n🚨 **{username} has reached the warning limit!**"

            await event.edit(response)
            await event.delete()  # remove command

        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!warn limit\s+(\d+)$"))
    async def warn_limit(event):
        try:
            new_limit = int(event.pattern_match.group(1))
            if new_limit < 1:
                await event.edit("❌ Limit must be at least 1.")
                return
            chat_id = event.chat_id
            chat_data = get_chat_data(chat_id)
            chat_data["limit"] = new_limit
            save_chat_data(chat_id, chat_data)
            await event.edit(f"✅ Warning limit set to {new_limit} for this chat.")
            await event.delete()
        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!warn list$"))
    async def warn_list(event):
        try:
            chat_id = event.chat_id
            chat_data = get_chat_data(chat_id)
            warnings = chat_data.get("warnings", {})
            if not warnings:
                await event.edit("📭 No warnings in this chat.")
                return

            lines = []
            for uid_str, reasons in warnings.items():
                uid = int(uid_str)
                name = await get_username(client, uid)
                lines.append(f"• {name} ({uid}) – {len(reasons)} warning(s)")
                for i, r in enumerate(reasons, start=1):
                    lines.append(f"  {i}. {r}")
            msg = "📋 **Warnings in this chat:**\n" + "\n".join(lines)
            if len(msg) > 4000:
                import io
                bio = io.BytesIO(msg.encode("utf-8"))
                bio.name = "warnings.txt"
                await client.send_file(await tgsend.peer(event), bio, caption="Warnings")
                await event.delete()
            else:
                await event.edit(msg)
        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!warn clear(?:\s+(.+))?$"))
    async def warn_clear(event):
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
            chat_data = get_chat_data(chat_id)
            warnings = chat_data.get("warnings", {})
            uid_str = str(target_user_id)
            if uid_str not in warnings:
                await event.edit(f"❌ User has no warnings.")
                return

            del warnings[uid_str]
            chat_data["warnings"] = warnings
            save_chat_data(chat_id, chat_data)
            cleared_name = await get_username(client, target_user_id)
            await event.edit(f"✅ Cleared warnings for {cleared_name}.")
            await event.delete()
        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!warn del\s+(\S+)\s+(\d+)$"))
    async def warn_del(event):
        try:
            target_str = event.pattern_match.group(1)
            index = int(event.pattern_match.group(2)) - 1  # convert to 0-based
            if index < 0:
                await event.edit("❌ Index must be >= 1.")
                return

            if target_str.isdigit():
                target_user_id = int(target_str)
            else:
                try:
                    entity = await client.get_entity(target_str)
                    target_user_id = entity.id
                except:
                    await event.edit(f"❌ Could not find user: {target_str}")
                    return

            chat_id = event.chat_id
            chat_data = get_chat_data(chat_id)
            warnings = chat_data.get("warnings", {})
            uid_str = str(target_user_id)
            if uid_str not in warnings:
                await event.edit(f"❌ User has no warnings.")
                return

            user_warnings = warnings[uid_str]
            if index >= len(user_warnings):
                await event.edit(f"❌ Invalid index. User has {len(user_warnings)} warnings.")
                return

            removed = user_warnings.pop(index)
            if not user_warnings:
                del warnings[uid_str]
            else:
                warnings[uid_str] = user_warnings
            chat_data["warnings"] = warnings
            save_chat_data(chat_id, chat_data)
            removed_name = await get_username(client, target_user_id)
            await event.edit(f"✅ Removed warning #{index+1}: '{removed}' from {removed_name}.")
            await event.delete()
        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")

    # Catch-all help
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!warn$"))
    async def warn_help(event):
        await event.edit(
            "📖 **Warn Commands**\n"
            "• `!warn add <user> [reason]` (or reply) – add warning\n"
            "• `!warn limit <number>` – set warning limit\n"
            "• `!warn list` – list warnings\n"
            "• `!warn clear <user>` (or reply) – clear warnings\n"
            "• `!warn del <user> <index>` – delete a specific warning"
        )