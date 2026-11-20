"""`!chat` family: format the owner's own messages in place.

How it works
------------
This is a self-bot: the account owns the messages it sends, so an outgoing
message arrives as a ``NewMessage`` event with ``out=True`` and can be edited by
message id. ``!chat bold hello`` therefore edits its own command message, so the
"!chat bold " prefix disappears and the written text stays formatted.

Formatting uses ``formatting_entities`` (explicit ``MessageEntity*`` objects),
never ``parse_mode``. With parse mode, a message whose text contains ``*``,
``_``, ``<`` or a backtick is mangled or rejected; with entities the text is
sent verbatim and the styling is described separately.

Loop safety
-----------
``edit_message`` emits a ``MessageEdited`` update, not a new message, and the
auto-format handler only listens to ``NewMessage``. As a second line of defence
every edited message id is remembered for a short while and skipped if it ever
arrives again as a new event. Messages starting with ``!`` are never formatted,
which also keeps this command's own confirmations out of the pipeline.

Persistence
-----------
Auto-format mode is per chat and stored in ``mode/chat_format.json`` through
``Com.storage.save_json`` (atomic write + fsync), so it survives Replit sleep.
If that file cannot be read the auto-formatter simply stays off ("fail open")
instead of raising.
"""
import json
import logging
import os
import time
from collections import OrderedDict

from telethon import errors, events
from telethon.tl.types import (
    MessageEntityBlockquote,
    MessageEntityBold,
    MessageEntityCode,
    MessageEntityItalic,
    MessageEntityPre,
    MessageEntitySpoiler,
    MessageEntityStrike,
    MessageEntityUnderline,
)

from Com.core.storage import load_json, save_json

__HELP__ = (
    "!chat bold|italic|underline|strike|spoiler|code|mono|quote|plain <text> → "
    "Rewrite your message with that formatting\n"
    "!chat <style> all <text> → Same, explicit form (whole rest is the text)\n"
    "!chat bold+italic <text> → Combine styles\n"
    "!chat <style> on|off → Auto-format every message you send in this chat\n"
    "!chat off → Turn auto-format off in this chat\n"
    "!chat status → Show the active style for this chat"
)
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.chat")

BASE_DIR = "mode"
FORMAT_FILE = os.path.join(BASE_DIR, "chat_format.json")
os.makedirs(BASE_DIR, exist_ok=True)

#------------------------------
#Configuration
#------------------------------

# style -> (entity class, needs language argument?)
STYLES = {
    "bold": (MessageEntityBold, False),
    "italic": (MessageEntityItalic, False),
    "underline": (MessageEntityUnderline, False),
    "strike": (MessageEntityStrike, False),
    "strikethrough": (MessageEntityStrike, False),
    "spoiler": (MessageEntitySpoiler, False),
    "code": (MessageEntityCode, False),
    "mono": (MessageEntityPre, True),
    "pre": (MessageEntityPre, True),
    "quote": (MessageEntityBlockquote, False),
    "blockquote": (MessageEntityBlockquote, False),
}

PLAIN_STYLES = {"plain", "unformat", "none", "text"}

# Recently edited ids
_EDITED_TTL = 120
_EDITED_MAX = 512
_recently_edited = OrderedDict()


#------------------------------
#Helpers
#------------------------------

def _remember(chat_id, msg_id):
    now = time.monotonic()
    _recently_edited[(chat_id, msg_id)] = now
    _recently_edited.move_to_end((chat_id, msg_id))
    while len(_recently_edited) > _EDITED_MAX:
        _recently_edited.popitem(last=False)


def _was_edited(chat_id, msg_id):
    stamp = _recently_edited.get((chat_id, msg_id))
    if stamp is None:
        return False
    if time.monotonic() - stamp > _EDITED_TTL:
        _recently_edited.pop((chat_id, msg_id), None)
        return False
    return True


def build_entities(style, text):
    """Return the MessageEntity list for `style` applied to all of `text`."""
    if not text:
        return []
    style = (style or "").strip().lower()
    if style in PLAIN_STYLES:
        return []

    entities = []
    length = len(text)
    for part in style.split("+"):
        part = part.strip()
        if not part:
            continue
        if part not in STYLES:
            raise ValueError(
                f"unknown style {part!r}. Try: "
                + ", ".join(sorted(set(STYLES) | PLAIN_STYLES))
            )
        entity_class, needs_language = STYLES[part]
        if needs_language:
            entities.append(entity_class(offset=0, length=length, language=""))
        else:
            entities.append(entity_class(offset=0, length=length))
    return entities


def _load_formats():
    data = load_json(FORMAT_FILE, {})
    return data if isinstance(data, dict) else {}


def get_chat_style(chat_id):
    """Active auto-format style for a chat, or None. Never raises."""
    try:
        style = _load_formats().get(str(chat_id))
    except Exception:  # noqa: BLE001 - fail open, never break sending
        log.warning("chat_format.json unreadable; auto-format disabled")
        return None
    return style if isinstance(style, str) and style else None


def set_chat_style(chat_id, style):
    data = _load_formats()
    if style:
        data[str(chat_id)] = style
    else:
        data.pop(str(chat_id), None)
    save_json(FORMAT_FILE, data)


