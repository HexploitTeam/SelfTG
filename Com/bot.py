# Com/bot.py
import os
import json
import asyncio
from telethon import TelegramClient, events
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback, KeyboardButtonRow

from Com.storage import load_json as _load_json, save_json as _save_json

# ---------- Global config ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_ENABLED = bool(BOT_TOKEN)  # True if token exists
bot_client = None
OWNER_ID = None

# Shared JSON paths
BASE_DIR = "mode"
ENEMY_FILE = os.path.join(BASE_DIR, "Enemy.json")
# NOTE: these were "Warn.json"/"Mute.json", while Com/warn.py, Com/mute.py and
# dashboard.py have always used the lowercase names. On Linux (Replit) those are
# different files, so the bot's /warns, /mutes, /set_warn and /add_mute commands
# silently operated on state that nothing else could see. Unified to lowercase.
WARN_FILE = os.path.join(BASE_DIR, "warn.json")
MUTE_FILE = os.path.join(BASE_DIR, "mute.json")
ELIST_FILE = os.path.join(BASE_DIR, "EList.json")

LEGACY_STATE_FILES = (
    (os.path.join(BASE_DIR, "Warn.json"), WARN_FILE),
    (os.path.join(BASE_DIR, "Mute.json"), MUTE_FILE),
)

# ---------- Helpers ----------
def load_json(fpath):
    return _load_json(fpath, {})

def save_json(fpath, data):
    _save_json(fpath, data)

def migrate_legacy_state():
    """Copy data from the old CamelCase state files once, without clobbering."""
    for legacy_path, current_path in LEGACY_STATE_FILES:
        if not os.path.exists(legacy_path) or os.path.exists(current_path):
            continue
        legacy_data = _load_json(legacy_path, None)
        if legacy_data is None:
            continue
        save_json(current_path, legacy_data)
        print(f"[BOT] Migrated legacy state {legacy_path} -> {current_path}")

async def send_inline(chat_id, text, buttons=None, reply_to=None):
    """Send a message through the bot client with inline buttons.

    Imported by Com/inline.py (which used to import a function that never
    existed here, so that module silently failed to load). Returns True on
    success so callers can fall back to a plain self-bot message.
    """
    if bot_client is None:
        return False
    try:
        await bot_client.send_message(
            chat_id, text, buttons=buttons or None, reply_to=reply_to
        )
        return True
    except Exception as exc:
        print(f"[BOT] send_inline failed: {exc}")
        return False

def get_bot_status():
    global BOT_ENABLED, bot_client, OWNER_ID
    if not BOT_ENABLED:
        return "❌ Bot disabled (BOT_TOKEN not set)."
    if bot_client is None:
        return "⏳ Bot connecting... (token exists)"
    if not bot_client.is_connected():
        return "⚠️ Bot disconnected."
    return f"✅ Bot running (Owner: {OWNER_ID})"

