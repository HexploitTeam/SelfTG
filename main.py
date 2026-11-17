import asyncio
import importlib
import logging
import os
import signal
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession

from Com import scheduler
from Com.net import ReplitConnection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("selftg")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COMMANDS_DIR = os.path.join(BASE_DIR, "Com")

# Replit sleeps idle Repls and drops sockets. Back off between attempts instead
# of reconnecting in a tight loop (which would also look like flood traffic).
RECONNECT_BASE_DELAY = 5
RECONNECT_MAX_DELAY = 60
DISCONNECT_TIMEOUT = 10

client = None
my_id = None
_background_tasks = []


# ------------------------------
# Configuration
# ------------------------------
def _require_env(name):
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise SystemExit(
            f"❌ {name} is not set. Add it under Replit Secrets "
            "(Tools → Secrets) and restart."
        )
    return value


def build_client():
    """Create the self-bot client from Replit Secrets.

    Nothing is read at import time: a cold Repl must be able to import this
    module (and its command modules) before the secrets exist, and a missing
    secret has to produce a readable message instead of a stack trace.
    """
    session_string = _require_env("SESSION_STRING")
    api_id_raw = _require_env("API_ID")
    api_hash = _require_env("API_HASH")

    try:
        api_id = int(api_id_raw)
    except ValueError:
        raise SystemExit(
            "❌ API_ID must be the numeric api_id from my.telegram.org, "
            f"got {api_id_raw!r}."
        ) from None

    try:
        session = StringSession(session_string)
    except Exception as exc:
        raise SystemExit(
            "❌ SESSION_STRING is not a valid Telethon StringSession "
            f"({type(exc).__name__}: {exc}). Regenerate it and update the secret."
        ) from None

    return TelegramClient(
        session,
        api_id,
        api_hash,
        # Replit-compatible transport (port 5222, see Com/net.py).
        connection=ReplitConnection,
        # Telethon retries short drops itself; the loop below only handles the
        # cases it gives up on, so keep this small and bounded.
        connection_retries=3,
        retry_delay=RECONNECT_BASE_DELAY,
        timeout=30,
        auto_reconnect=True,
    )


# ------------------------------
# Load commands
# ------------------------------
def load_commands():
    total_loaded = 0
    failures = []
    # Sorted so handler registration order is deterministic between restarts.
    for filename in sorted(os.listdir(COMMANDS_DIR)):
        if filename.endswith(".py") and filename != "__init__.py":
            modulename = filename[:-3]
            fullname = f"Com.{modulename}"
            try:
                module = importlib.import_module(fullname)
                if hasattr(module, "setup"):
                    module.setup(client, my_id)
                if hasattr(module, "__HELP__"):
                    log.info("Loaded command: %s", module.__HELP__.splitlines()[0])
                    total_loaded += 1
            except Exception as e:
                failures.append(f"{fullname}: {e}")
                log.warning("Failed to import %s: %s", fullname, e)
    log.info("📂 Total commands loaded: %d", total_loaded)
    if failures:
        log.warning("⚠️ %d module(s) failed to load:", len(failures))
        for failure in failures:
            log.warning("   - %s", failure)
    return failures


# ------------------------------
# Connection lifecycle
# ------------------------------
async def _on_ready():
    """Runs once, after the first successful (authorized) connection."""
    global my_id
    me = await client.get_me()
    my_id = me.id
    log.info(
        "✅ Connected as %s (id=%s) username=@%s",
        me.first_name,
        my_id,
        me.username or "N/A",
    )

    load_commands()

    # Start the separate bot as a background task. Keep a reference: a bare
    # create_task() result can be garbage collected mid-flight.
    try:
        from Com import bot as bot_module

        if bot_module.BOT_ENABLED:
            task = asyncio.create_task(bot_module.start_bot(my_id), name="selftg-bot")
            _background_tasks.append(task)
            log.info("[BOT] Bot starting.")
        else:
            log.info("[BOT] BOT_TOKEN not set, bot disabled.")
    except Exception:
        log.exception("[BOT] Failed to start")

    # One loop for every periodic job (reminders, AFK cooldown sweeps). Started
    # after load_commands() so all jobs are registered by then.
    scheduler.start(client)
    log.info("📌 Bot is ready.")


async def _serve():
    """Stay connected, reconnecting with bounded exponential backoff."""
    delay = RECONNECT_BASE_DELAY
    ready = False

    while True:
        try:
            await client.connect()
            if not await client.is_user_authorized():
                # connect() + is_user_authorized() instead of client.start(): a
                # self-bot cannot complete the interactive phone/code login on
                # Replit, so a bad SESSION_STRING used to hang waiting on stdin.
                raise SystemExit(
                    "❌ SESSION_STRING is not authorized. Generate a new string "
                    "session and update the secret, then restart."
                )
            if not ready:
                await _on_ready()
                ready = True
            delay = RECONNECT_BASE_DELAY

            # Returns when the socket is closed for good (Replit sleep, network
            # change, Telegram kick). Telethon handles transient drops itself.
            await client.run_until_disconnected()
            log.warning(
                "Connection closed; reconnecting in %ds.", delay
            )
        except SystemExit:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning(
                "Connection error (%s: %s); retrying in %ds.",
                type(exc).__name__,
                exc,
                delay,
            )

        await asyncio.sleep(delay)
        delay = min(delay * 2, RECONNECT_MAX_DELAY)


async def _shutdown():
    """Cancel background work and close the session cleanly."""
    for task in _background_tasks:
        task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
        _background_tasks.clear()

    # Stop the job loop before the client goes away, so no job tries to send on
    # a closing connection.
    try:
        await scheduler.stop()
    except Exception:
        log.warning("Error while stopping the scheduler", exc_info=True)

    try:
        await asyncio.wait_for(client.disconnect(), timeout=DISCONNECT_TIMEOUT)
        log.info("Session closed.")
    except asyncio.TimeoutError:
        log.warning("Timed out closing the session; exiting anyway.")
    except Exception as exc:
        log.warning("Error while closing the session: %s", exc)


async def main():
    global client

    # Make `Com.*` importable and keep relative state paths (mode/, Logs/)
    # anchored to the project instead of wherever the Repl happened to start.
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    if os.getcwd() != BASE_DIR:
        log.info("Changing working directory to %s", BASE_DIR)
        os.chdir(BASE_DIR)

    client = build_client()

    # SIGTERM is what Replit sends on stop/restart. Without this the session is
    # torn down mid-write instead of being closed.
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass

    serve_task = asyncio.create_task(_serve(), name="selftg-serve")
    stop_task = asyncio.create_task(stop.wait(), name="selftg-stop")

    try:
        await asyncio.wait(
            {serve_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        for task in (serve_task, stop_task):
            task.cancel()
        results = await asyncio.gather(
            serve_task, stop_task, return_exceptions=True
        )
        await _shutdown()
        for result in results:
            if isinstance(result, BaseException) and not isinstance(
                result, asyncio.CancelledError
            ):
                raise result


# ------------------------------
# Run
# ------------------------------
if __name__ == "__main__":
    # asyncio.run() creates and closes the loop itself; the previous
    # loop = asyncio.get_event_loop() pattern is deprecated on 3.10+.
    asyncio.run(main())
