"""!calc: arithmetic on a replied message, evaluated through Com.core.safe_eval."""
from telethon import events
import Com.core.tgsend as tgsend

from Com.core import brand
from Com.core.reply import say
from Com.core.safe_eval import evaluate as safe_evaluate

__HELP__ = "!calc <num1> <op> <num2> → Calculate (supports + - × /). Must be used as reply."
__CATEGORY__ = "Utilities"

def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!calc\s+(.+)$"))
    async def calc_handler(event):
        try:
            if not event.is_reply:
                await say(
                    event,
                    "❌ Reply to a message and use "
                    "<code>!calc &lt;num1&gt; &lt;op&gt; &lt;num2&gt;</code>",
                    name="calc",
                    parse_mode="html",
                )
                return

            expression = event.pattern_match.group(1).strip()
            # Persian keyboards send × where the parser expects *
            expression = expression.replace("×", "*").replace("÷", "/")

            # First gate; Com/core/safe_eval.py is the real guard
            allowed = set("0123456789+-*/. ")
            if not all(c in allowed for c in expression):
                await say(event, "❌ Invalid expression.", name="calc")
                return

            # AST whitelist: numbers and arithmetic only
            try:
                result = safe_evaluate(expression)
            except (ValueError, ZeroDivisionError, OverflowError):
                await say(event, "❌ Calculation error.", name="calc")
                return

            await event.delete()

            reply_msg = await event.get_reply_message()
            await client.send_message(
                await tgsend.peer(event),
                brand.sign(f"🧮 <b>Result</b> · <code>{brand.esc(result)}</code>", "calc"),
                parse_mode="html",
                reply_to=reply_msg.id,
            )

        except Exception as e:
            await say(
                event,
                f"❌ <b>Calc failed.</b> {brand.esc(e)}",
                name="calc",
                parse_mode="html",
            )
