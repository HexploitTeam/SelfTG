# Com/monitor.py
import os
import json
import re
from telethon import events

__HELP__ = (
    "!monitor add <keyword> → Add keyword to watch (in current chat or global)\n"
    "!monitor remove <keyword> → Remove keyword\n"
    "!monitor list → List all keywords in the current scope\n"
    "!monitor global → Toggle global watching (across all chats)\n"
    "!monitor reply <text> → Set reply text (send in chat on match; use 'off' to disable)\n"
    "!monitor regex → Toggle regex mode for the current scope\n"
    "!monitor case → Toggle case sensitivity\n"
    "!monitor silent → Toggle silent mode (no DM alerts, only log to file)"
)
__CATEGORY__ = "Utilities"

DATA_FILE = "mode/monitor.json"
LOG_FILE = "mode/monitor_log.txt"

os.makedirs("mode", exist_ok=True)

# Default structure
DEFAULT_SCOPE = {
    "keywords": [],
    "reply_text": None,       # None = no reply, else string
    "case_sensitive": False,
    "regex": False,
    "silent": False
}

DEFAULT_DATA = {
    "__global": DEFAULT_SCOPE.copy(),
    "__settings": {"global_enabled": False}
}

def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Ensure keys exist
        if "__global" not in data:
            data["__global"] = DEFAULT_SCOPE.copy()
        if "__settings" not in data:
            data["__settings"] = {"global_enabled": False}
        return data
    except:
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_scope(data, chat_id):
    """Return the scope dict for the chat or global if global_enabled."""
    if data["__settings"].get("global_enabled", False):
        return data["__global"]
    chat_id_str = str(chat_id)
    if chat_id_str not in data:
        data[chat_id_str] = DEFAULT_SCOPE.copy()
    return data[chat_id_str]

def log_match(chat_id, user_id, keyword, text):
    """Log a match to a file (always, regardless of silent)."""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{chat_id}] User {user_id} matched '{keyword}': {text}\n")

