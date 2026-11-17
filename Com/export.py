# Com/export.py
import os
import sys
import json
import zipfile
import tempfile
import shutil
from datetime import datetime
from telethon import events

__HELP__ = (
    "!export → Export all settings (enemies, warns, mutes, lists, reactions, monitor) to a zip file.\n"
    "!import (reply to a settings zip file) → Restore all settings from the zip file and restart.\n"
    "CAUTION: Import will overwrite existing settings."
)
__CATEGORY__ = "Utilities"

# Folders and files to include in export
EXPORT_FOLDERS = [
    "mode",
    "mods",
]

# Files to exclude (temporary or runtime)
EXCLUDE_FILES = [
    "restart.json",
    "file_hashes.json",
    "sysmon.json",      # large logs
    "sysinfo.json",     # large logs
    "cauto_log.json",   # optional logs
]

def should_include(path):
    """Return True if the file/dir should be included in export."""
    # Include only specific folders
    for folder in EXPORT_FOLDERS:
        if path.startswith(folder + os.sep) or path == folder:
            return True
    return False

def should_exclude_file(filename):
    for excl in EXCLUDE_FILES:
        if filename == excl:
            return True
    return False

def create_export_zip():
    """Create a zip file with all settings and return the file path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    zip_path = tmp.name
    tmp.close()

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Walk the current directory
        for root, dirs, files in os.walk("."):
            for file in files:
                full_path = os.path.join(root, file)
                # Skip hidden files like .git, __pycache__, etc.
                if "__pycache__" in full_path or ".git" in full_path:
                    continue
                # Normalise path relative to current dir
                rel_path = os.path.relpath(full_path, ".")
                if not should_include(rel_path):
                    continue
                if should_exclude_file(file):
                    continue
                # Add to zip
                zf.write(full_path, rel_path)

    return zip_path

def extract_zip(zip_path):
    """Extract zip to current directory, overwriting files."""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(".")

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!export$"))
    async def export_cmd(event):
        await event.edit("📦 Creating export archive...")
        zip_path = create_export_zip()
        await event.delete()
        await client.send_file(
            event.chat_id,
            zip_path,
            caption=f"📦 Settings export ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"
        )
        os.remove(zip_path)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!import$"))
    async def import_cmd(event):
        if not event.is_reply:
            await event.edit("❌ Reply to a settings zip file with `!import`.")
            return

        reply = await event.get_reply_message()
        if not reply.file:
            await event.edit("❌ The replied message does not contain a file.")
            return

        # Check if it's a zip
        if not reply.file.name or not reply.file.name.endswith(".zip"):
            await event.edit("❌ The file must be a .zip archive.")
            return

        await event.edit("📥 Downloading and importing settings...")

        # Download zip to temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        zip_path = tmp.name
        tmp.close()

        await reply.download_media(file=zip_path)

        # Validate zip
        if not zipfile.is_zipfile(zip_path):
            os.remove(zip_path)
            await event.edit("❌ The file is not a valid zip archive.")
            return

        # Extract
        try:
            extract_zip(zip_path)
        except Exception as e:
            os.remove(zip_path)
            await event.edit(f"❌ Failed to extract: {str(e)}")
            return

        os.remove(zip_path)

        # Send success and restart
        await event.edit("✅ Settings restored. Restarting...")
        # Restart the bot
        os.execv(sys.executable, [sys.executable] + sys.argv)