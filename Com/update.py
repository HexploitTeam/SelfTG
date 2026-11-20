"""!update: restart in place and report which commands changed."""
import os
import sys
import hashlib
import asyncio
import logging
from telethon import events
import Com.core.tgsend as tgsend

from Com.core.storage import load_json, save_json

log = logging.getLogger("selftg.update")

__HELP__ = "!update → Restart the session and show command changes after restart"
__CATEGORY__ = "Setup"

#------------------------------
#File paths
#------------------------------

HASH_FILE = "mode/file_hashes.json"
RESTART_FILE = "mode/restart.json"
os.makedirs("mode", exist_ok=True)


def compute_hash(file_path):
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def get_commands_in_file(file_path):
    """Return True if file defines __HELP__."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()
        return "__HELP__" in code
    except OSError:
        return False


def collect_current_hashes():
    """Scan Com/*.py with __HELP__ and return dict {filename: hash}."""
    current = {}
    for filename in os.listdir("Com"):
        if filename.endswith(".py") and filename != "__init__.py":
            path = os.path.join("Com", filename)
            if get_commands_in_file(path):
                current[filename] = compute_hash(path)
    return current


def get_changes(old, new):
    """Return list of change descriptions."""
    changes = []
    for fname, hval in new.items():
        if fname not in old:
            changes.append(f"🟢 Added `{fname[:-3]}`")
        elif old[fname] != hval:
            changes.append(f"✏️ Changed `{fname[:-3]}`")
    for fname in old:
        if fname not in new:
            changes.append(f"❌ Removed `{fname[:-3]}`")
    return changes


def setup(client, my_id):
    # Startup: handle pending restart
    async def handle_restart():
        if not os.path.exists(RESTART_FILE):
            return
        data = load_json(RESTART_FILE, None)
        if not isinstance(data, dict):
            return

        chat_id = data.get("chat_id")
        msg_id = data.get("msg_id")
        old_hashes = data.get("old_hashes", {})

        peer = await tgsend.resolve(client, chat_id) if chat_id else None
        if peer and msg_id:
            try:
                await client.delete_messages(peer, msg_id)
            except Exception:
                pass

        # Remove the marker early
        os.remove(RESTART_FILE)

        new_hashes = collect_current_hashes()
        changes = get_changes(old_hashes, new_hashes)

        if not changes:
            report = "✅ No command changes detected."
        else:
            report = "📋 **Command changes after restart:**\n" + "\n".join(changes)

        try:
            await client.send_message(peer or "me", report)
        except Exception:
            try:
                await client.send_message("me", report)
            except Exception:  # noqa: BLE001 - the report is informational
                log.info("update: post-restart report could not be delivered")

        save_json(HASH_FILE, new_hashes)

    asyncio.create_task(handle_restart())

    # !update command
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!update$"))
    async def update_cmd(event):
        old_hashes = load_json(HASH_FILE, {})
        if not isinstance(old_hashes, dict):
            old_hashes = {}

        new_hashes = collect_current_hashes()

        # Restart marker
        restart_data = {
            "chat_id": event.chat_id,
            "msg_id": event.id,
            "old_hashes": old_hashes   # <-- backup of old hashes
        }
        # Atomic: a half-written marker would misreport
        save_json(RESTART_FILE, restart_data)
        save_json(HASH_FILE, new_hashes)

        await event.edit("🔄 Restarting session...")

        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            # execv only returns on failure
            try:
                os.remove(RESTART_FILE)
            except OSError:
                pass
            await event.edit(f"❌ Restart failed: {e}")