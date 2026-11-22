"""`!pin` / `!unpin` -- pin, unpin and inspect the pinned message.

Verified against the resolved Telethon 1.33.1:

* ``client.pin_message(entity, message, *, notify=False, pm_oneside=False)``
  builds ``messages.UpdatePinnedMessageRequest(silent=not notify, ...)``, so
  `!pin silent` genuinely sends ``silent=True`` and `!pin` sends ``silent=False``.
* ``client.unpin_message(entity, message)`` with ``message=0`` becomes
  ``messages.UnpinAllMessagesRequest``; with an id it unpins that message.
* Pinning works in private chats too, but there it pins on **both** sides unless
  ``pm_oneside=True``. A self-bot must not pin things in someone else's view, so
  private chats use ``pm_oneside=True`` and the reply says so.
"""
import logging

from telethon import errors, events
from telethon.tl.types import InputMessagesFilterPinned, User

import Com.core.registry as registry
from Com.core import brand, flood
from Com.core.reply import say
import Com.core.tgsend as tgsend

log = logging.getLogger("selftg.pin")

SUBCOMMANDS = [
    ("!pin", "pin the replied message (or the latest one) with notification"),
    ("!pin silent", "pin without notifying members"),
    ("!pin unpin", "unpin the current pinned message"),
    ("!unpin", "same as !pin unpin"),
    ("!pin list", "show the pinned message(s) in this chat"),
]

__HELP__ = registry.command(
    "pin", SUBCOMMANDS,
    "Pin management for chats where the account is allowed to pin.",
)
__CATEGORY__ = "Utilities"


#------------------------------
#Helpers
#------------------------------

def _preview(message, limit=160):
    text = (message.raw_text or "").strip() if message else ""
    if not text:
        return "<i>(no text: media or service message)</i>"
    text = " ".join(text.split())
    text = text if len(text) <= limit else text[: limit - 1] + "…"
    return brand.esc(text)


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!(pin|unpin)(?:\s+([\s\S]*))?$"))
    async def pin_cmd(event):
        if not event.out or event.sender_id != my_id:
            return

        verb = event.pattern_match.group(1).lower()
        args = (event.pattern_match.group(2) or "").strip()
        head = args.split()[0].lower() if args else ""

        try:
            if verb == "unpin" or head in ("unpin", "off"):
                await _unpin(event)
            elif head == "list":
                await _list(event)
            elif head == "silent":
                await _pin(event, notify=False)
            elif not args:
                await _pin(event, notify=True)
            else:
                await _say(event, "📖 " + brand.esc(__HELP__))
        except errors.ChatAdminRequiredError:
            await _say(event, "❌ <b>The account needs admin rights</b> (and the "
                             "'pin messages' right) here.")
        except errors.ChatNotModifiedError:
            await _say(event, "ℹ️ <b>That message is already the pinned one.</b>")
        except errors.MessageNotModifiedError:
            await _say(event, "ℹ️ <b>Nothing changed.</b>")
        except errors.MessageIdInvalidError:
            await _say(event, "❌ <b>That message no longer exists.</b>")
        except flood.FLOOD_ERRORS as exc:
            await _say(event, f"⏳ <b>Telegram rate limit</b> · wait <code>{exc.seconds}s</code>.")
        except errors.ChatWriteForbiddenError:
            await _say(event, "❌ <b>The account cannot post in this chat any more.</b>")
        except errors.RPCError as exc:
            await _say(event, f"❌ Telegram error (<code>{brand.esc(type(exc).__name__)}</code>); "
                             "see the Replit log.")
            log.warning("pin: RPC failure %s", type(exc).__name__)
        except Exception:  # noqa: BLE001
            log.exception("pin: unexpected failure")
            await _say(event, "❌ <b>Pin command failed.</b> See the Replit log.")

    async def _chat(event):
        return await event.get_chat()

    async def _pin(event, notify):
        chat = await _chat(event)
        private = isinstance(chat, User)

        if event.is_reply:
            reply = await event.get_reply_message()
            target = reply.id if reply else None
            preview = _preview(reply)
        else:
            latest = await client.get_messages(await tgsend.peer(event), limit=1)
            if not latest:
                await _say(event, "❌ <b>This chat has no messages to pin.</b>")
                return
            target = latest[0].id
            preview = _preview(latest[0])

        if target is None:
            await _say(event, "❌ <b>Could not determine which message to pin.</b>")
            return

        await client.pin_message(
            event.chat_id, target, notify=notify, pm_oneside=private
        )

        bits = [
            f"📌 <b>Pinned message</b> <code>{target}</code>",
            "<i>notification sent</i>" if notify else "<i>silent</i>",
        ]
        if private:
            bits.append(
                "<i>private chat: pinned on your side only (pm_oneside)</i>"
            )
        bits.append(preview)
        await _say(event, "\n".join(bits))

    async def _unpin(event):
        peer = await tgsend.peer(event)
        pinned = await client.get_messages(
            peer, limit=1, filter=InputMessagesFilterPinned
        )
        if not pinned:
            await _say(event, "📭 <b>Nothing is pinned in this chat.</b>")
            return
        await client.unpin_message(peer, pinned[0].id)
        await _say(event, f"📌 <b>Unpinned message</b> <code>{pinned[0].id}</code>.")

    async def _list(event):
        pinned = await client.get_messages(
            event.chat_id, limit=5, filter=InputMessagesFilterPinned
        )
        if not pinned:
            await _say(event, "📭 <b>Nothing is pinned in this chat.</b>")
            return
        lines = ["📌 <b>Pinned messages</b>"]
        for message in pinned:
            sender = ""
            if message.sender_id:
                sender = f" · from <code>{message.sender_id}</code>"
            date = message.date.strftime("%Y-%m-%d %H:%M") if message.date else ""
            lines.append(
                f"• <code>{message.id}</code>{sender} · {date}\n"
                f"  {_preview(message, 120)}"
            )
        await _say(event, "\n".join(lines))

    async def _say(event, text):
        # Edit-then-reply is shared: see Com/core/reply.py.
        await say(event, text, name="pin", parse_mode="html")
