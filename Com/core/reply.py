"""The one way a command answers: edit its own message, else reply.

Why this exists
---------------
A self-bot's command message is the owner's own message, so the clean answer is
to *edit* it: the command disappears and the answer takes its place, and the chat
does not collect "!remind 10m tea" followed by a bot-looking reply. Editing can
be refused, though -- the message was deleted, it is older than Telegram's 48h
edit window, the account lost write access -- and then a reply is the only way to
say anything at all.

Seven modules (`!remind`, `!todo`, `!note`, `!afk`, `!ban`, `!pin`, `!poll`) each
carried their own copy of that try/edit/except/try/reply/except dance. Copies
drift: one logged the failure, another swallowed it, and a new command copied
whichever version it found first. This is the single implementation.

Nothing here raises. A command that cannot deliver its answer must still leave
the client and the event loop untouched; the log line is the record.

This module has no ``setup()`` and no ``__HELP__``.
"""
import logging

log = logging.getLogger("selftg.reply")


async def say(event, text, *, name="reply"):
    """Show `text` on `event`, editing in place and falling back to a reply.

    `name` only labels the log line, so a failure in ``mode/`` logs points at the
    command that produced it. Returns True when either delivery worked.
    """
    try:
        await event.edit(text)
        return True
    except Exception:  # noqa: BLE001 - the edit is the fast path, not a promise
        pass

    try:
        await event.reply(text)
        return True
    except Exception:  # noqa: BLE001 - there is nothing left to try
        log.info("%s: response could not be delivered", name)
        return False
