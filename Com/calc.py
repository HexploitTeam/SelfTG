"""!calc: arithmetic on a replied message, evaluated through Com.core.safe_eval."""
from telethon import events
import Com.core.tgsend as tgsend

from Com.core.safe_eval import evaluate as safe_evaluate

__HELP__ = "!calc <num1> <op> <num2> → Calculate (supports + - × /). Must be used as reply."
__CATEGORY__ = "Utilities"

def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!calc\s+(.+)$"))
    async def calc_handler(event):
        try:
            if not event.is_reply:
                await event.edit(
                    "❌ Reply to a message and use !calc <num1> <op> <num2>")
                return

            expression = event.pattern_match.group(1).strip()
            # Persian keyboards send × where the parser expects *
            expression = expression.replace("×", "*").replace("÷", "/")

            # Reject anything else here; Com/core/safe_eval.py is the real guard
            allowed = set("0123456789+-*/. ")
            if not all(c in allowed for c in expression):
                await event.edit("❌ Invalid expression")
                return

            # Evaluate without eval(): the AST whitelist in Com/core/safe_eval.py only
            # accepts numbers and arithmetic operators.
            try:
                result = safe_evaluate(expression)
            except (ValueError, ZeroDivisionError, OverflowError):
                await event.edit("❌ Calculation error")
                return

            await event.delete()

            reply_msg = await event.get_reply_message()
            await client.send_message(await tgsend.peer(event),
                                      f"{result}",
                                      reply_to=reply_msg.id)

        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")
