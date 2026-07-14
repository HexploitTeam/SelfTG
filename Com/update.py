# Com/update.py
from telethon import events
import os
import hashlib
import json
import asyncio
import sys

__HELP__ = "!update → Restart the session\n!update log → Show changes in commands/files"
__CATEGORY__ = "Setup"
HASH_FILE = "mode/file_hashes.json"  # stores last file hashes


def setup(client, my_id):

    def compute_hash(file_path):
        """Compute SHA256 hash of a file"""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            h.update(f.read())
        return h.hexdigest()

    def get_commands_in_file(file_path):
        """Return True if file defines __HELP__, else False"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code = f.read()
            return "__HELP__" in code
        except:
            return False

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!update(?:\s+log)?$"))
    async def update(event):
        try:
            command = event.text.strip().lower()

            # ---------------------------
            # !update log
            # ---------------------------
            if "log" in command:
                msg = await event.edit("📊 Gathering command changes...")
                await asyncio.sleep(0.5)

                current_hashes = {}
                file_changes = []

                # Scan all Com/*.py files that define __HELP__
                for filename in os.listdir("Com"):
                    if filename.endswith(".py"):
                        path = os.path.join("Com", filename)
                        if get_commands_in_file(path):
                            current_hashes[filename] = compute_hash(path)

                # Load previous hashes
                if os.path.exists(HASH_FILE):
                    with open(HASH_FILE, "r", encoding="utf-8") as f:
                        old_hashes = json.load(f)
                else:
                    old_hashes = {}

                # Detect changes
                for fname, hval in current_hashes.items():
                    if fname not in old_hashes:
                        file_changes.append(f"🟢 Added !{fname[:-3]}")
                    elif old_hashes[fname] != hval:
                        file_changes.append(f"✏️ Changed !{fname[:-3]}")

                for fname in old_hashes:
                    if fname not in current_hashes:
                        file_changes.append(f"❌ Deleted !{fname[:-3]}")

                if not file_changes:
                    file_changes.append("✅ No changes detected.")

                result_text = "📋 Command changes:\n" + "\n".join(file_changes)
                result_text += f"\n\n🔹 Total commands: {len(current_hashes)}"

                await msg.edit(result_text)

                # Update stored hashes
                os.makedirs(os.path.dirname(HASH_FILE), exist_ok=True)
                with open(HASH_FILE, "w", encoding="utf-8") as f:
                    json.dump(current_hashes, f, indent=2)

            # ---------------------------
            # !update (restart)
            # ---------------------------
            else:
                msg = await event.edit(
                    "🔄 Restarting the session to apply changes...")
                await asyncio.sleep(1)  # ensure message is edited
                os.execv(sys.executable, [sys.executable] + sys.argv)

        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")
