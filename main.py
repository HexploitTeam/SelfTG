import os
import asyncio
import importlib
from telethon import TelegramClient
from telethon.sessions import StringSession

# ------------------------------
# Load Replit secrets
# ------------------------------
SESSION_STRING = os.environ.get("SESSION_STRING")
if not SESSION_STRING:
    raise ValueError("SESSION_STRING environment variable is required")

API_ID_STR = os.environ.get("API_ID")
if not API_ID_STR:
    raise ValueError("API_ID environment variable is required")
API_ID = int(API_ID_STR)

API_HASH = os.environ.get("API_HASH")
if not API_HASH:
    raise ValueError("API_HASH environment variable is required")

# ------------------------------
# Telegram client
# ------------------------------
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
my_id = None


# ------------------------------
# Load commands
# ------------------------------
def load_commands():
    total_loaded = 0
    for filename in os.listdir("Com"):
        if filename.endswith(".py") and filename != "__init__.py":
            modulename = filename[:-3]
            fullname = f"Com.{modulename}"
            try:
                module = importlib.import_module(fullname)
                if hasattr(module, "setup"):
                    module.setup(client, my_id)
                if hasattr(module, "__HELP__"):
                    print(f"Loaded command: {module.__HELP__}")
                    total_loaded += 1
            except Exception as e:
                print(f"Failed to import {fullname}: {e}")
    print(f"📂 Total commands loaded: {total_loaded}")


# ------------------------------
# Async main
# ------------------------------
async def main():
    global my_id
    await client.start()
    me = await client.get_me()
    my_id = me.id
    print(
        f"✅ Connected as {me.first_name} (id={my_id}) username=@{me.username if me.username else 'N/A'}"
    )

    # Now that client is started, load commands
    load_commands()
    print(
        "📌 Bot is ready. Send commands from your account (e.g., !ping, !info, !help, !log)."
    )

    # Keep running
    await client.run_until_disconnected()

# ------------------------------
# Run
# ------------------------------
loop = asyncio.get_event_loop()
loop.run_until_complete(main())
