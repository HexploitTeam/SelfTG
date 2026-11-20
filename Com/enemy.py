"""!enemy: the auto-reply target list, its message pools and round-robin selection."""
import os
import json
import re
from telethon import events
import Com.core.tgsend as tgsend

from Com.core.storage import cached_json as _storage_cached
from Com.core.storage import save_json as _storage_save

#------------------------------
#Scary messages
#------------------------------

SCARY_MESSAGES = [
    "☠️ Bot is ready. Kill 'em all. No mercy, no survivors.",
    "🔫 Locked and loaded. Every single one of them is a target. Who’s first?",
    "🎯 Target acquired. Eliminate with extreme prejudice. No witnesses.",
    "💀 Execute order 66. The time has come to purge the unworthy.",
    "🌙 The hunt begins at midnight. They won’t see it coming.",
    "⚔️ We ride at dawn. Blood will be spilled. Legends will be born.",
    "🔥 No survivors. Burn everything to the ground. Let the ashes tell the tale.",
    "😈 This is where the fun begins. Let the games of death commence.",
    "👊 I'm about to end this man's whole career. Permanently.",
    "🪓 Rip and tear. Until it is done. No one is safe.",
    "😎 Let's get dangerous. They made a grave mistake crossing us.",
    "🦅 The predator is here. Stalking. Hunting. Killing. Just another day.",
    "🚨 It's about to get real. Panic won't save them. Nothing will.",
    "🧨 Say your prayers. The reaper is knocking and I'm holding the door.",
    "💣 Tick tock... Time’s running out. Make peace with your gods.",
    "👿 Rise and shine, it's judgment day. The scales are tipping.",
    "🏴‍☠️ Dead men tell no tales. Neither will they.",
    "🩸 Blood will flow like rivers. The ground will drink deeply.",
    "🧛 The night is dark and full of terrors. I am one of them.",
    "👾 System override. Autopilot engaged. Termination sequence started.",
    "🤖 Engage kill mode. All systems green. No mercy protocol active.",
    "☢️ Radiation levels critical. Everyone in range is already dead.",
    "🌪️ The storm is coming. I am the eye of destruction.",
    "⚡ Thunder rolls. Lightning strikes. So will I. Again and again.",
    "🌀 Twist of fate. Their luck just ran out. Completely.",
    "🌋 Eruption imminent. The ground will swallow them whole.",
    "🌊 Tsunami warning. They'll be swept away. No trace left.",
    "🪐 Rings of Saturn. Distant and cold. Just like their future.",
    "💥 Explosive impact. Nothing remains. Just dust and regret.",
    "🧠 Mind games. Psychological warfare. They'll break before they fall.",
    "👁️ I see everything. Every move, every fear. It's already over.",
    "🗡️ The blade is sharp. One cut is all it takes. I'll make it count.",
    "🏹 Arrow aimed. Perfect trajectory. Bullseye every time.",
    "🔪 Slice and dice. They won't even feel it. Just a whisper.",
    "🪚 Chain reaction. One falls, the rest follow. Inevitable.",
    "⛓️ Bound by fear. They can't escape. Their fate is sealed.",
    "🧨 Fuse lit. Boom. They'll never know what hit them.",
    "🚀 Liftoff. Straight to hell. No return ticket.",
    "🛸 Abduction. They'll be gone before they can scream.",
    "👻 Ghost protocol. Invisible. Untouchable. Unstoppable.",
    "💀 Skull and crossbones. Pirate code. Kill or be killed.",
    "🖤 Darkness falls. I am the shadow that hunts.",
    "🌑 Eclipse. Total blackout. They'll be blind. I'll be deadly.",
    "🔦 Spotlight. They can't hide. I see every corner.",
    "🚪 Door slam. Their last chance just closed. Locked in.",
    "🪑 Seat's taken. They can't run. Nowhere to go.",
    "🛏️ Nightmare fuel. They'll never sleep again. Ever.",
    "📦 Boxed in. No escape. Just me and them.",
    "📦 Pandora's box. They opened it. Now they pay.",
    "🔮 Crystal ball. I see their death. Clear as day.",
    "🧿 Evil eye. Cursed. They’ll never be the same.",
    "🎭 Mask on. The show is about to start. They're the main event.",
]

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
    "!enemy clist no show → Show no list with IDs\n"
    "!enemy load → Scare them with a random gangster message"
)
__CATEGORY__ = "Utilities"

#------------------------------
#File paths
#------------------------------

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

#------------------------------
#Helpers
#------------------------------

def load_json(fpath):
    # The auto-reply handler asks for this on every incoming message, so it reads
    # through the shared mtime-validated cache instead of parsing the file per
    # event (Com/core/storage.py).
    return _storage_cached(fpath, {})

def save_json(fpath, data):
    _storage_save(fpath, data)

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

