# Com/enemy.py
import os
import json
import re
from telethon import events

__HELP__ = (
    "!enemy add (reply) → Add replied user as enemy (default category)\n"
    "!enemy add no (reply) → Add replied user as enemy (no category)\n"
    "!enemy del (reply or <user_id>) → Remove enemy from this chat\n"
    "!enemy rep <text> (reply to enemy) → Set custom reply text for that enemy\n"
    "!enemy list → Show enemies in this chat\n"
    "!enemy list show → Show ALL enemies (global) across all chats\n"
    "!enemy list del → Delete ALL enemies in the current chat\n"
    "!enemy list texts → Show default text list with IDs\n"
    "!enemy list texts no → Show no text list with IDs\n"
    "!enemy list add <text> → Add text to default list\n"
    "!enemy list add no <text> → Add text to no list\n"
    "!enemy list del <id> → Delete line by ID from default list\n"
    "!enemy list del no <id> → Delete line by ID from no list\n"
    "!enemy clist (reply) → Add replied message text to default list\n"
    "!enemy clist no (reply) → Add replied message text to no list\n"
    "!enemy clist show → Show default list with IDs\n"
    "!enemy clist no show → Show no list with IDs"
)
__CATEGORY__ = "Utilities"

# -------------------------
# File paths
# -------------------------
BASE_DIR = "mode"
ENEMY_FILE = os.path.join(BASE_DIR, "Enemy.json")
ELIST_FILE = os.path.join(BASE_DIR, "EList.json")
ELISTNO_FILE = os.path.join(BASE_DIR, "EListNO.json")
STATE_FILE = os.path.join(BASE_DIR, "enemy_state.json")

os.makedirs(BASE_DIR, exist_ok=True)

# Initialize empty files if missing
if not os.path.exists(ENEMY_FILE):
    with open(ENEMY_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f, indent=2)

for fpath in [ELIST_FILE, ELISTNO_FILE]:
    if not os.path.exists(fpath):
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)

if not os.path.exists(STATE_FILE):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f, indent=2)


