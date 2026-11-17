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
    failures = []
    # Sorted so handler registration order is deterministic between restarts.
    for filename in sorted(os.listdir("Com")):
        if filename.endswith(".py") and filename != "__init__.py":
            modulename = filename[:-3]
            fullname = f"Com.{modulename}"
            try:
                module = importlib.import_module(fullname)
                if hasattr(module, "setup"):
                    module.setup(client, my_id)
                if hasattr(module, "__HELP__"):
                    print(f"Loaded command: {module.__HELP__.splitlines()[0]}")
                    total_loaded += 1
            except Exception as e:
                failures.append(f"{fullname}: {e}")
                print(f"Failed to import {fullname}: {e}")
    print(f"📂 Total commands loaded: {total_loaded}")
    if failures:
        # Make broken modules visible at startup instead of only in one log line.
        print(f"⚠️ {len(failures)} module(s) failed to load:")
        for failure in failures:
            print(f"   - {failure}")
    return failures


# ------------------------------
# Async main
# ------------------------------
async def main():
    global my_id

    # connect() + explicit authorization check instead of client.start(): a
    # self-bot cannot complete the interactive phone/code login on Replit, so a
    # bad SESSION_STRING used to hang the process waiting for stdin forever.
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit(
            "❌ SESSION_STRING is not authorized. Generate a new string session "
            "and update the secret, then restart."
        )

    me = await client.get_me()
    my_id = me.id
    print(
        f"✅ Connected as {me.first_name} (id={my_id}) username=@{me.username if me.username else 'N/A'}"
    )

    # Now that client is started, load commands
    load_commands()
    print("📌 Bot is ready.")

    # Start the separate bot as a background task
    try:
        from Com import bot as bot_module

        if bot_module.BOT_ENABLED:
            asyncio.create_task(bot_module.start_bot(my_id))
            print("[BOT] Bot starting.")
        else:
            print("[BOT] BOT_TOKEN not set, bot disabled.")
    except Exception as e:
        print(f"[BOT] Failed to start: {e}")

    # Keep running
    await client.run_until_disconnected()


# ------------------------------
# Run
# ------------------------------
if __name__ == "__main__":
    # asyncio.run() creates and closes the loop itself; the previous
    # loop = asyncio.get_event_loop() / run_until_complete() pattern is
    # deprecated on 3.10+ and raises on 3.14.
    asyncio.run(main())