def setup(client, my_id):

    # -------------------------
    # Keyword matching handler
    # -------------------------
    @client.on(events.NewMessage)
    async def monitor_handler(event):
        # Ignore self messages
        if event.sender_id == my_id:
            return
        text = event.raw_text or ""
        if not text:
            return

        data = load_data()
        chat_id_str = str(event.chat_id)
        global_enabled = data["__settings"].get("global_enabled", False)

        # Collect all keywords to check (global + per-chat)
        all_keywords = []
        matched_keyword = None
        scope_reply = None
        scope_silent = False

        # Check per-chat scope
        if chat_id_str in data:
            scope = data[chat_id_str]
            all_keywords.extend(scope.get("keywords", []))
            if scope.get("reply_text"):
                scope_reply = scope["reply_text"]
            if scope.get("silent"):
                scope_silent = True

        # Check global scope if enabled
        if global_enabled:
            gscope = data["__global"]
            all_keywords.extend(gscope.get("keywords", []))
            if gscope.get("reply_text") and not scope_reply:  # per-chat overrides
                scope_reply = gscope["reply_text"]
            if gscope.get("silent"):
                scope_silent = True

        if not all_keywords:
            return

        # Determine match mode (per-chat overrides global)
        # We'll check both but we can simply use per-chat or global flags
        # We'll assume if per-chat has regex/case, use that; else global settings.
        # For simplicity, we'll check per-chat first, then global if not set.
        case_sensitive = False
        regex_mode = False
        if chat_id_str in data:
            case_sensitive = data[chat_id_str].get("case_sensitive", False)
            regex_mode = data[chat_id_str].get("regex", False)
        elif global_enabled:
            case_sensitive = data["__global"].get("case_sensitive", False)
            regex_mode = data["__global"].get("regex", False)

        # Check each keyword
        for kw in all_keywords:
            if regex_mode:
                flags = 0 if case_sensitive else re.IGNORECASE
                try:
                    if re.search(kw, text, flags):
                        matched_keyword = kw
                        break
                except:
                    continue
            else:
                compare_text = text if case_sensitive else text.lower()
                compare_kw = kw if case_sensitive else kw.lower()
                if compare_kw in compare_text:
                    matched_keyword = kw
                    break

        if not matched_keyword:
            return

        # Log always (unless silent? No, we log always for audit)
        log_match(event.chat_id, event.sender_id, matched_keyword, text)

        # Send DM alert unless silent
        if not scope_silent:
            try:
                chat_name = getattr(event.chat, "title", "Private")
                user = await event.get_sender()
                user_name = getattr(user, "first_name", "Unknown")
                await client.send_message(
                    my_id,
                    f"⚡ Keyword alert!\n"
                    f"Chat: {chat_name}\n"
                    f"User: {user_name}\n"
                    f"Keyword: '{matched_keyword}'\n"
                    f"Message: {text}"
                )
            except Exception as e:
                print(f"[monitor] Failed to send DM: {e}")

        # Send reply in chat if reply_text is set
        if scope_reply:
            try:
                await event.reply(scope_reply)
            except Exception as e:
                print(f"[monitor] Failed to send reply: {e}")

    # -------------------------
    # !monitor add <keyword>
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!monitor add (.+)"))
    async def monitor_add(event):
        keyword = event.pattern_match.group(1).strip()
        data = load_data()
        scope = get_scope(data, event.chat_id)
        if keyword in scope["keywords"]:
            await event.reply(f"⚠️ Keyword '{keyword}' already in the watchlist.")
            return
        scope["keywords"].append(keyword)
        save_data(data)
        await event.reply(f"✅ Added '{keyword}' to watchlist.")

    # -------------------------
    # !monitor remove <keyword>
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!monitor remove (.+)"))
    async def monitor_remove(event):
        keyword = event.pattern_match.group(1).strip()
        data = load_data()
        scope = get_scope(data, event.chat_id)
        if keyword not in scope["keywords"]:
            await event.reply(f"⚠️ Keyword '{keyword}' not in the watchlist.")
            return
        scope["keywords"].remove(keyword)
        save_data(data)
        await event.reply(f"✅ Removed '{keyword}' from watchlist.")

    # -------------------------
    # !monitor list
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!monitor list$"))
    async def monitor_list(event):
        data = load_data()
        chat_id_str = str(event.chat_id)
        global_enabled = data["__settings"].get("global_enabled", False)

        msg = "📝 **Watchlist**\n"
        if global_enabled:
            kw = data["__global"].get("keywords", [])
            msg += "🌍 **Global:** " + (", ".join(kw) if kw else "(empty)") + "\n"
        if chat_id_str in data:
            kw = data[chat_id_str].get("keywords", [])
            msg += f"📌 **This chat:** " + (", ".join(kw) if kw else "(empty)") + "\n"
        else:
            msg += "📌 This chat: (empty)\n"

        # Show settings
        scope = get_scope(data, event.chat_id)
        msg += f"🔹 Reply: {scope.get('reply_text') or 'Off'}\n"
        msg += f"🔹 Case sensitive: {'On' if scope.get('case_sensitive') else 'Off'}\n"
        msg += f"🔹 Regex mode: {'On' if scope.get('regex') else 'Off'}\n"
        msg += f"🔹 Silent: {'On' if scope.get('silent') else 'Off'}\n"
        msg += f"🌍 Global mode: {'On' if global_enabled else 'Off'}"

        await event.edit(msg)

    # -------------------------
    # !monitor global
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!monitor global$"))
    async def monitor_global(event):
        data = load_data()
        current = data["__settings"].get("global_enabled", False)
        data["__settings"]["global_enabled"] = not current
        save_data(data)
        status = "ON" if not current else "OFF"
        await event.reply(f"🌍 Global watch mode: {status}")

    # -------------------------
    # !monitor reply <text> or off
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!monitor reply (.+)"))
    async def monitor_reply(event):
        text = event.pattern_match.group(1).strip()
        data = load_data()
        scope = get_scope(data, event.chat_id)
        if text.lower() == "off":
            scope["reply_text"] = None
            await event.reply("✅ Reply text disabled.")
        else:
            scope["reply_text"] = text
            await event.reply(f"✅ Reply text set to: {text}")
        save_data(data)

    # -------------------------
    # !monitor regex
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!monitor regex$"))
    async def monitor_regex(event):
        data = load_data()
        scope = get_scope(data, event.chat_id)
        scope["regex"] = not scope.get("regex", False)
        save_data(data)
        status = "ON" if scope["regex"] else "OFF"
        await event.reply(f"🔍 Regex mode: {status}")

    # -------------------------
    # !monitor case
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!monitor case$"))
    async def monitor_case(event):
        data = load_data()
        scope = get_scope(data, event.chat_id)
        scope["case_sensitive"] = not scope.get("case_sensitive", False)
        save_data(data)
        status = "ON" if scope["case_sensitive"] else "OFF"
        await event.reply(f"🔤 Case sensitivity: {status}")

    # -------------------------
    # !monitor silent
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!monitor silent$"))
    async def monitor_silent(event):
        data = load_data()
        scope = get_scope(data, event.chat_id)
        scope["silent"] = not scope.get("silent", False)
        save_data(data)
        status = "ON" if scope["silent"] else "OFF"
        await event.reply(f"🔇 Silent mode: {status}")

    # -------------------------
    # Fallback help
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!monitor$"))
    async def monitor_help(event):
        await event.edit(
            "📖 **Monitor Commands**\n"
            "• `!monitor add <keyword>`\n"
            "• `!monitor remove <keyword>`\n"
            "• `!monitor list`\n"
            "• `!monitor global` – toggle global watch\n"
            "• `!monitor reply <text|off>`\n"
            "• `!monitor regex` – toggle regex\n"
            "• `!monitor case` – toggle case sensitivity\n"
            "• `!monitor silent` – toggle silent mode"
        )