async def get_username(client, user_id):
    # Was a synchronous call to client.loop.run_until_complete() from inside the
    # running event loop, which always raised, so listings showed bare IDs.
    try:
        user = await client.get_entity(user_id)
        return f"@{user.username}" if user.username else f"ID:{user_id}"
    except Exception:
        return f"ID:{user_id}"

#------------------------------
#Round-robin state
#------------------------------

def load_state():
    # Same reasoning as load_json(): this is on the per-message path.
    return _storage_cached(STATE_FILE, {})

def save_state(state):
    _storage_save(STATE_FILE, state)

def get_next_index(chat_id, category):
    """Return the current index and increment it for next time."""
    state = load_state()
    chat_key = str(chat_id)
    if chat_key not in state:
        state[chat_key] = {"default": 0, "no": 0}
    idx = state[chat_key].get(category, 0)
    return idx

def save_next_index(chat_id, category, new_idx):
    state = load_state()
    chat_key = str(chat_id)
    if chat_key not in state:
        state[chat_key] = {"default": 0, "no": 0}
    state[chat_key][category] = new_idx
    save_state(state)

#------------------------------
#Setup
#------------------------------

def setup(client, my_id):

    # Auto-reply handler
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
                # Round-robin selection
                idx = get_next_index(chat_id, category)
                reply_text = lines[idx]["text"]
                new_idx = (idx + 1) % len(lines)
                save_next_index(chat_id, category, new_idx)

        await event.reply(reply_text)

    # !enemy add (default)
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

    # !enemy add no
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

    # !enemy del (reply or ID)
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

    # !enemy rep <text> (reply to enemy)
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

    # !enemy list (show enemies in current chat)
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
            name = await get_username(client, uid)
            cat = e.get("category", "default")
            custom = e.get("custom_text")
            custom_str = f" (custom: {custom})" if custom else ""
            lines.append(f"• {name} (ID: {uid}) – category: {cat}{custom_str}")

        msg = "📋 **Enemies in this chat:**\n" + "\n".join(lines)
        await event.edit(msg)

    # !enemy list show (global enemies)
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
                name = await get_username(client, uid)
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
            await client.send_file(await tgsend.peer(event), bio, caption="Global enemy list")
            await event.edit("📄 Too many enemies, sent as file.")
            await event.delete()
        else:
            await event.edit(msg)

    # !enemy list del (delete all enemies in current chat)
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

    # !enemy list texts (show default list)
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+texts$"))
    async def enemy_list_texts(event):
        data = load_json(ELIST_FILE)
        if not data:
            await event.edit("📭 Default list is empty.")
            return
        lines = [f"{item['id']}: {item['text']}" for item in data]
        msg = "📋 **Default List:**\n" + "\n".join(lines)
        await event.edit(msg)

    # !enemy list texts no (show no list)
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+texts\s+no$"))
    async def enemy_list_texts_no(event):
        data = load_json(ELISTNO_FILE)
        if not data:
            await event.edit("📭 No list is empty.")
            return
        lines = [f"{item['id']}: {item['text']}" for item in data]
        msg = "📋 **No List:**\n" + "\n".join(lines)
        await event.edit(msg)

    # !enemy list add <text>
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+add\s+(.+)$"))
    async def enemy_list_add(event):
        text = event.pattern_match.group(1).strip()
        data = load_json(ELIST_FILE)
        new_id = get_next_id(data)
        data.append({"id": new_id, "text": text})
        save_json(ELIST_FILE, data)
        await event.edit(f"✅ Added to default list (ID: {new_id})")
        await event.delete()

    # !enemy list add no <text>
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+add\s+no\s+(.+)$"))
    async def enemy_list_add_no(event):
        text = event.pattern_match.group(1).strip()
        data = load_json(ELISTNO_FILE)
        new_id = get_next_id(data)
        data.append({"id": new_id, "text": text})
        save_json(ELISTNO_FILE, data)
        await event.edit(f"✅ Added to no list (ID: {new_id})")
        await event.delete()

    # !enemy list del <id> (default list)
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

    # !enemy list del no <id> (no list)
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

    # !enemy clist (add replied text to default list)
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
        await event.delete()

    # !enemy clist no (add replied text to no list)
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
        await event.delete()

    # !enemy clist show (show default list)
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
            await client.send_file(await tgsend.peer(event), bio, caption="Default list (too long for message)")
            await event.delete()
        else:
            await event.edit(msg)

    # !enemy clist no show (show no list)
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
            await client.send_file(await tgsend.peer(event), bio, caption="No list (too long for message)")
            await event.delete()
        else:
            await event.edit(msg)

    # !enemy load (scary gangster message)
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy load$"))
    async def enemy_load(event):
        import random
        msg = random.choice(SCARY_MESSAGES)
        await event.edit(msg)

    # Catch-all for wrong usage
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
            "• `!enemy clist no show` – show no list\n"
            "• `!enemy load` – scare them with a random gangster message"
        )