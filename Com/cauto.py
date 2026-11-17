# Com/cauto.py
from telethon import events
from datetime import datetime
import re
import os
import json

from Com.safe_eval import evaluate as safe_evaluate
from Com.storage import save_json

__HELP__ = "!cauto ON/OFF → Auto solve math challenges in groups/DMs"

# Store state
AUTO_SOLVE = False
LOG_FILE = "mods/cauto_log.json"
os.makedirs("mods", exist_ok=True)

# Ensure log file exists
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)


def setup(client, my_id):
    global AUTO_SOLVE

    # Toggle ON/OFF
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!cauto\s+(on|off)$"))
    async def toggle_cauto(event):
        global AUTO_SOLVE
        state = event.pattern_match.group(1).lower()

        if state == "on":
            AUTO_SOLVE = True
            await event.edit("✅ Auto Challenge Solver: ON")
        else:
            AUTO_SOLVE = False
            await event.edit("❌ Auto Challenge Solver: OFF")

    # Logging helper
    async def log_challenge(chat_id, msg_id, challenge_type, equation, result):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            "chat_id": chat_id,
            "message_id": msg_id,
            "type": challenge_type,
            "equation": equation,
            "result": result,
            "timestamp": now
        }
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []

        data.append(log_entry)
        # Keep the log bounded: it grew by one entry per solved challenge and was
        # re-read and re-written in full every time (unbounded file + O(n²)).
        if len(data) > 1000:
            data = data[-1000:]
        save_json(LOG_FILE, data)

    # Auto-solver
    @client.on(events.NewMessage())
    async def auto_solver(event):
        global AUTO_SOLVE
        if not AUTO_SOLVE:
            return

        text = event.raw_text
        if not text:
            return

        # --------------------------
        # Old style: "چالش ریاضی"
        # --------------------------
        if "چالش ریاضی" in text and "=" in text:
            match = re.search(r"([\d\s\+\-\×\*/÷]+)= ?", text)
            if not match:
                return

            expression = match.group(1).strip()
            expression = expression.replace("×", "*").replace("÷", "/")

            try:
                # This expression comes from somebody else's message, so it must
                # never reach eval() (it was an RCE path via __subclasses__).
                result = safe_evaluate(expression)
                await client.send_message(event.chat_id,
                                          str(result),
                                          reply_to=event.id)
                await log_challenge(event.chat_id, event.id, "چالش ریاضی",
                                    expression, str(result))
            except Exception:
                pass

        # --------------------------
        # New style: "برای باز کردن جعبه حماسی"
        # --------------------------
        elif "برای باز کردن جعبه حماسی" in text:
            match = re.search(r"(\d+)\s*([\+\-\*/×÷])\s*(\d+)", text)
            if not match:
                return

            a, op, b = match.groups()
            op = op.replace("×", "*").replace("÷", "/")
            expr = f"{a}{op}{b}"

            try:
                result = str(safe_evaluate(expr))
            except Exception:
                return

            # Click the correct button if exists
            clicked = False
            if event.message.buttons:
                for row in event.message.buttons:
                    for btn in row:
                        if btn.text.strip() == result:
                            try:
                                await event.click(btn)
                                clicked = True
                                break
                            except Exception:
                                pass
                    if clicked:
                        break

            await log_challenge(event.chat_id, event.id, "جعبه حماسی", expr,
                                result)
