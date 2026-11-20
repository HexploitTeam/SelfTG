"""Auto-solve the maths challenge messages some groups use as a join gate.

Two things here are deliberate, because both were wrong in the first version:

* **The toggle is persisted** in ``mode/cauto.json``. It used to live only in a
  module global, so a Replit restart silently turned the feature back off -- or,
  if the global had been set by another import order, back on -- with nothing in
  the chat saying so. The file is the truth; the global is only a per-message
  cache of it.
* **Every answer goes through the shared flood gate** (``Com/core/flood.py``).
  This module replies to someone else's message automatically, which is exactly
  the traffic pattern that must never become a burst: `pace()` spaces the sends
  and an open breaker stops them entirely.

Failures are logged rather than swallowed: a challenge that cannot be answered is
worth a line in the Replit log, and a silently dead feature is indistinguishable
from one that was never enabled.
"""
import os
import re
import logging
from datetime import datetime

from telethon import errors, events

import Com.core.tgsend as tgsend
from Com.core import flood
from Com.core.safe_eval import evaluate as safe_evaluate
from Com.core.storage import ensure_json_file, load_json, save_json

__HELP__ = "!cauto ON/OFF → Auto solve math challenges in groups/DMs"
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.cauto")

STATE_FILE = "mode/cauto.json"
LOG_FILE = "mods/cauto_log.json"
MAX_LOG_ENTRIES = 1000

os.makedirs("mode", exist_ok=True)
os.makedirs("mods", exist_ok=True)
ensure_json_file(STATE_FILE, {"enabled": False})
ensure_json_file(LOG_FILE, [])

# Mirrors STATE_FILE
AUTO_SOLVE = False


#------------------------------
#State
#------------------------------

def load_enabled():
    """Read the persisted toggle. An unreadable file means off, never on."""
    data = load_json(STATE_FILE, {})
    return bool(data.get("enabled")) if isinstance(data, dict) else False


def save_enabled(enabled):
    save_json(STATE_FILE, {"enabled": bool(enabled)})
    return bool(enabled)


#------------------------------
#Command
#------------------------------

def setup(client, my_id):
    global AUTO_SOLVE
    AUTO_SOLVE = load_enabled()

    async def log_challenge(chat_id, msg_id, challenge_type, equation, result):
        entry = {
            "chat_id": chat_id,
            "message_id": msg_id,
            "type": challenge_type,
            "equation": equation,
            "result": result,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        data = load_json(LOG_FILE, [])
        if not isinstance(data, list):
            data = []
        data.append(entry)
        save_json(LOG_FILE, data[-MAX_LOG_ENTRIES:])

    async def answer(event, result):
        """Reply with `result`, obeying the flood gate. Returns True when sent."""
        if flood.is_open():
            log.info("cauto: breaker open for %ss, not answering", flood.cooldown_left())
            return False
        await flood.pace(event.chat_id)
        try:
            await client.send_message(
                await tgsend.peer(event), str(result), reply_to=event.id
            )
            return True
        except flood.FLOOD_ERRORS as exc:
            cooldown = flood.note_flood(exc.seconds)
            log.warning(
                "cauto: flood wait %ss%s", exc.seconds,
                f", breaker open for {cooldown}s" if cooldown else "",
            )
            return False
        except Exception as exc:  # noqa: BLE001 - one message, not the client
            log.warning("cauto: reply failed (%s)", type(exc).__name__)
            return False

    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!cauto\s+(on|off)$"))
    async def toggle_cauto(event):
        global AUTO_SOLVE
        state = event.pattern_match.group(1).lower()
        try:
            AUTO_SOLVE = save_enabled(state == "on")
        except Exception:  # noqa: BLE001 - never leave the toggle lying
            log.exception("cauto: could not persist the toggle")
            await event.edit("❌ Could not save the setting (storage error).")
            return

        await event.edit(
            "✅ Auto Challenge Solver: ON" if AUTO_SOLVE
            else "❌ Auto Challenge Solver: OFF"
        )

    @client.on(events.NewMessage())
    async def auto_solver(event):
        if not AUTO_SOLVE:
            return
        if event.out:
            return  # never our own messages

        text = event.raw_text
        if not text:
            return

        # Old style: "چالش ریاضی"
        if "چالش ریاضی" in text and "=" in text:
            match = re.search(r"([\d\s\+\-\×\*/÷]+)= ?", text)
            if not match:
                return

            expression = match.group(1).strip()
            expression = expression.replace("×", "*").replace("÷", "/")

            try:
                # Foreign text: never eval()
                result = safe_evaluate(expression)
            except Exception as exc:  # noqa: BLE001 - a foreign expression
                log.info("cauto: could not evaluate %r (%s)", expression,
                         type(exc).__name__)
                return

            if await answer(event, result):
                await log_challenge(event.chat_id, event.id, "چالش ریاضی",
                                    expression, str(result))

        # New style: "برای باز کردن جعبه حماسی"
        elif "برای باز کردن جعبه حماسی" in text:
            match = re.search(r"(\d+)\s*([\+\-\*/×÷])\s*(\d+)", text)
            if not match:
                return

            a, op, b = match.groups()
            op = op.replace("×", "*").replace("÷", "/")
            expr = f"{a}{op}{b}"

            try:
                result = str(safe_evaluate(expr))
            except Exception as exc:  # noqa: BLE001
                log.info("cauto: could not evaluate %r (%s)", expr, type(exc).__name__)
                return

            # A click is a callback query, not a send
            clicked = False
            if event.message.buttons:
                for row in event.message.buttons:
                    for btn in row:
                        if btn.text.strip() == result:
                            try:
                                await event.click(btn)
                                clicked = True
                                break
                            except Exception as exc:  # noqa: BLE001
                                log.info("cauto: button click failed (%s)",
                                         type(exc).__name__)
                    if clicked:
                        break

            # Only record what happened
            if clicked:
                await log_challenge(event.chat_id, event.id, "جعبه حماسی", expr,
                                    result)
