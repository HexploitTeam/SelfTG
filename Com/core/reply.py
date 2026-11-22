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

from Com.core import brand

log = logging.getLogger("selftg.reply")


# "parse_mode not given": the client's own default, which is what every call
# site had before styled output needed to opt in
_UNSET = object()


async def say(event, text, *, name="reply", parse_mode=_UNSET, sign=True):
    """Show `text` on `event`, editing in place and falling back to a reply.

    `name` labels the log line and, when it names a command, the signature
    (``— Spooku Self · !ban``): every module already passes it, so the brand is
    attached once here instead of in 188 messages.

    `parse_mode` is opt-in. Without it `text` is a plain body: it is escaped and
    signed, then sent as HTML. With it the body is expected to be HTML already
    and only the signature is appended -- that is how `!love` and `!creator`
    keep their own markup.

    `sign=False` is for a message that leaves the product: an auto-reply to
    someone else, or a relayed body. Returns True when either delivery worked.
    """
    if sign:
        command = None if name == "reply" else name
        if parse_mode is _UNSET:
            text = brand.render(text, command)
            parse_mode = "html"
        else:
            text = brand.sign(text, command)

    options = {} if parse_mode is _UNSET else {"parse_mode": parse_mode}

    try:
        await event.edit(text, **options)
        return True
    except Exception:  # noqa: BLE001 - the edit is the fast path, not a promise
        pass

    try:
        await event.reply(text, **options)
        return True
    except Exception:  # noqa: BLE001 - there is nothing left to try
        log.info("%s: response could not be delivered", name)
        return False
