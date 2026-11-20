"""!fw: forward the replied-to message with the new forward controls.

Telethon 1.44 (layer 227) exposes two flags on ``forward_messages`` that older
schemas did not have:

* ``drop_author`` -- the copy carries no "Forwarded from" header, so a repost
  reads as a post of this account;
* ``drop_media_captions`` -- the media is copied without its caption.

Both are server-side decisions, so nothing is re-uploaded and no extra request
is sent: one forward per command, exactly like the plain one.

Usage is reply-based on purpose. Resolving an arbitrary link or id from text
needs the entity cache, and a StringSession has none after a restart, so the
message being forwarded is taken from the event instead of being guessed.

Errors are the ones Telegram actually returns for this call:
``ChatWriteForbiddenError`` (cannot post here), ``ChatAdminRequiredError``
(no right to post), ``ChannelPrivateError`` (not a member) and
``MessageIdInvalidError`` (source deleted). Anything else is reported by name
rather than swallowed.
"""
import logging
import re

from telethon import errors, events
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatWriteForbiddenError,
    MessageIdInvalidError,
    PeerIdInvalidError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)

from Com.core import flood
import Com.core.tgsend as tgsend
from Com.core.reply import say

log = logging.getLogger("selftg.fw")

__HELP__ = (
    "!fw → Forward the replied message into this chat\n"
    "!fw -a → …without the \"Forwarded from\" header\n"
    "!fw -c → …without the media caption\n"
    "!fw -ac → …both, in one token\n"
    "!fw -ac <chat> → Forward into another chat (id, @username or -100…)\n"
    "Reply to the message to forward: the source comes from the reply."
)
__CATEGORY__ = "Utilities"

FLAGS = {"a": "drop_author", "c": "drop_media_captions"}


def parse_args(raw):
    """Split the argument string into (flag map, target). Never raises."""
    flags = {}
    target = None
    for token in (raw or "").split():
        if token.startswith("-") and len(token) > 1 and not token[1:].isdigit():
            for letter in token[1:].lower():
                name = FLAGS.get(letter)
                if name:
                    flags[name] = True
            continue
        if target is None:
            target = token
    return flags, target


def _target_ref(raw):
    """A negative or positive decimal is an id, anything else is a username."""
    text = raw.strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return text


async def _resolve_target(client, target):
    """Input peer for `target`; raises ValueError with a readable reason."""
    ref = _target_ref(target)
    if isinstance(ref, int):
        return await tgsend.resolve(client, ref)
    return await client.get_input_entity(ref)


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!fw\b(.*)$"))
    async def fw_cmd(event):
        if not event.out or event.sender_id != my_id:
            return

        flags, target = parse_args(event.pattern_match.group(1))
        if not flags and target is None and not event.is_reply:
            await say(event, "📖 **Forward**\n" + __HELP__, name="fw")
            return

        if not event.is_reply:
            await say(
                event,
                "❌ Reply to the message you want to forward. `!fw` takes the "
                "source from the reply, so nothing has to be resolved by id.",
                name="fw",
            )
            return

        reply = await event.get_reply_message()
        if reply is None:
            await say(event, "❌ The replied message is not available.",
                      name="fw")
            return

        try:
            peer = await _resolve_target(client, target) if target \
                else await tgsend.peer(event)
        except (ValueError, UsernameInvalidError, UsernameNotOccupiedError,
                PeerIdInvalidError) as exc:
            await say(event, f"❌ Could not resolve `{target}`: {exc}",
                      name="fw")
            return

        labels = [name for name in ("drop_author", "drop_media_captions")
                  if flags.get(name)]
        try:
            await client.forward_messages(
                peer,
                reply.id,
                from_peer=await tgsend.peer(event),
                **flags,
            )
        except flood.FLOOD_ERRORS as exc:
            left = flood.note_flood(exc.seconds)
            text = f"⏳ Telegram rate limit: wait {exc.seconds}s."
            if left:
                text += "\n" + flood.describe(left)
            await say(event, text, name="fw")
            return
        except ChatWriteForbiddenError:
            await say(event, "❌ The account cannot post in the target chat.",
                      name="fw")
            return
        except ChatAdminRequiredError:
            await say(event, "❌ Posting here needs an admin right the account "
                             "does not have.", name="fw")
            return
        except ChannelPrivateError:
            await say(event, "❌ The target is private or the account is not a "
                             "member.", name="fw")
            return
        except MessageIdInvalidError:
            await say(event, "❌ The message being forwarded no longer exists.",
                      name="fw")
            return
        except errors.RPCError as exc:
            await say(event, f"❌ Telegram error ({type(exc).__name__}).",
                      name="fw")
            return
        except Exception as exc:  # noqa: BLE001 - report, never raise
            log.exception("fw: forward failed")
            await say(event, f"❌ {type(exc).__name__}: {exc}", name="fw")
            return

        if labels:
            log.info("fw: forwarded %s with %s", reply.id, ", ".join(labels))
        try:
            await event.delete()
        except Exception:  # noqa: BLE001 - the forward already happened
            pass
