"""!wordlist: fetch rockyou.txt and report on the generated wordlists."""
import os
import gzip
import urllib.request
import shutil
import asyncio
from telethon import events
from Com.core import brand
from Com.core.reply import say

__HELP__ = (
    "!wordlist download → Download rockyou.txt (14M real passwords) and save as mode/rockyou.txt.\n"
    "   - This is the most common wordlist for password recovery/analysis.\n"
    "   - Download size ~200MB, decompressed ~15M entries.\n"
    "!wordlist status → Show wordlist size and location.\n"
    "!wordlist merge → Copy rockyou.txt to mode/wordlist.txt.\n"
)
__CATEGORY__ = "Utilities"

BASE_DIR = "mode"
ROCKYOU_URL = "https://github.com/brannondorsey/naive-hashcat/releases/download/data/rockyou.txt"
ROCKYOU_FILE = os.path.join(BASE_DIR, "rockyou.txt")
WORDLIST_FILE = os.path.join(BASE_DIR, "wordlist.txt")
os.makedirs(BASE_DIR, exist_ok=True)

def download_file(url, dest):
    """Download a file with progress."""
    def report(block, block_size, total_size):
        percent = int(block * block_size * 100 / total_size)
        if percent % 10 == 0:
            print(f"Downloaded {percent}%", end='\r', flush=True)
    urllib.request.urlretrieve(url, dest, reporthook=report)
    print("Download complete!")

async def download_rockyou():
    if os.path.exists(ROCKYOU_FILE):
        return f"rockyou.txt already exists at {ROCKYOU_FILE}"
    await asyncio.get_event_loop().run_in_executor(None, download_file, ROCKYOU_URL, ROCKYOU_FILE)
    return f"Downloaded rockyou.txt to {ROCKYOU_FILE}"

def count_lines(filepath):
    if not os.path.exists(filepath):
        return 0
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        return sum(1 for _ in f)

async def count_lines_async(filepath):
    # ~130 MB read: keep it off the loop
    return await asyncio.get_running_loop().run_in_executor(None, count_lines, filepath)

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!wordlist download$"))
    async def download_cmd(event):
        await say(event,
                  "📥 <b>Downloading rockyou.txt</b> <i>(≈200MB)</i>… "
                  "this may take a few minutes.",
                  name="wordlist", parse_mode="html")
        try:
            msg = await download_rockyou()
            count = await count_lines_async(ROCKYOU_FILE)
            await say(event,
                      f"✅ {brand.esc(msg)}\n"
                      f"Entries · <code>{count:,}</code>",
                      name="wordlist", parse_mode="html")
        except Exception as e:
            await say(event,
                      f"❌ <b>Download failed</b> · "
                      f"<code>{brand.esc(e)}</code>",
                      name="wordlist", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!wordlist status$"))
    async def status_cmd(event):
        rockyou_count = await count_lines_async(ROCKYOU_FILE)
        wordlist_count = await count_lines_async(WORDLIST_FILE)
        msg = "📊 <b>Wordlist Status</b>"
        if rockyou_count:
            msg += (f"\n<code>rockyou.txt</code> · "
                    f"<b>{rockyou_count:,}</b> entries")
        if wordlist_count:
            msg += (f"\n<code>wordlist.txt</code> · "
                    f"<b>{wordlist_count:,}</b> entries")
        if not rockyou_count and not wordlist_count:
            msg += ("\nNo wordlists found. Use "
                    "<code>!wordlist download</code> or "
                    "<code>!wordlist generate</code>.")
        await say(event, msg, name="wordlist", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!wordlist merge$"))
    async def merge_cmd(event):
        if not os.path.exists(ROCKYOU_FILE):
            await say(event,
                      "❌ <code>rockyou.txt</code> not found. Use "
                      "<code>!wordlist download</code> first.",
                      name="wordlist", parse_mode="html")
            return
        await say(event, "🔄 <b>Merging</b> rockyou.txt with built-in words…",
                  name="wordlist", parse_mode="html")
        try:
            with open(ROCKYOU_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                rockyou_words = set(line.strip() for line in f if line.strip())
        except:
            await say(event, "❌ Failed to read <code>rockyou.txt</code>.",
                      name="wordlist", parse_mode="html")
            return
        # rockyou is already large enough that merging the generated list adds nothing
        shutil.copy2(ROCKYOU_FILE, WORDLIST_FILE)
        count = await count_lines_async(WORDLIST_FILE)
        await say(event,
                  "✅ <b>Merged</b> · <code>wordlist.txt</code> now has "
                  f"<b>{count:,}</b> entries.",
                  name="wordlist", parse_mode="html")