# ---------- Bot main ----------
async def start_bot(owner_id):
    global bot_client, BOT_ENABLED, OWNER_ID
    if not BOT_ENABLED:
        print("[BOT] BOT_TOKEN not set, bot disabled.")
        return

    OWNER_ID = owner_id
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    migrate_legacy_state()
    bot_client = TelegramClient("bot_session", API_ID, API_HASH)
    await bot_client.start(bot_token=BOT_TOKEN)
    print(f"[BOT] Bot is running. Owner ID: {OWNER_ID}")

    # ---------- Command handlers ----------
    @bot_client.on(events.NewMessage(pattern=r'^/start$'))
    async def start_cmd(event):
        is_owner = (event.sender_id == OWNER_ID)
        if is_owner:
            markup = ReplyInlineMarkup([
                KeyboardButtonRow([KeyboardButtonCallback("📊 Stats", b"stats")]),
                KeyboardButtonRow([KeyboardButtonCallback("👿 Enemies", b"enemies")]),
                KeyboardButtonRow([KeyboardButtonCallback("⚠️ Warns", b"warns")]),
                KeyboardButtonRow([KeyboardButtonCallback("🔇 Mutes", b"mutes")]),
                KeyboardButtonRow([KeyboardButtonCallback("📝 Texts", b"texts")]),
                KeyboardButtonRow([KeyboardButtonCallback("⚙️ Admin Panel", b"admin")]),
            ])
            await event.respond("🤖 **Owner Menu**\nUse the buttons below or /commands.", buttons=markup)
        else:
            markup = ReplyInlineMarkup([
                KeyboardButtonRow([KeyboardButtonCallback("📊 Stats", b"stats")]),
            ])
            await event.respond("🤖 **Shared Bot**\nYou have limited access.", buttons=markup)

    @bot_client.on(events.NewMessage(pattern=r'^/commands$'))
    async def commands_cmd(event):
        is_owner = (event.sender_id == OWNER_ID)
        if is_owner:
            await event.respond(
                "/start – main menu\n"
                "/enemies – list enemies\n"
                "/warns – list warns\n"
                "/mutes – list mutes\n"
                "/texts – list texts\n"
                "/stats – summary stats\n"
                "/admin – admin panel (owner only)"
            )
        else:
            await event.respond("/start – main menu\n/stats – summary stats")

    @bot_client.on(events.NewMessage(pattern=r'^/admin$'))
    async def admin_cmd(event):
        if event.sender_id != OWNER_ID:
            await event.respond("⛔ You are not authorized.")
            return
        markup = ReplyInlineMarkup([
            KeyboardButtonRow([KeyboardButtonCallback("➕ Add Enemy", b"add_enemy")]),
            KeyboardButtonRow([KeyboardButtonCallback("❌ Remove Enemy", b"remove_enemy")]),
            KeyboardButtonRow([KeyboardButtonCallback("📝 Set Warn Limit", b"set_warn")]),
            KeyboardButtonRow([KeyboardButtonCallback("🔇 Add Mute", b"add_mute")]),
            KeyboardButtonRow([KeyboardButtonCallback("🔓 Remove Mute", b"remove_mute")]),
        ])
        await event.respond("⚙️ **Admin Panel**", buttons=markup)

    @bot_client.on(events.NewMessage(pattern=r'^/stats$'))
    async def stats_cmd(event):
        enemies = load_json(ENEMY_FILE)
        warns = load_json(WARN_FILE)
        mutes = load_json(MUTE_FILE)
        texts = load_json(ELIST_FILE)
        msg = (f"📊 **Stats**\n"
               f"Enemies: {sum(len(v) for v in enemies.values())}\n"
               f"Warns: {sum(len(v.get('warnings', {})) for v in warns.values())}\n"
               f"Mutes: {sum(len(v) for v in mutes.values())}\n"
               f"Texts: {len(texts)}")
        await event.respond(msg)

    @bot_client.on(events.NewMessage(pattern=r'^/enemies$'))
    async def enemies_cmd(event):
        if event.sender_id != OWNER_ID:
            await event.respond("⛔ Access denied.")
            return
        enemies = load_json(ENEMY_FILE)
        if not enemies:
            await event.respond("No enemies.")
            return
        lines = []
        for cid, users in enemies.items():
            for u in users:
                lines.append(f"Chat {cid}: User {u['user_id']} (cat: {u.get('category','default')})")
        msg = "\n".join(lines[:10]) + ("..." if len(lines)>10 else "")
        await event.respond(msg or "No enemies.")

    @bot_client.on(events.NewMessage(pattern=r'^/warns$'))
    async def warns_cmd(event):
        if event.sender_id != OWNER_ID:
            await event.respond("⛔ Access denied.")
            return
        warns = load_json(WARN_FILE)
        if not warns:
            await event.respond("No warns.")
            return
        lines = []
        for cid, wdata in warns.items():
            for uid, reasons in wdata.get("warnings", {}).items():
                for r in reasons:
                    lines.append(f"Chat {cid}: User {uid} – {r}")
        msg = "\n".join(lines[:10]) + ("..." if len(lines)>10 else "")
        await event.respond(msg or "No warns.")

    @bot_client.on(events.NewMessage(pattern=r'^/mutes$'))
    async def mutes_cmd(event):
        if event.sender_id != OWNER_ID:
            await event.respond("⛔ Access denied.")
            return
        mutes = load_json(MUTE_FILE)
        if not mutes:
            await event.respond("No mutes.")
            return
        lines = []
        for cid, users in mutes.items():
            for u in users:
                lines.append(f"Chat {cid}: User {u['user_id']} ({u.get('mode','admin')})")
        msg = "\n".join(lines[:10]) + ("..." if len(lines)>10 else "")
        await event.respond(msg or "No mutes.")

    @bot_client.on(events.NewMessage(pattern=r'^/texts$'))
    async def texts_cmd(event):
        if event.sender_id != OWNER_ID:
            await event.respond("⛔ Access denied.")
            return
        texts = load_json(ELIST_FILE)
        if not texts:
            await event.respond("No texts.")
            return
        lines = [f"{t['id']}: {t['text'][:30]}" for t in texts]
        msg = "\n".join(lines[:10]) + ("..." if len(lines)>10 else "")
        await event.respond(msg or "No texts.")

    # ---------- Callback handler ----------
    @bot_client.on(events.CallbackQuery)
    async def callback_handler(event):
        is_owner = (event.sender_id == OWNER_ID)
        data = event.data.decode()

        if data == "stats":
            enemies = load_json(ENEMY_FILE)
            warns = load_json(WARN_FILE)
            mutes = load_json(MUTE_FILE)
            texts = load_json(ELIST_FILE)
            msg = (f"Enemies: {sum(len(v) for v in enemies.values())}\n"
                   f"Warns: {sum(len(v.get('warnings', {})) for v in warns.values())}\n"
                   f"Mutes: {sum(len(v) for v in mutes.values())}\n"
                   f"Texts: {len(texts)}")
            await event.answer(msg, alert=True)
            return

        if not is_owner:
            await event.answer("⛔ Access denied.", alert=True)
            return

        if data == "enemies":
            enemies = load_json(ENEMY_FILE)
            lines = []
            for cid, users in enemies.items():
                for u in users:
                    lines.append(f"Chat {cid}: User {u['user_id']}")
            await event.answer("\n".join(lines[:5]) + ("..." if len(lines)>5 else ""), alert=True)

        elif data == "warns":
            warns = load_json(WARN_FILE)
            lines = []
            for cid, wdata in warns.items():
                for uid, reasons in wdata.get("warnings", {}).items():
                    for r in reasons:
                        lines.append(f"Chat {cid}: User {uid} – {r}")
            await event.answer("\n".join(lines[:5]) + ("..." if len(lines)>5 else ""), alert=True)

        elif data == "mutes":
            mutes = load_json(MUTE_FILE)
            lines = []
            for cid, users in mutes.items():
                for u in users:
                    lines.append(f"Chat {cid}: User {u['user_id']}")
            await event.answer("\n".join(lines[:5]) + ("..." if len(lines)>5 else ""), alert=True)

        elif data == "texts":
            texts = load_json(ELIST_FILE)
            lines = [f"{t['id']}: {t['text'][:20]}" for t in texts]
            await event.answer("\n".join(lines[:5]) + ("..." if len(lines)>5 else ""), alert=True)

        elif data == "admin":
            markup = ReplyInlineMarkup([
                KeyboardButtonRow([KeyboardButtonCallback("➕ Add Enemy", b"add_enemy")]),
                KeyboardButtonRow([KeyboardButtonCallback("❌ Remove Enemy", b"remove_enemy")]),
                KeyboardButtonRow([KeyboardButtonCallback("📝 Set Warn Limit", b"set_warn")]),
                KeyboardButtonRow([KeyboardButtonCallback("🔇 Add Mute", b"add_mute")]),
                KeyboardButtonRow([KeyboardButtonCallback("🔓 Remove Mute", b"remove_mute")]),
            ])
            await event.edit(buttons=markup)
            await event.answer("Admin panel opened.")

        elif data == "add_enemy":
            await event.answer("Use /add_enemy <chat_id> <user_id> [category] [custom_text]", alert=True)
        elif data == "remove_enemy":
            await event.answer("Use /remove_enemy <chat_id> <user_id>", alert=True)
        elif data == "set_warn":
            await event.answer("Use /set_warn <chat_id> <limit>", alert=True)
        elif data == "add_mute":
            await event.answer("Use /add_mute <chat_id> <user_id> [admin|manual]", alert=True)
        elif data == "remove_mute":
            await event.answer("Use /remove_mute <chat_id> <user_id>", alert=True)

    # ---------- Admin commands (owner only) ----------
    @bot_client.on(events.NewMessage(pattern=r'^/add_enemy\s+(\-?\d+)\s+(\d+)(?:\s+(\w+))?(?:\s+(.+))?$'))
    async def add_enemy_cmd(event):
        if event.sender_id != OWNER_ID:
            await event.respond("⛔ Access denied.")
            return
        chat_id = event.pattern_match.group(1)
        user_id = int(event.pattern_match.group(2))
        category = event.pattern_match.group(3) or "default"
        custom_text = event.pattern_match.group(4) or ""
        enemies = load_json(ENEMY_FILE)
        if chat_id not in enemies:
            enemies[chat_id] = []
        if any(u.get('user_id') == user_id for u in enemies[chat_id]):
            await event.respond(f"User {user_id} already in enemy list.")
            return
        enemies[chat_id].append({"user_id": user_id, "category": category, "custom_text": custom_text})
        save_json(ENEMY_FILE, enemies)
        await event.respond(f"✅ Added enemy: Chat {chat_id}, User {user_id}")

    @bot_client.on(events.NewMessage(pattern=r'^/remove_enemy\s+(\-?\d+)\s+(\d+)$'))
    async def remove_enemy_cmd(event):
        if event.sender_id != OWNER_ID:
            await event.respond("⛔ Access denied.")
            return
        chat_id = event.pattern_match.group(1)
        user_id = int(event.pattern_match.group(2))
        enemies = load_json(ENEMY_FILE)
        if chat_id not in enemies:
            await event.respond(f"Chat {chat_id} not found.")
            return
        new_users = [u for u in enemies[chat_id] if u.get('user_id') != user_id]
        if len(new_users) == len(enemies[chat_id]):
            await event.respond(f"User {user_id} not found.")
            return
        enemies[chat_id] = new_users
        save_json(ENEMY_FILE, enemies)
        await event.respond(f"✅ Removed enemy: Chat {chat_id}, User {user_id}")

    @bot_client.on(events.NewMessage(pattern=r'^/set_warn\s+(\-?\d+)\s+(\d+)$'))
    async def set_warn_cmd(event):
        if event.sender_id != OWNER_ID:
            await event.respond("⛔ Access denied.")
            return
        chat_id = event.pattern_match.group(1)
        limit = int(event.pattern_match.group(2))
        warns = load_json(WARN_FILE)
        if chat_id not in warns:
            warns[chat_id] = {"limit": limit, "warnings": {}}
        else:
            warns[chat_id]["limit"] = limit
        save_json(WARN_FILE, warns)
        await event.respond(f"✅ Warn limit for chat {chat_id} set to {limit}")

    @bot_client.on(events.NewMessage(pattern=r'^/add_mute\s+(\-?\d+)\s+(\d+)(?:\s+(\w+))?$'))
    async def add_mute_cmd(event):
        if event.sender_id != OWNER_ID:
            await event.respond("⛔ Access denied.")
            return
        chat_id = event.pattern_match.group(1)
        user_id = int(event.pattern_match.group(2))
        mode = event.pattern_match.group(3) or "admin"
        mutes = load_json(MUTE_FILE)
        if chat_id not in mutes:
            mutes[chat_id] = []
        if any(u.get('user_id') == user_id for u in mutes[chat_id]):
            await event.respond(f"User {user_id} already muted.")
            return
        mutes[chat_id].append({"user_id": user_id, "mode": mode})
        save_json(MUTE_FILE, mutes)
        await event.respond(f"✅ Muted: Chat {chat_id}, User {user_id}")

    @bot_client.on(events.NewMessage(pattern=r'^/remove_mute\s+(\-?\d+)\s+(\d+)$'))
    async def remove_mute_cmd(event):
        if event.sender_id != OWNER_ID:
            await event.respond("⛔ Access denied.")
            return
        chat_id = event.pattern_match.group(1)
        user_id = int(event.pattern_match.group(2))
        mutes = load_json(MUTE_FILE)
        if chat_id not in mutes:
            await event.respond(f"Chat {chat_id} not found.")
            return
        new_users = [u for u in mutes[chat_id] if u.get('user_id') != user_id]
        if len(new_users) == len(mutes[chat_id]):
            await event.respond(f"User {user_id} not found.")
            return
        mutes[chat_id] = new_users
        save_json(MUTE_FILE, mutes)
        await event.respond(f"✅ Unmuted: Chat {chat_id}, User {user_id}")

    # ---------- Keep the bot connected ----------
    await bot_client.run_until_disconnected()