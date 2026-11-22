"""!export and !import: zip the state directory and restore it after a restart."""
import os
import sys
import json
import zipfile
import tempfile
import shutil
from datetime import datetime
from telethon import events
import Com.core.tgsend as tgsend
from Com.core import brand
from Com.core.reply import say

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
        for root, dirs, files in os.walk("."):
            for file in files:
                full_path = os.path.join(root, file)
                # Skip the interpreter cache and this repository's own history
                if "__pycache__" in full_path or ".git" in full_path:
                    continue
                rel_path = os.path.relpath(full_path, ".")
                if not should_include(rel_path):
                    continue
                if should_exclude_file(file):
                    continue
                zf.write(full_path, rel_path)

    return zip_path

def extract_zip(zip_path):
    """Extract zip to current directory, overwriting files."""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(".")

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!export$"))
    async def export_cmd(event):
        await say(event, "📦 Creating export archive…", name="export")
        zip_path = create_export_zip()
        await event.delete()
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        await client.send_file(await tgsend.peer(event),
            zip_path,
            caption=brand.sign(
                f"📦 <b>Settings export</b> · <code>{stamp}</code>", "export"),
            parse_mode="html"
        )
        os.remove(zip_path)

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!import$"))
    async def import_cmd(event):
        if not event.is_reply:
            await say(event,
                      "❌ Reply to a settings zip file with "
                      "<code>!import</code>.",
                      name="import", parse_mode="html")
            return

        reply = await event.get_reply_message()
        if not reply.file:
            await say(event, "❌ The replied message does not contain a file.",
                      name="import")
            return

        if not reply.file.name or not reply.file.name.endswith(".zip"):
            await say(event, "❌ The file must be a <code>.zip</code> archive.",
                      name="import", parse_mode="html")
            return

        await say(event, "📥 Downloading and importing settings…",
                  name="import")

        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        zip_path = tmp.name
        tmp.close()

        await reply.download_media(file=zip_path)

        if not zipfile.is_zipfile(zip_path):
            os.remove(zip_path)
            await say(event, "❌ The file is not a valid zip archive.",
                      name="import")
            return

        try:
            extract_zip(zip_path)
        except Exception as e:
            os.remove(zip_path)
            await say(event,
                      f"❌ Failed to extract · <code>{brand.esc(e)}</code>",
                      name="import", parse_mode="html")
            return

        os.remove(zip_path)

        # Send success and restart
        await say(event, "✅ <b>Settings restored</b> · restarting…",
                  name="import", parse_mode="html")
        os.execv(sys.executable, [sys.executable] + sys.argv)