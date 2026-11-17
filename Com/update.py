# Com/update.py
import os
import sys
import json
import hashlib
import asyncio
from telethon import events

__HELP__ = "!update → Restart the session and show command changes after restart"
__CATEGORY__ = "Setup"

# -------------------------
# File paths
# -------------------------
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
    except:
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
    # -------------------------
    # Startup: handle pending restart
    # -------------------------
    async def handle_restart():
        if not os.path.exists(RESTART_FILE):
            return
        try:
            with open(RESTART_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            return

        chat_id = data.get("chat_id")
        msg_id = data.get("msg_id")
        old_hashes = data.get("old_hashes", {})

        # Delete the restart message if possible
        if chat_id and msg_id:
            try:
                await client.delete_messages(chat_id, msg_id)
            except Exception:
                pass

        # Remove restart marker (do this early)
        os.remove(RESTART_FILE)

        # Compute new hashes and compare
        new_hashes = collect_current_hashes()
        changes = get_changes(old_hashes, new_hashes)

        if not changes:
            report = "✅ No command changes detected."
        else:
            report = "📋 **Command changes after restart:**\n" + "\n".join(changes)

        # Send report to the same chat (or fallback to saved messages)
        try:
            await client.send_message(chat_id, report)
        except Exception:
            try:
                await client.send_message("me", report)
            except:
                pass

        # Update the stored hashes to the new state
        with open(HASH_FILE, "w", encoding="utf-8") as f:
            json.dump(new_hashes, f, indent=2)

    # Run the startup handler after client is ready
    asyncio.create_task(handle_restart())

    # -------------------------
    # !update command
    # -------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!update$"))
    async def update_cmd(event):
        # Load current (old) hashes if they exist
        old_hashes = {}
        if os.path.exists(HASH_FILE):
            try:
                with open(HASH_FILE, "r", encoding="utf-8") as f:
                    old_hashes = json.load(f)
            except:
                pass

        # Compute new hashes (current state)
        new_hashes = collect_current_hashes()

        # Save restart info (including old_hashes for comparison after restart)
        restart_data = {
            "chat_id": event.chat_id,
            "msg_id": event.id,
            "old_hashes": old_hashes   # <-- backup of old hashes
        }
        with open(RESTART_FILE, "w", encoding="utf-8") as f:
            json.dump(restart_data, f)

        # Also store the new hashes now (so they are current after restart)
        with open(HASH_FILE, "w", encoding="utf-8") as f:
            json.dump(new_hashes, f, indent=2)

        # Edit the command message to indicate restart
        await event.edit("🔄 Restarting session...")

        # Restart the process
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            # execv only returns if it failed; without this the bot died silently
            # and left mode/restart.json behind to fire on the next boot.
            try:
                os.remove(RESTART_FILE)
            except OSError:
                pass
            await event.edit(f"❌ Restart failed: {e}")