# -------------------------
# Helper functions
# -------------------------
def load_json(fpath):
    with open(fpath, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(fpath, data):
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_next_id(data):
    """Return max existing id + 1, or 1 if empty."""
    if not data:
        return 1
    return max(item["id"] for item in data) + 1

def get_enemy_data(chat_id):
    """Return list of enemies for a given chat (as dict)."""
    data = load_json(ENEMY_FILE)
    if not isinstance(data, dict):
        data = {}
        save_json(ENEMY_FILE, data)
    chat_id_str = str(chat_id)
    return data.get(chat_id_str, [])

def save_enemy_data(chat_id, enemies):
    data = load_json(ENEMY_FILE)
    if not isinstance(data, dict):
        data = {}
    data[str(chat_id)] = enemies
    save_json(ENEMY_FILE, data)

def find_enemy_by_user_id(chat_id, user_id):
    enemies = get_enemy_data(chat_id)
    for e in enemies:
        if e["user_id"] == user_id:
            return e
    return None

def get_username(client, user_id):
    try:
        user = client.loop.run_until_complete(client.get_entity(user_id))
        return f"@{user.username}" if user.username else f"ID:{user_id}"
    except:
        return f"ID:{user_id}"

# ---------- Round‑robin state ----------
def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def get_next_index(chat_id, category):
    """Return the current index and increment it for next time."""
    state = load_state()
    chat_key = str(chat_id)
    if chat_key not in state:
        state[chat_key] = {"default": 0, "no": 0}
    idx = state[chat_key].get(category, 0)
    # Increment for next call (will be saved after the reply)
    return idx

def save_next_index(chat_id, category, new_idx):
    state = load_state()
    chat_key = str(chat_id)
    if chat_key not in state:
        state[chat_key] = {"default": 0, "no": 0}
    state[chat_key][category] = new_idx
    save_state(state)


# -------------------------
# Setup
# -------------------------
def setup(client, my_id):

    # -------------------------
    # Auto‑reply handler
    # -------------------------
    @client.on(events.NewMessage)
    async def enemy_auto_reply(event):
        # Ignore own messages, commands, and messages without text
        if event.sender_id == my_id:
            return
        if not event.raw_text:
            return
        if event.raw_text.startswith("!"):
            return

        chat_id = event.chat_id
        sender_id = event.sender_id

        enemy = find_enemy_by_user_id(chat_id, sender_id)
        if not enemy:
            return

        # Determine reply text
        if enemy.get("custom_text"):
            reply_text = enemy["custom_text"]
        else:
            category = enemy.get("category", "default")
            list_file = ELIST_FILE if category == "default" else ELISTNO_FILE
            lines = load_json(list_file)

            # Ensure lines is a list of dicts with "text" key
            if not isinstance(lines, list):
                if isinstance(lines, dict):
                    lines = [{"id": k, "text": v} for k, v in lines.items()]
                    save_json(list_file, lines)
                else:
                    lines = []
            lines = [item for item in lines if isinstance(item, dict) and "text" in item]

            if not lines:
                reply_text = "(no replies configured for this category)"
            else:
                # ---- Round‑robin selection ----
                idx = get_next_index(chat_id, category)
                reply_text = lines[idx]["text"]
                new_idx = (idx + 1) % len(lines)
                save_next_index(chat_id, category, new_idx)

        await event.reply(reply_text)

    # -------------------------
    # !enemy add (default)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+add$"))
    async def enemy_add(event):
        if not event.is_reply:
            await event.edit("❌ Reply to a user to add them as enemy.")
            return
        reply = await event.get_reply_message()
        user_id = reply.sender_id
        chat_id = event.chat_id

        if find_enemy_by_user_id(chat_id, user_id):
            await event.edit("❌ This user is already an enemy. Delete and re‑add if you want to change category.")
            return

        enemies = get_enemy_data(chat_id)
        enemies.append({"user_id": user_id, "category": "default", "custom_text": None})
        save_enemy_data(chat_id, enemies)
        await event.edit("✅ Added enemy (default category).")
        await event.delete()

    # -------------------------
    # !enemy add no
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+add\s+no$"))
    async def enemy_add_no(event):
        if not event.is_reply:
            await event.edit("❌ Reply to a user to add them as enemy.")
            return
        reply = await event.get_reply_message()
        user_id = reply.sender_id
        chat_id = event.chat_id

        if find_enemy_by_user_id(chat_id, user_id):
            await event.edit("❌ This user is already an enemy. Delete and re‑add if you want to change category.")
            return

        enemies = get_enemy_data(chat_id)
        enemies.append({"user_id": user_id, "category": "no", "custom_text": None})
        save_enemy_data(chat_id, enemies)
        await event.edit("✅ Added enemy (no category).")
        await event.delete()

    # -------------------------
    # !enemy del (reply or ID)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+del(?:\s+(\d+))?$"))
    async def enemy_del(event):
        chat_id = event.chat_id
        user_id = None

        # If numeric argument, use that
        match = event.pattern_match.group(1)
        if match:
            user_id = int(match)
        elif event.is_reply:
            reply = await event.get_reply_message()
            user_id = reply.sender_id

        if not user_id:
            await event.edit("❌ Reply to an enemy or provide a user ID.")
            return

        enemy = find_enemy_by_user_id(chat_id, user_id)
        if not enemy:
            await event.edit("❌ This user is not an enemy in this chat.")
            return

        enemies = get_enemy_data(chat_id)
        enemies = [e for e in enemies if e["user_id"] != user_id]
        save_enemy_data(chat_id, enemies)
        await event.edit("✅ Enemy removed.")
        await event.delete()

    # -------------------------
    # !enemy rep <text> (reply to enemy)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+rep\s+(.+)$"))
    async def enemy_rep(event):
        if not event.is_reply:
            await event.edit("❌ Reply to a user to set custom text (they will be added as enemy if not already).")
            return
        text = event.pattern_match.group(1).strip()
        reply = await event.get_reply_message()
        user_id = reply.sender_id
        chat_id = event.chat_id

        enemy = find_enemy_by_user_id(chat_id, user_id)
        if not enemy:
            # Automatically add as enemy (default category) with the custom text
            enemies = get_enemy_data(chat_id)
            enemies.append({"user_id": user_id, "category": "default", "custom_text": text})
            save_enemy_data(chat_id, enemies)
            await event.edit(f"✅ User added as enemy with custom text: {text}")
            await event.delete()
            return

        # Update custom text for existing enemy
        enemies = get_enemy_data(chat_id)
        for e in enemies:
            if e["user_id"] == user_id:
                e["custom_text"] = text
                break
        save_enemy_data(chat_id, enemies)
        await event.edit(f"✅ Custom reply text updated for enemy: {text}")
        await event.delete()

    # -------------------------
    # !enemy list (show enemies in current chat)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list$"))
    async def enemy_list(event):
        chat_id = event.chat_id
        enemies = get_enemy_data(chat_id)
        if not enemies:
            await event.edit("❌ No enemies in this chat.")
            return

        lines = []
        for e in enemies:
            uid = e["user_id"]
            name = get_username(client, uid)
            cat = e.get("category", "default")
            custom = e.get("custom_text")
            custom_str = f" (custom: {custom})" if custom else ""
            lines.append(f"• {name} (ID: {uid}) – category: {cat}{custom_str}")

        msg = "📋 **Enemies in this chat:**\n" + "\n".join(lines)
        await event.edit(msg)

    # -------------------------
    # !enemy list show (global enemies)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+show$"))
    async def enemy_list_show_global(event):
        all_data = load_json(ENEMY_FILE)
        if not isinstance(all_data, dict):
            all_data = {}
            save_json(ENEMY_FILE, all_data)
        if not all_data:
            await event.edit("📭 No enemies anywhere.")
            return

        lines = []
        for chat_id_str, enemies in all_data.items():
            if not enemies:
                continue
            # Try to get chat name
            try:
                chat = await client.get_entity(int(chat_id_str))
                chat_name = chat.title or chat.first_name or chat_id_str
            except:
                chat_name = chat_id_str
            lines.append(f"**Chat:** {chat_name} (ID: {chat_id_str})")
            for e in enemies:
                uid = e["user_id"]
                name = get_username(client, uid)
                cat = e.get("category", "default")
                custom = e.get("custom_text")
                custom_str = f" (custom: {custom})" if custom else ""
                lines.append(f"  • {name} (ID: {uid}) – {cat}{custom_str}")
            lines.append("")  # blank line between chats

        msg = "🌍 **All Enemies (global):**\n" + "\n".join(lines)
        if len(msg) > 4000:
            import io
            bio = io.BytesIO(msg.encode("utf-8"))
            bio.name = "enemies_global.txt"
            await client.send_file(event.chat_id, bio, caption="Global enemy list")
            await event.edit("📄 Too many enemies, sent as file.")
            await event.delete()
        else:
            await event.edit(msg)

    # -------------------------
    # !enemy list del (delete all enemies in current chat)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+del$"))
    async def enemy_list_del_all(event):
        chat_id = event.chat_id
        enemies = get_enemy_data(chat_id)
        if not enemies:
            await event.edit("❌ No enemies in this chat to delete.")
            return
        save_enemy_data(chat_id, [])
        await event.edit("✅ All enemies in this chat have been removed.")
        await event.delete()

    # -------------------------
    # !enemy list texts (show default list)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+texts$"))
    async def enemy_list_texts(event):
        data = load_json(ELIST_FILE)
        if not data:
            await event.edit("📭 Default list is empty.")
            return
        lines = [f"{item['id']}: {item['text']}" for item in data]
        msg = "📋 **Default List:**\n" + "\n".join(lines)
        await event.edit(msg)

    # -------------------------
    # !enemy list texts no (show no list)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+texts\s+no$"))
    async def enemy_list_texts_no(event):
        data = load_json(ELISTNO_FILE)
        if not data:
            await event.edit("📭 No list is empty.")
            return
        lines = [f"{item['id']}: {item['text']}" for item in data]
        msg = "📋 **No List:**\n" + "\n".join(lines)
        await event.edit(msg)

    # -------------------------
    # !enemy list add <text>
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+add\s+(.+)$"))
    async def enemy_list_add(event):
        text = event.pattern_match.group(1).strip()
        data = load_json(ELIST_FILE)
        new_id = get_next_id(data)
        data.append({"id": new_id, "text": text})
        save_json(ELIST_FILE, data)
        await event.edit(f"✅ Added to default list (ID: {new_id})")
        await event.delete()

    # -------------------------
    # !enemy list add no <text>
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+add\s+no\s+(.+)$"))
    async def enemy_list_add_no(event):
        text = event.pattern_match.group(1).strip()
        data = load_json(ELISTNO_FILE)
        new_id = get_next_id(data)
        data.append({"id": new_id, "text": text})
        save_json(ELISTNO_FILE, data)
        await event.edit(f"✅ Added to no list (ID: {new_id})")
        await event.delete()

    # -------------------------
    # !enemy list del <id> (default list)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+del\s+(\d+)$"))
    async def enemy_list_del(event):
        del_id = int(event.pattern_match.group(1))
        data = load_json(ELIST_FILE)
        new_data = [item for item in data if item["id"] != del_id]
        if len(new_data) == len(data):
            await event.edit(f"❌ ID {del_id} not found in default list.")
            return
        save_json(ELIST_FILE, new_data)
        await event.edit(f"✅ Deleted line with ID {del_id} from default list.")
        await event.delete()

    # -------------------------
    # !enemy list del no <id> (no list)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+del\s+no\s+(\d+)$"))
    async def enemy_list_del_no(event):
        del_id = int(event.pattern_match.group(1))
        data = load_json(ELISTNO_FILE)
        new_data = [item for item in data if item["id"] != del_id]
        if len(new_data) == len(data):
            await event.edit(f"❌ ID {del_id} not found in no list.")
            return
        save_json(ELISTNO_FILE, new_data)
        await event.edit(f"✅ Deleted line with ID {del_id} from no list.")
        await event.delete()

    # -------------------------
    # !enemy clist (add replied text to default list)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+clist$"))
    async def enemy_clist(event):
        if not event.is_reply:
            await event.edit("❌ Reply to a message to add its text to the default list.")
            return
        reply = await event.get_reply_message()
        text = reply.text
        if not text:
            await event.edit("❌ The replied message has no text.")
            return
        data = load_json(ELIST_FILE)
        new_id = get_next_id(data)
        data.append({"id": new_id, "text": text})
        save_json(ELIST_FILE, data)
        await event.edit(f"✅ Added to default list (ID: {new_id})")
        await asyncio.sleep(3)
        await event.delete()

    # -------------------------
    # !enemy clist no (add replied text to no list)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+clist\s+no$"))
    async def enemy_clist_no(event):
        if not event.is_reply:
            await event.edit("❌ Reply to a message to add its text to the no list.")
            return
        reply = await event.get_reply_message()
        text = reply.text
        if not text:
            await event.edit("❌ The replied message has no text.")
            return
        data = load_json(ELISTNO_FILE)
        new_id = get_next_id(data)
        data.append({"id": new_id, "text": text})
        save_json(ELISTNO_FILE, data)
        await event.edit(f"✅ Added to no list (ID: {new_id})")
        await asyncio.sleep(3)
        await event.delete()

    # -------------------------
    # !enemy clist show (show default list)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+clist\s+show$"))
    async def enemy_clist_show(event):
        data = load_json(ELIST_FILE)
        if not data:
            await event.edit("📭 Default list is empty.")
            return
        lines = [f"{item['id']}: {item['text']}" for item in data]
        msg = "📋 **Default List (clist):**\n" + "\n".join(lines)
        if len(msg) > 4000:
            import io
            bio = io.BytesIO(msg.encode("utf-8"))
            bio.name = "default_list.txt"
            await client.send_file(event.chat_id, bio, caption="Default list (too long for message)")
            await event.delete()
        else:
            await event.edit(msg)

    # -------------------------
    # !enemy clist no show (show no list)
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+clist\s+no\s+show$"))
    async def enemy_clist_no_show(event):
        data = load_json(ELISTNO_FILE)
        if not data:
            await event.edit("📭 No list is empty.")
            return
        lines = [f"{item['id']}: {item['text']}" for item in data]
        msg = "📋 **No List (clist no):**\n" + "\n".join(lines)
        if len(msg) > 4000:
            import io
            bio = io.BytesIO(msg.encode("utf-8"))
            bio.name = "no_list.txt"
            await client.send_file(event.chat_id, bio, caption="No list (too long for message)")
            await event.delete()
        else:
            await event.edit(msg)

    # -------------------------
    # Catch‑all for wrong usage
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy(?:\s+help)?$"))
    async def enemy_help(event):
        await event.edit(
            "📖 **Enemy Command Help**\n"
            "• `!enemy add` (reply) – add as default\n"
            "• `!enemy add no` (reply) – add as no\n"
            "• `!enemy del` (reply or ID) – remove enemy\n"
            "• `!enemy rep <text>` (reply to user) – set custom text (auto‑adds)\n"
            "• `!enemy list` – show enemies in this chat\n"
            "• `!enemy list show` – show all enemies globally\n"
            "• `!enemy list del` – delete all enemies in this chat\n"
            "• `!enemy list texts` – show default text list\n"
            "• `!enemy list texts no` – show no text list\n"
            "• `!enemy list add <text>` – add to default list\n"
            "• `!enemy list add no <text>` – add to no list\n"
            "• `!enemy list del <id>` – delete from default list\n"
            "• `!enemy list del no <id>` – delete from no list\n"
            "• `!enemy clist` (reply) – add replied text to default list\n"
            "• `!enemy clist no` (reply) – add replied text to no list\n"
            "• `!enemy clist show` – show default list\n"
            "• `!enemy clist no show` – show no list"
        )