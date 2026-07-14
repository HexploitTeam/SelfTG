# Com/menres.py
from telethon import events
import os
import json

__HELP__ = ("!menres on/off → Enable or disable mention auto-response\n"
            "!menres set <text> → Set the response text for mentions")
__CATEGORY__ = "Utilities"
MODE_FILE = "mode/menres.json"
os.makedirs("mode", exist_ok=True)

if not os.path.exists(MODE_FILE):
    with open(MODE_FILE, "w", encoding="utf-8") as f:
        json.dump({"enabled": False, "text": ""}, f, indent=2)


def setup(client, my_id):

    def load_config():
        with open(MODE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_config(cfg):
        with open(MODE_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!menres\s+(on|off)$"))
    async def toggle_menres(event):
        cfg = load_config()
        state = event.pattern_match.group(1).lower()
        cfg["enabled"] = state == "on"
        save_config(cfg)
        await event.edit(
            f"✅ Mention Response {'enabled' if cfg['enabled'] else 'disabled'}."
        )

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!menres\s+set\s+(.+)$"))
    async def set_text(event):
        cfg = load_config()
        text = event.pattern_match.group(1).strip()
        cfg["text"] = text
        save_config(cfg)
        await event.edit(f"✅ Mention response text set to:\n{text}")

    @client.on(events.NewMessage())
    async def mention_response(event):
        cfg = load_config()
        if not cfg["enabled"] or not cfg["text"]:
            return

        # event.message.mentioned is True if your account was mentioned
        if getattr(event.message, "mentioned", False):
            await event.reply(cfg["text"])
