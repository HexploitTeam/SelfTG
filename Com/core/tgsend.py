"""Resolve an event's chat the way Telethon itself does.

Why this exists
---------------
`client.send_file(chat_id, ...)` and `client.send_message(chat_id, ...)`, when
handed the event's raw id, pass a bare integer to `TelegramClient.get_input_entity()`, which can only
resolve entities it has cached. This bot runs on a `StringSession`, so nothing
about users/chats is persisted between restarts; when an id is not in the
in-memory cache the call dies with:

    ValueError: Could not find the input entity for PeerUser(user_id=...)

That is what made `!help all` (and every other "too long, send as a file" path)
crash in a private chat while `event.edit()` kept working: `Message.edit()`,
`Message.reply()` and `Message.pin()` all go through
`Message.get_input_chat()`, and that helper has a fallback the bare id does not
-- it looks the peer up in the recent dialog list (see
`telethon/tl/custom/chatgetter.py`). That fallback is what resolves a peer whose
access hash is not cached yet.

So: take the peer from the event, never from the raw id.

This module has no ``setup()`` and no ``__HELP__``.
"""
import logging

log = logging.getLogger("selftg.tgsend")


async def peer(event):
    """Return an InputPeer for `event`, falling back to the raw chat id.

    `event.get_input_chat()` uses the library's dialog fallback; if the event has
    no peer information at all the plain id is still a better attempt than
    raising here.
    """
    try:
        chat = await event.get_input_chat()
    except Exception:  # noqa: BLE001 - never let peer lookup mask the real call
        log.info("tgsend: get_input_chat() failed, using chat_id")
        chat = None
    return chat if chat is not None else event.chat_id


async def resolve(client, chat_id):
    """Resolve a *stored* chat id (no event available) to an input peer.

    Background work -- reminders, timers, countdown resume, the post-restart
    report -- only has the id it saved earlier, so `event.get_input_chat()` is
    not available. `get_input_entity()` alone hits the empty StringSession cache
    after a restart, so fall back to a dialog scan before giving up.
    """
    try:
        return await client.get_input_entity(chat_id)
    except Exception:  # noqa: BLE001 - not cached yet, look through dialogs
        log.info("tgsend: %s not cached, scanning dialogs", chat_id)
    try:
        async for dialog in client.iter_dialogs():
            entity = getattr(dialog, "entity", None)
            if getattr(dialog, "id", None) == chat_id or \
                    getattr(entity, "id", None) == chat_id:
                return await client.get_input_entity(entity or chat_id)
    except Exception:  # noqa: BLE001
        log.warning("tgsend: dialog scan failed for %s", chat_id)
    return chat_id