def _truncate(text, limit=3800):
    return text if len(text) <= limit else text[: limit - 1] + "…"


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):

    async def _edit(event, text, entities=None, style_label=None):
        """Edit the triggering message in place, with precise error handling."""
        try:
            await client.edit_message(
                event.chat_id, event.id, text,
                formatting_entities=entities if entities is not None else [],
            )
            _remember(event.chat_id, event.id)
        except errors.MessageNotModifiedError:
            pass  # already identical; nothing to do
        except errors.MessageAuthorRequiredError:
            await _reply(event, "❌ Cannot edit that message: this account does not own it.")
        except errors.MessageEditTimeExpiredError:
            await _reply(event, "❌ Too old to edit (Telegram's 48h edit window).")
        except errors.MessageIdInvalidError:
            await _reply(event, "❌ That message no longer exists.")
        except errors.FloodWaitError as exc:
            await _reply(event, f"⏳ Telegram rate limit: wait {exc.seconds}s.")
        except errors.RPCError as exc:
            await _reply(event, f"❌ Telegram error ({type(exc).__name__}).")
        except Exception as exc:  # noqa: BLE001
            log.exception("chat: edit failed")
            await _reply(event, f"❌ {type(exc).__name__}: {exc}")

    async def _reply(event, text):
        try:
            await event.reply(text)
        except Exception:
            log.info("chat: could not deliver %r", text[:60])

    async def _target_text(event, rest):
        """Text for the command: explicit argument, else the replied message."""
        if rest:
            return rest
        if event.is_reply:
            reply = await event.get_reply_message()
            if reply:
                return reply.raw_text or ""
        return ""

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!chat(?:\s+([\s\S]*))?$"))
    async def chat_cmd(event):
        if not event.out or event.sender_id != my_id:
            return

        args = (event.pattern_match.group(1) or "").strip()
        if not args:
            await _edit(event, "📖 **Chat formatting**\n" + __HELP__)
            return

        head, _, rest = args.partition(" ")
        head_l = head.lower()
        rest = rest.strip()

        if head_l == "status":
            style = get_chat_style(event.chat_id)
            if style:
                await _edit(event, f"🎨 Auto-format in this chat: **{style}**")
            else:
                await _edit(event, "🎨 Auto-format is off in this chat.")
            return

        if head_l == "off" and not rest:
            set_chat_style(event.chat_id, None)
            await _edit(event, "🎨 Auto-format disabled in this chat.")
            return

        if head_l == "help":
            await _edit(event, "📖 **Chat formatting**\n" + __HELP__)
            return

        # `!chat <style> on|off` and `!chat <style> all <text>`
        parts = rest.split(maxsplit=1)
        keyword = parts[0].lower() if parts else ""
        tail = parts[1].strip() if len(parts) > 1 else ""

        if keyword in ("on", "off") and not tail:
            try:
                build_entities(head_l, "x")  # validates the style name
            except ValueError as exc:
                await _edit(event, f"❌ {exc}")
                return
            if keyword == "on":
                set_chat_style(event.chat_id, head_l)
                await _edit(
                    event,
                    f"🎨 Auto-format **{head_l}** enabled. Every plain message you "
                    "send here will be rewritten in that style. Use `!chat off` to stop.",
                )
            else:
                if get_chat_style(event.chat_id) == head_l:
                    set_chat_style(event.chat_id, None)
                    await _edit(event, f"🎨 Auto-format **{head_l}** disabled.")
                else:
                    await _edit(
                        event, f"ℹ️ Auto-format is not set to **{head_l}** in this chat."
                    )
            return

        if keyword == "all":
            text = tail
        else:
            text = await _target_text(event, rest)

        if not text:
            await _edit(
                event,
                f"Usage: `!chat {head_l} <text>` (or reply to a message, or "
                f"`!chat {head_l} on` for auto-mode, `!chat {head_l} all <text>`).",
            )
            return

        try:
            entities = build_entities(head_l, text)
        except ValueError as exc:
            await _edit(event, f"❌ {exc}")
            return
        await _edit(event, text, entities=entities, style_label=head_l)

    @client.on(events.NewMessage(outgoing=True))
    async def auto_format(event):
        """Rewrite the owner's plain messages when auto-mode is on."""
        if not event.out or event.sender_id != my_id:
            return
        text = event.raw_text or ""
        if not text or text.startswith("!"):
            return
        if event.media:
            # Never edit captions: a rejected edit can lose the media
            log.info("chat: auto-format skipped a media message in %s", event.chat_id)
            return
        if _was_edited(event.chat_id, event.id):
            return

        style = get_chat_style(event.chat_id)
        if not style:
            return

        try:
            entities = build_entities(style, text)
        except ValueError:
            log.warning("chat: stored style %r is invalid, disabling it", style)
            try:
                set_chat_style(event.chat_id, None)
            except Exception:
                pass
            return

        try:
            await client.edit_message(
                event.chat_id, event.id, text, formatting_entities=entities
            )
            _remember(event.chat_id, event.id)
        except errors.MessageNotModifiedError:
            pass
        except errors.FloodWaitError as exc:
            log.warning("chat: auto-format flood wait %ss; paused", exc.seconds)
            try:
                set_chat_style(event.chat_id, None)
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001 - never break normal sending
            log.info("chat: auto-format skipped (%s)", type(exc).__name__)
