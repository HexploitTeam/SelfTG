"""`!love` -- print one fixed message that lives in the source.

Where the text lives
--------------------
``LOVE_TEXT`` at the top of ``main.py`` (Configuration). Edit that string and
restart the Repl. There is deliberately no runtime setter: the point is that the
message is source the owner reviews in the repository, not state that can be
changed from chat.

Delivery
--------
The command message is edited into the text, so ``!love`` leaves one message
instead of a command plus a reply; the ``!chat`` family behaves the same way.
``Com/core/reply.py`` falls back to a plain reply when the edit is refused (a
message older than Telegram's 48h window, a deleted message) and never raises.

Who can use it
--------------
Owner-only, through the same ``from_users=my_id`` gate as every other command.
The self-bot has no audience model, and answering strangers would mean a new
outgoing message per person who typed the command.

Empty state
-----------
A blank or whitespace-only ``LOVE_TEXT`` is not sent as an empty message: the
command says the constant is unset and names the file. Oversized text is
refused before sending, for the same reason -- a silent failure would look like
a broken command.
"""
import logging
import sys

from telethon import events

from Com.core.reply import say

log = logging.getLogger("selftg.love")

# Telegram rejects a message (and an edit) above 4096 characters
MAX_TEXT = 4096

__HELP__ = (
    "!love → Show the message written in `LOVE_TEXT` in main.py\n"
    "Edit that constant and restart; it has no runtime setter."
)
__CATEGORY__ = "Utilities"


#------------------------------
#Reading the constant
#------------------------------

def configured_text():
    """Return ``main.py``'s LOVE_TEXT, stripped; "" when empty or unreachable.

    In production ``main.py`` is the ``__main__`` module, so the constant is
    read from there and the entry point is not imported a second time. Under
    ``tools/smoke.py`` and any other harness the fallback import finds the same
    module without running ``main()`` (its entry guard is false).
    """
    entry = sys.modules.get("__main__")
    text = getattr(entry, "LOVE_TEXT", None) if entry is not None else None
    if not isinstance(text, str):
        try:
            import main
        except Exception:  # noqa: BLE001 - report "unset", never crash the client
            log.exception("love: main.py could not be imported")
            return ""
        text = getattr(main, "LOVE_TEXT", "")
    return text.strip() if isinstance(text, str) else ""


#------------------------------
#Command handler
#------------------------------

def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!love(?:\s+([\s\S]*))?$"))
    async def love_cmd(event):
        if not event.out or event.sender_id != my_id:
            return

        args = (event.pattern_match.group(1) or "").strip()
        if args:
            await _say(event, "❌ `!love` takes no arguments.")
            return

        text = configured_text()
        if not text:
            await _say(
                event,
                "❌ `LOVE_TEXT` in main.py is empty. Write the message there and "
                "restart the Repl.",
            )
            return
        if len(text) > MAX_TEXT:
            await _say(
                event,
                f"❌ `LOVE_TEXT` is {len(text)} characters; Telegram's limit is "
                f"{MAX_TEXT}. Shorten it in main.py and restart.",
            )
            return

        await _say(event, text)

    async def _say(event, text):
        # Edit-then-reply is shared: see Com/core/reply.py.
        await say(event, text, name="love")
