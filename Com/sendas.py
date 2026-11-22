"""!sendas: post one message as a channel the account administers.

Layer 227 added ``send_as`` to ``send_message``/``send_file``, which is how the
official clients post into a group's discussion thread *as the channel* instead
of as the personal account. On MTProto it is the ``send_as`` peer on
``messages.sendMessage``.

What it can and cannot do is Telegram's rule, not this module's: the channel has
to be an admin of the chat (a linked discussion group normally is), and the
account has to be able to post there at all. When either is missing Telegram
answers ``SEND_AS_PEER_INVALID`` / ``CHAT_ADMIN_REQUIRED`` / 
``CHAT_WRITE_FORBIDDEN``, and each one is reported as itself -- a silent
fallback to the personal identity would be worse than a failure, because the
message would go out under the wrong name.

One command, one message. Nothing is remembered between calls, so a channel
identity cannot be left switched on by accident.
"""
import logging

from telethon import errors, events
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatWriteForbiddenError,
    PeerIdInvalidError,
    SendAsPeerInvalidError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)

from Com.core import brand, flood
import Com.core.tgsend as tgsend
from Com.core.reply import say

log = logging.getLogger("selftg.sendas")

__HELP__ = (
    "!sendas <channel> <text> → Send one message here as that channel\n"
    "!sendas <channel> (reply) → Same, using the replied message's text\n"
    "<channel> is @username, a -100… id, or a t.me link.\n"
    "The channel must be an admin of this chat (Telegram's rule, not ours)."
)
__CATEGORY__ = "Utilities"


def split_args(raw):
    """Split into (identity, text). Text keeps its spaces."""
    head, _, rest = (raw or "").strip().partition(" ")
    return head.strip(), rest.strip()


def _identity_ref(raw):
    """A -100… id is an int; a username or link stays a string."""
    text = raw.strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return text


async def _resolve_identity(client, raw):
    """Input peer for the channel, or ValueError with a readable reason."""
    ref = _identity_ref(raw)
    if isinstance(ref, int):
        return await tgsend.resolve(client, ref)
    return await client.get_input_entity(ref)


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!sendas\b(.*)$"))
    async def sendas_cmd(event):
        if not event.out or event.sender_id != my_id:
            return

        identity, text = split_args(event.pattern_match.group(1))
        if not identity:
            await say(event, "📖 <b>Send as</b>\n" + brand.esc(__HELP__),
                      name="sendas", parse_mode="html")
            return

        if not text and event.is_reply:
            reply = await event.get_reply_message()
            text = (reply.raw_text or "") if reply else ""
        if not text:
            await say(
                event,
                "❌ <b>Nothing to send.</b> Add text, or reply to a text "
                "message.",
                name="sendas",
                parse_mode="html",
            )
            return

        try:
            channel = await _resolve_identity(client, identity)
        except (ValueError, UsernameInvalidError, UsernameNotOccupiedError,
                PeerIdInvalidError) as exc:
            await say(
                event,
                f"❌ Could not resolve <code>{brand.esc(identity)}</code> · "
                f"{brand.esc(exc)}",
                name="sendas",
                parse_mode="html",
            )
            return

        try:
            await client.send_message(
                await tgsend.peer(event), text, send_as=channel
            )
        except flood.FLOOD_ERRORS as exc:
            left = flood.note_flood(exc.seconds)
            message = (
                f"⏳ <b>Telegram rate limit</b> · wait "
                f"<code>{exc.seconds}s</code>."
            )
            if left:
                message += "\n" + flood.describe(left)
            await say(event, message, name="sendas", parse_mode="html")
            return
        except SendAsPeerInvalidError:
            await say(
                event,
                f"❌ <b>Telegram will not accept</b> "
                f"<code>{brand.esc(identity)}</code> as the sender here. The "
                "channel has to be an admin of this chat.",
                name="sendas",
                parse_mode="html",
            )
            return
        except ChatAdminRequiredError:
            await say(event, "❌ <b>Posting as that channel needs an admin "
                             "right</b> the account does not have.",
                      name="sendas", parse_mode="html")
            return
        except ChatWriteForbiddenError:
            await say(event, "❌ <b>The account cannot post in this chat.</b>",
                      name="sendas", parse_mode="html")
            return
        except ChannelPrivateError:
            await say(event, "❌ <b>That channel is private</b> or the account "
                             "is not a member.",
                      name="sendas", parse_mode="html")
            return
        except errors.RPCError as exc:
            await say(event, f"❌ Telegram error "
                             f"(<code>{brand.esc(type(exc).__name__)}</code>).",
                      name="sendas", parse_mode="html")
            return
        except Exception as exc:  # noqa: BLE001 - report, never raise
            log.exception("sendas: send failed")
            await say(event, f"❌ <code>{brand.esc(type(exc).__name__)}</code> · "
                             f"{brand.esc(exc)}",
                      name="sendas", parse_mode="html")
            return

        log.info("sendas: sent one message as %s in %s", identity, event.chat_id)
        try:
            await event.delete()
        except Exception:  # noqa: BLE001 - the message is out already
            pass
