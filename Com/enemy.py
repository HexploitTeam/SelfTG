"""!enemy: the auto-reply target list, its message pools and round-robin selection."""
import os
import re
from telethon import events
import Com.core.tgsend as tgsend

from Com.core import brand
from Com.core.reply import say
from Com.core.storage import cached_json as _storage_cached
from Com.core.storage import ensure_json_file
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

# Atomic first-run creation
ensure_json_file(ENEMY_FILE, {})
for fpath in [ELIST_FILE, ELISTNO_FILE]:
    ensure_json_file(fpath, [])
ensure_json_file(STATE_FILE, {})

#------------------------------
#Helpers
#------------------------------

def load_json(fpath):
    # Per-message path: cached read (Com/core/storage.py)
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
    try:
        user = await client.get_entity(user_id)
        return f"@{user.username}" if user.username else f"ID:{user_id}"
    except Exception:
        return f"ID:{user_id}"

#------------------------------
#Round-robin state
#------------------------------

def load_state():
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
        # Skip own, command and empty messages
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

            # Normalise shape
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
            await say(event, "❌ Reply to a user to add them as enemy.", name="enemy")
            return
        reply = await event.get_reply_message()
        user_id = reply.sender_id
        chat_id = event.chat_id

        if find_enemy_by_user_id(chat_id, user_id):
            await say(
                event,
                "❌ <b>This user is already an enemy.</b> Delete and re‑add if "
                "you want to change category.",
                name="enemy",
                parse_mode="html",
            )
            return

        enemies = get_enemy_data(chat_id)
        enemies.append({"user_id": user_id, "category": "default", "custom_text": None})
        save_enemy_data(chat_id, enemies)
        await say(
            event,
            "✅ <b>Added enemy</b> · <code>default</code> category.",
            name="enemy",
            parse_mode="html",
        )
        await event.delete()

    # !enemy add no
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+add\s+no$"))
    async def enemy_add_no(event):
        if not event.is_reply:
            await say(event, "❌ Reply to a user to add them as enemy.", name="enemy")
            return
        reply = await event.get_reply_message()
        user_id = reply.sender_id
        chat_id = event.chat_id

        if find_enemy_by_user_id(chat_id, user_id):
            await say(
                event,
                "❌ <b>This user is already an enemy.</b> Delete and re‑add if "
                "you want to change category.",
                name="enemy",
                parse_mode="html",
            )
            return

        enemies = get_enemy_data(chat_id)
        enemies.append({"user_id": user_id, "category": "no", "custom_text": None})
        save_enemy_data(chat_id, enemies)
        await say(
            event,
            "✅ <b>Added enemy</b> · <code>no</code> category.",
            name="enemy",
            parse_mode="html",
        )
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+del(?:\s+(\d+))?$"))
    async def enemy_del(event):
        chat_id = event.chat_id
        user_id = None

        match = event.pattern_match.group(1)
        if match:
            user_id = int(match)
        elif event.is_reply:
            reply = await event.get_reply_message()
            user_id = reply.sender_id

        if not user_id:
            await say(event, "❌ Reply to an enemy or provide a user ID.", name="enemy")
            return

        enemy = find_enemy_by_user_id(chat_id, user_id)
        if not enemy:
            await say(event, "❌ This user is not an enemy in this chat.", name="enemy")
            return

        enemies = get_enemy_data(chat_id)
        enemies = [e for e in enemies if e["user_id"] != user_id]
        save_enemy_data(chat_id, enemies)
        await say(event, "✅ <b>Enemy removed.</b>", name="enemy", parse_mode="html")
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+rep\s+(.+)$"))
    async def enemy_rep(event):
        if not event.is_reply:
            await say(
                event,
                "❌ Reply to a user to set custom text (they will be added as "
                "enemy if not already).",
                name="enemy",
            )
            return
        text = event.pattern_match.group(1).strip()
        reply = await event.get_reply_message()
        user_id = reply.sender_id
        chat_id = event.chat_id

        enemy = find_enemy_by_user_id(chat_id, user_id)
        if not enemy:
            enemies = get_enemy_data(chat_id)
            enemies.append({"user_id": user_id, "category": "default", "custom_text": text})
            save_enemy_data(chat_id, enemies)
            await say(
                event,
                f"✅ <b>User added as enemy</b>\n"
                f"<b>Custom text</b> · {brand.esc(text)}",
                name="enemy",
                parse_mode="html",
            )
            await event.delete()
            return

        enemies = get_enemy_data(chat_id)
        for e in enemies:
            if e["user_id"] == user_id:
                e["custom_text"] = text
                break
        save_enemy_data(chat_id, enemies)
        await say(
            event,
            f"✅ <b>Custom reply text updated</b>\n"
            f"<b>Text</b> · {brand.esc(text)}",
            name="enemy",
            parse_mode="html",
        )
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list$"))
    async def enemy_list(event):
        chat_id = event.chat_id
        enemies = get_enemy_data(chat_id)
        if not enemies:
            await say(event, "❌ No enemies in this chat.", name="enemy")
            return

        lines = []
        for e in enemies:
            uid = e["user_id"]
            name = await get_username(client, uid)
            cat = e.get("category", "default")
            custom = e.get("custom_text")
            custom_str = f"\n  custom · {brand.esc(custom)}" if custom else ""
            lines.append(
                f"• <b>{brand.esc(name)}</b> (<code>{uid}</code>) · "
                f"category <code>{brand.esc(cat)}</code>{custom_str}"
            )

        msg = "📋 <b>Enemies in this chat</b>\n" + "\n".join(lines)
        await say(event, msg, name="enemy", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+show$"))
    async def enemy_list_show_global(event):
        all_data = load_json(ENEMY_FILE)
        if not isinstance(all_data, dict):
            all_data = {}
            save_json(ENEMY_FILE, all_data)
        if not all_data:
            await say(event, "📭 No enemies anywhere.", name="enemy")
            return

        lines = []
        for chat_id_str, enemies in all_data.items():
            if not enemies:
                continue
            try:
                chat = await client.get_entity(int(chat_id_str))
                chat_name = chat.title or chat.first_name or chat_id_str
            except:
                chat_name = chat_id_str
            lines.append(
                f"<b>Chat</b> · {brand.esc(chat_name)} "
                f"(<code>{chat_id_str}</code>)"
            )
            for e in enemies:
                uid = e["user_id"]
                name = await get_username(client, uid)
                cat = e.get("category", "default")
                custom = e.get("custom_text")
                custom_str = f"\n    custom · {brand.esc(custom)}" if custom else ""
                lines.append(
                    f"  • <b>{brand.esc(name)}</b> (<code>{uid}</code>) · "
                    f"<code>{brand.esc(cat)}</code>{custom_str}"
                )
            lines.append("")

        msg = "🌍 <b>All Enemies</b> (global)\n" + "\n".join(lines)
        if len(msg) > 4000:
            import io
            bio = io.BytesIO(brand.plain(msg).encode("utf-8"))
            bio.name = "enemies_global.txt"
            await client.send_file(
                await tgsend.peer(event),
                bio,
                caption=brand.sign("🌍 <b>Global enemy list</b>", "enemy"),
                parse_mode="html",
            )
            await say(
                event, "📄 <b>Too many enemies</b>, sent as file.", name="enemy",
                parse_mode="html",
            )
            await event.delete()
        else:
            await say(event, msg, name="enemy", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+del$"))
    async def enemy_list_del_all(event):
        chat_id = event.chat_id
        enemies = get_enemy_data(chat_id)
        if not enemies:
            await say(event, "❌ No enemies in this chat to delete.", name="enemy")
            return
        save_enemy_data(chat_id, [])
        await say(
            event,
            "✅ <b>All enemies in this chat have been removed.</b>",
            name="enemy",
            parse_mode="html",
        )
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+texts$"))
    async def enemy_list_texts(event):
        data = load_json(ELIST_FILE)
        if not data:
            await say(event, "📭 Default list is empty.", name="enemy")
            return
        lines = [
            f"<code>{item['id']}</code> · {brand.esc(item['text'])}" for item in data
        ]
        msg = "📋 <b>Default list</b>\n" + "\n".join(lines)
        await say(event, msg, name="enemy", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+texts\s+no$"))
    async def enemy_list_texts_no(event):
        data = load_json(ELISTNO_FILE)
        if not data:
            await say(event, "📭 No list is empty.", name="enemy")
            return
        lines = [
            f"<code>{item['id']}</code> · {brand.esc(item['text'])}" for item in data
        ]
        msg = "📋 <b>No list</b>\n" + "\n".join(lines)
        await say(event, msg, name="enemy", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+add\s+(.+)$"))
    async def enemy_list_add(event):
        text = event.pattern_match.group(1).strip()
        data = load_json(ELIST_FILE)
        new_id = get_next_id(data)
        data.append({"id": new_id, "text": text})
        save_json(ELIST_FILE, data)
        await say(
            event,
            f"✅ <b>Added to default list</b> · ID <code>{new_id}</code>",
            name="enemy",
            parse_mode="html",
        )
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+add\s+no\s+(.+)$"))
    async def enemy_list_add_no(event):
        text = event.pattern_match.group(1).strip()
        data = load_json(ELISTNO_FILE)
        new_id = get_next_id(data)
        data.append({"id": new_id, "text": text})
        save_json(ELISTNO_FILE, data)
        await say(
            event,
            f"✅ <b>Added to no list</b> · ID <code>{new_id}</code>",
            name="enemy",
            parse_mode="html",
        )
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+del\s+(\d+)$"))
    async def enemy_list_del(event):
        del_id = int(event.pattern_match.group(1))
        data = load_json(ELIST_FILE)
        new_data = [item for item in data if item["id"] != del_id]
        if len(new_data) == len(data):
            await say(
                event,
                f"❌ <b>ID {del_id} not found</b> in the default list.",
                name="enemy",
                parse_mode="html",
            )
            return
        save_json(ELIST_FILE, new_data)
        await say(
            event,
            f"✅ <b>Deleted line</b> <code>{del_id}</code> from the default list.",
            name="enemy",
            parse_mode="html",
        )
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+list\s+del\s+no\s+(\d+)$"))
    async def enemy_list_del_no(event):
        del_id = int(event.pattern_match.group(1))
        data = load_json(ELISTNO_FILE)
        new_data = [item for item in data if item["id"] != del_id]
        if len(new_data) == len(data):
            await say(
                event,
                f"❌ <b>ID {del_id} not found</b> in the no list.",
                name="enemy",
                parse_mode="html",
            )
            return
        save_json(ELISTNO_FILE, new_data)
        await say(
            event,
            f"✅ <b>Deleted line</b> <code>{del_id}</code> from the no list.",
            name="enemy",
            parse_mode="html",
        )
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+clist$"))
    async def enemy_clist(event):
        if not event.is_reply:
            await say(
                event,
                "❌ Reply to a message to add its text to the default list.",
                name="enemy",
            )
            return
        reply = await event.get_reply_message()
        text = reply.text
        if not text:
            await say(event, "❌ The replied message has no text.", name="enemy")
            return
        data = load_json(ELIST_FILE)
        new_id = get_next_id(data)
        data.append({"id": new_id, "text": text})
        save_json(ELIST_FILE, data)
        await say(
            event,
            f"✅ <b>Added to default list</b> · ID <code>{new_id}</code>",
            name="enemy",
            parse_mode="html",
        )
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+clist\s+no$"))
    async def enemy_clist_no(event):
        if not event.is_reply:
            await say(
                event,
                "❌ Reply to a message to add its text to the no list.",
                name="enemy",
            )
            return
        reply = await event.get_reply_message()
        text = reply.text
        if not text:
            await say(event, "❌ The replied message has no text.", name="enemy")
            return
        data = load_json(ELISTNO_FILE)
        new_id = get_next_id(data)
        data.append({"id": new_id, "text": text})
        save_json(ELISTNO_FILE, data)
        await say(
            event,
            f"✅ <b>Added to no list</b> · ID <code>{new_id}</code>",
            name="enemy",
            parse_mode="html",
        )
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+clist\s+show$"))
    async def enemy_clist_show(event):
        data = load_json(ELIST_FILE)
        if not data:
            await say(event, "📭 Default list is empty.", name="enemy")
            return
        lines = [
            f"<code>{item['id']}</code> · {brand.esc(item['text'])}" for item in data
        ]
        msg = "📋 <b>Default list</b> (clist)\n" + "\n".join(lines)
        if len(msg) > 4000:
            import io
            bio = io.BytesIO(brand.plain(msg).encode("utf-8"))
            bio.name = "default_list.txt"
            await client.send_file(
                await tgsend.peer(event),
                bio,
                caption=brand.sign(
                    "📋 <b>Default list</b> (too long for a message)", "enemy"
                ),
                parse_mode="html",
            )
            await event.delete()
        else:
            await say(event, msg, name="enemy", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy\s+clist\s+no\s+show$"))
    async def enemy_clist_no_show(event):
        data = load_json(ELISTNO_FILE)
        if not data:
            await say(event, "📭 No list is empty.", name="enemy")
            return
        lines = [
            f"<code>{item['id']}</code> · {brand.esc(item['text'])}" for item in data
        ]
        msg = "📋 <b>No list</b> (clist no)\n" + "\n".join(lines)
        if len(msg) > 4000:
            import io
            bio = io.BytesIO(brand.plain(msg).encode("utf-8"))
            bio.name = "no_list.txt"
            await client.send_file(
                await tgsend.peer(event),
                bio,
                caption=brand.sign(
                    "📋 <b>No list</b> (too long for a message)", "enemy"
                ),
                parse_mode="html",
            )
            await event.delete()
        else:
            await say(event, msg, name="enemy", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy load$"))
    async def enemy_load(event):
        import random
        msg = random.choice(SCARY_MESSAGES)
        await say(event, msg, name="enemy")

    # Catch-all for wrong usage
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!enemy(?:\s+help)?$"))
    async def enemy_help(event):
        await say(
            event,
            "📖 <b>Enemy Commands</b>\n"
            "• <code>!enemy add</code> (reply) – add as default\n"
            "• <code>!enemy add no</code> (reply) – add as no\n"
            "• <code>!enemy del</code> (reply or ID) – remove enemy\n"
            "• <code>!enemy rep &lt;text&gt;</code> (reply to user) – set custom "
            "text (auto‑adds)\n"
            "• <code>!enemy list</code> – show enemies in this chat\n"
            "• <code>!enemy list show</code> – show all enemies globally\n"
            "• <code>!enemy list del</code> – delete all enemies in this chat\n"
            "• <code>!enemy list texts</code> – show default text list\n"
            "• <code>!enemy list texts no</code> – show no text list\n"
            "• <code>!enemy list add &lt;text&gt;</code> – add to default list\n"
            "• <code>!enemy list add no &lt;text&gt;</code> – add to no list\n"
            "• <code>!enemy list del &lt;id&gt;</code> – delete from default list\n"
            "• <code>!enemy list del no &lt;id&gt;</code> – delete from no list\n"
            "• <code>!enemy clist</code> (reply) – add replied text to default "
            "list\n"
            "• <code>!enemy clist no</code> (reply) – add replied text to no list\n"
            "• <code>!enemy clist show</code> – show default list\n"
            "• <code>!enemy clist no show</code> – show no list\n"
            "• <code>!enemy load</code> – scare them with a random gangster "
            "message",
            name="enemy",
            parse_mode="html",
        )