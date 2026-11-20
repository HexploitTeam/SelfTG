"""!menres: auto-reply when the owner's account is mentioned."""
from telethon import events
import os

from Com.core.storage import ensure_json_file, load_json, save_json

__HELP__ = ("!menres on/off → Enable or disable mention auto-response\n"
            "!menres set <text> → Set the response text for mentions")
__CATEGORY__ = "Utilities"
MODE_FILE = "mode/menres.json"
os.makedirs("mode", exist_ok=True)

DEFAULT_CONFIG = {"enabled": False, "text": ""}
ensure_json_file(MODE_FILE, DEFAULT_CONFIG)


def setup(client, my_id):

    def load_config():
        config = load_json(MODE_FILE, dict(DEFAULT_CONFIG))
        return config if isinstance(config, dict) else dict(DEFAULT_CONFIG)

    def save_config(cfg):
        save_json(MODE_FILE, cfg)

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
