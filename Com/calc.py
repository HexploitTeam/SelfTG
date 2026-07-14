# Com/calc.py
from telethon import events

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
            # Normalize × to *
            expression = expression.replace("×", "*").replace("÷", "/")

            # Only allow digits, operators, dots, and spaces
            allowed = set("0123456789+-*/. ")
            if not all(c in allowed for c in expression):
                await event.edit("❌ Invalid expression")
                return

            # Evaluate safely
            try:
                result = eval(expression, {"__builtins__": {}})
            except Exception:
                await event.edit("❌ Calculation error")
                return

            # Delete command
            await event.delete()

            # Reply with result
            reply_msg = await event.get_reply_message()
            await client.send_message(event.chat_id,
                                      f"{result}",
                                      reply_to=reply_msg.id)

        except Exception as e:
            await event.edit(f"❌ Error: {str(e)}")
