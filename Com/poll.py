"""`!poll` -- native Telegram polls via ``InputMediaPoll`` (no external service).

This replaces the previous reaction/text-based fake poll: a real poll is created
with ``messages.SendMediaRequest`` carrying ``InputMediaPoll``/``Poll``/
``InputPollAnswer``, so Telegram itself tallies votes, shows the quiz result and
enforces the limits.

Verified against the resolved Telethon 1.44.0 (layer 227, read from the
installed package, not assumed):

* ``types.Poll(id, question, answers, hash, closed, public_voters,
  multiple_choice, quiz, ...)`` -- ``question`` is ``TextWithEntities`` and a
  new poll goes out with ``id=0`` (Telegram assigns the id); a nonzero id is
  only meaningful for a poll read back from a sent message;
* ``types.InputMediaPoll(poll, correct_answers, solution, solution_entities)``;
* ``types.InputPollAnswer(text, media)`` -- a new poll is built from these and
  Telegram assigns the ``option`` bytes itself;
* ``types.PollAnswer(text, option)`` -- the server-side form read back from a
  sent poll, which is what ``!poll close`` re-sends inside the edited media;
* ``messages.GetPollResultsRequest(peer, msg_id)`` **exists** in this version, so
  `!poll results` does work for user accounts (it returns
  ``PollResults.results`` -> ``PollAnswerVoters(option, voters, chosen, correct)``
  plus ``total_voters``);
* closing a poll is an edit: ``messages.EditMessageRequest(peer, id,
  media=InputMediaPoll(poll=<same poll with closed=True>))``.

If `GetPollResultsRequest` is rejected at runtime (private chat, poll deleted,
older/newer server behaviour), `!poll results` says exactly what happened
instead of pretending it has data.
"""
import logging
import random
import re
import time
from datetime import datetime, timezone

from telethon import errors, events
from telethon.tl.functions.messages import (
    EditMessageRequest,
    GetPollResultsRequest,
    SendMediaRequest,
)
from telethon.tl.types import (
    InputMediaPoll,
    InputPollAnswer,
    MessageMediaPoll,
    Poll,
    TextWithEntities,
)

import Com.core.tgsend as tgsend

import Com.core.registry as registry
from Com.core import flood
from Com.core.reply import say
from Com.core.storage import load_store, save_json


# Layer 227 sends poll text as TextWithEntities, not str
def _as_text(value):
    return value if isinstance(value, TextWithEntities) else TextWithEntities(
        text=value or "", entities=[])


def _plain(value):
    return value.text if isinstance(value, TextWithEntities) else value


log = logging.getLogger("selftg.poll")

POLL_FILE = "mode/polls.json"
MAX_QUESTION = 300
MAX_OPTION = 100
MIN_OPTIONS = 2
MAX_OPTIONS = 10

SUBCOMMANDS = [
    ("!poll <question> | <opt1> | <opt2>", "anonymous poll"),
    ("!poll multi <question> | <opt1> | ...", "allow multiple answers"),
    ("!poll public <question> | <opt1> | ...", "voters are visible"),
    ("!poll quiz <question> | <correct> | <opt1> | ...", "quiz with a correct answer"),
    ("!poll quiz ... | explain: <text>", "quiz explanation"),
    ("!poll close", "close the latest poll here (or reply to one)"),
    ("!poll results", "results for the latest poll (or the replied one)"),
    ("!poll help", "this help"),
]

__HELP__ = registry.command(
    "poll", SUBCOMMANDS,
    "Native Telegram polls, quizzes and results.",
)
__CATEGORY__ = "Utilities"


#------------------------------
#Parsing
#------------------------------

def split_options(raw):
    """Split on '|' while keeping quoted segments (which may contain '|')."""
    parts, buffer, quote = [], [], None
    for char in raw:
        if quote:
            if char == quote:
                quote = None
            else:
                buffer.append(char)
        elif char in ("'", '"'):
            quote = char
        elif char == "|":
            parts.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(char)
    parts.append("".join(buffer).strip())
    return [part for part in parts if part]


def build_poll(question, options, *, quiz=False, multiple=False, public=False,
               correct_index=None, explanation=None):
    """Validate and return (InputMediaPoll, correct_index). Raises ValueError."""
    if len(question) > MAX_QUESTION:
        raise ValueError(f"question is {len(question)} chars; Telegram allows {MAX_QUESTION}")
    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        raise ValueError(f"need {MIN_OPTIONS}-{MAX_OPTIONS} options, got {len(options)}")
    if len({option.lower() for option in options}) != len(options):
        raise ValueError("options must be unique")
    for option in options:
        if len(option) > MAX_OPTION:
            raise ValueError(f"option {option[:20]!r}… is longer than {MAX_OPTION} chars")

    # Layer 227 creates options from InputPollAnswer: no client-chosen option
    answers = [InputPollAnswer(text=_as_text(option)) for option in options]
    # TDLib sends id 0 when creating a poll (the server assigns one); a nonzero
    # id refers to an existing poll and is only used when reading one back.
    poll = Poll(
        id=0,
        question=_as_text(question),
        answers=answers,
        hash=0,
        closed=False,
        public_voters=public,
        multiple_choice=multiple,
        quiz=quiz,
    )
    media = InputMediaPoll(
        poll=poll,
        correct_answers=[correct_index] if quiz else None,
        solution=explanation,
        solution_entities=[] if explanation else None,
    )
    return media, correct_index


def render_results(question, options, results, total, chosen=None):
    lines = [f"📊 **{question}**"]
    seen = 0
    for answer in results or []:
        index = answer.option[0] if answer.option else -1
        label = options[index] if 0 <= index < len(options) else f"option {index}"
        voters = answer.voters or 0
        seen += voters
        share = (voters / total * 100) if total else 0
        bar = "█" * max(0, min(20, round(share / 5)))
        mark = " ✅" if getattr(answer, "correct", False) else ""
        lines.append(f"{label}{mark}\n`{bar}` {voters} ({share:.0f}%)")
    if not lines[1:]:
        lines.append("_Telegram returned no tallies yet (no votes, or the poll was just closed)._")
    lines.append(f"\n_{total if total is not None else seen} voter(s) · {datetime.now(timezone.utc).strftime('%H:%M UTC')}_")
    return "\n".join(lines)


#------------------------------
#State
#------------------------------

def _default():
    return {"chats": {}}


def load_state():
    try:
        state = load_store(POLL_FILE, 1, _default)
    except Exception:  # noqa: BLE001
        log.exception("poll: could not read state")
        return _default()
    if not isinstance(state.get("chats"), dict):
        state["chats"] = {}
    return state


def save_state(state):
    try:
        save_json(POLL_FILE, state)
        return True
    except Exception:  # noqa: BLE001
        log.exception("poll: could not write state")
        return False


def _remember(chat_id, msg_id, *, question, options, quiz, correct_index):
    state = load_state()
    state["chats"][str(chat_id)] = {
        "msg_id": msg_id,
        "question": question,
        "options": options,
        "quiz": quiz,
        "correct_index": correct_index,
        "created": time.time(),
    }
    save_state(state)


def _last(chat_id):
    return load_state()["chats"].get(str(chat_id))


def _message_id_from(result):
    """Pull the new message id out of a SendMedia result."""
    updates = getattr(result, "updates", None) or []
    for update in updates:
        message = getattr(update, "message", None)
        if message is not None and getattr(message, "id", None):
            return message.id
    return None


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!poll(?:\s+([\s\S]*))?$"))
    async def poll_cmd(event):
        if not event.out or event.sender_id != my_id:
            return

        raw = (event.pattern_match.group(1) or "").strip()
        if not raw or raw.lower() in ("help", "?"):
            await _say(event, "📖 " + __HELP__)
            return

        head, _, rest = raw.partition(" ")
        sub = head.lower()

        try:
            if sub == "close":
                await _close(event)
            elif sub in ("results", "result", "stats"):
                await _results(event)
            elif sub == "create":
                await _create(event, rest)
            else:
                await _create(event, raw)
        except Exception:  # noqa: BLE001
            log.exception("poll: command failed")
            await _say(event, "❌ Poll command failed; see the Replit log.")

    async def _create(event, raw):
        quiz = multiple = public = False
        text = raw

        # Leading mode flags, in any order.
        while True:
            head, _, tail = text.partition(" ")
            if head.lower() == "quiz" and not quiz:
                quiz = True
            elif head.lower() in ("multi", "multiple") and not multiple:
                multiple = True
            elif head.lower() == "public" and not public:
                public = True
            elif head.lower() in ("anon", "anonymous"):
                public = False
            else:
                break
            text = tail.strip()

        parts = split_options(text)
        if len(parts) < 2:
            await _say(
                event,
                "❌ Need a question and at least one option, separated by `|`.\n"
                "Example: `!poll Best language? | Python | Rust`",
            )
            return

        question = parts[0]
        body = parts[1:]

        explanation = None
        for index, part in enumerate(body):
            if part.lower().startswith("explain:"):
                explanation = part.split(":", 1)[1].strip() or None
                body = body[:index] + body[index + 1:]
                break

        correct_index = None
        if quiz:
            if len(body) < 3:
                await _say(
                    event,
                    "❌ Quiz form: `!poll quiz <question> | <correct answer> | <opt1> | <opt2>`",
                )
                return
            correct_token = body[0]
            options = body[1:]
            if correct_token.isdigit():
                candidate = int(correct_token) - 1
                if not 0 <= candidate < len(options):
                    await _say(event, "❌ The correct-answer index is out of range.")
                    return
                correct_index = candidate
            else:
                matches = [i for i, option in enumerate(options) if option.lower() == correct_token.lower()]
                if not matches:
                    await _say(event, "❌ The correct answer must be one of the options.")
                    return
                correct_index = matches[0]
        else:
            options = body

        try:
            media, correct_index = build_poll(
                question, options, quiz=quiz, multiple=multiple, public=public,
                correct_index=correct_index, explanation=explanation,
            )
        except ValueError as exc:
            await _say(event, f"❌ {exc}")
            return

        peer = await tgsend.peer(event)

        async def _send():
            """Send the poll, retrying once with the other known poll id shape."""
            try:
                return await client(
                    SendMediaRequest(
                        peer=peer,
                        media=media,
                        message="",
                        random_id=random.getrandbits(63),
                    )
                )
            except errors.MediaInvalidError:
                # TDLib sends id 0, older clients (Pyrogram) send a random id;
                # a rejected id changes nothing server-side, so try the other.
                media.poll.id = random.getrandbits(62)
                log.info("poll: id 0 refused, retrying with a random id")
                return await client(
                    SendMediaRequest(
                        peer=peer,
                        media=media,
                        message="",
                        random_id=random.getrandbits(63),
                    )
                )

        try:
            result = await _send()
        except errors.ChatWriteForbiddenError:
            await _say(event, "❌ The account cannot post in this chat.")
            return
        except errors.ChatSendMediaForbiddenError:
            await _say(event, "❌ The account is not allowed to send media (polls) in this chat.")
            return
        except errors.ChatSendPollForbiddenError:
            await _say(event, "❌ Polls are not allowed in this chat.")
            return
        except errors.ChatAdminRequiredError:
            await _say(event, "❌ Admin rights are required to create a poll here.")
            return
        except errors.PollOptionInvalidError:
            await _say(event, "❌ Telegram rejected an option (duplicate or too long).")
            return
        except flood.FLOOD_ERRORS as exc:
            await _say(event, f"⏳ Telegram rate limit: wait {exc.seconds}s.")
            return
        except errors.MediaInvalidError:
            await _say(
                event,
                "❌ Telegram rejected the poll media (MEDIA_INVALID). Polls cannot "
                "be created in secret chats or channel direct-message chats; "
                "post it in a group, a channel or Saved Messages.",
            )
            return
        except errors.RPCError as exc:
            log.warning("poll: send failed %s", type(exc).__name__)
            await _say(event, f"❌ Telegram refused the poll ({type(exc).__name__}).")
            return

        msg_id = _message_id_from(result)
        if msg_id:
            _remember(
                event.chat_id, msg_id, question=question, options=options,
                quiz=quiz, correct_index=correct_index,
            )

        kind = "quiz" if quiz else ("multi" if multiple else "poll")
        bits = [f"✅ Created a {kind} poll."]
        if msg_id:
            bits.append(f"`!poll results` = #`{msg_id}` · `!poll close` closes it")
        await event.delete()
        await _say(event, "\n".join(bits))

    async def _resolve_target(event):
        """msg_id + metadata for the replied poll or the last one created here."""
        if event.is_reply:
            reply = await event.get_reply_message()
            if reply and isinstance(reply.media, MessageMediaPoll):
                poll = reply.media.poll
                return reply.id, {
                    "question": _plain(poll.question),
                    "options": [_plain(answer.text) for answer in poll.answers],
                    "correct_index": None,
                    "quiz": bool(poll.quiz),
                }
            if reply:
                return reply.id, None

        last = _last(event.chat_id)
        if not last:
            return None, None
        return last.get("msg_id"), last

    async def _results(event):
        msg_id, meta = await _resolve_target(event)
        if not msg_id:
            await _say(event, "❌ No poll to inspect. Reply to a poll or create one here first.")
            return

        peer = await tgsend.peer(event)
        try:
            # poll_hash=0 asks for the full tally instead of a cached diff.
            result = await client(
                GetPollResultsRequest(peer=peer, msg_id=msg_id, poll_hash=0)
            )
        except errors.RPCError as exc:
            log.info("poll: results failed (%s)", type(exc).__name__)
            await _say(
                event,
                f"❌ Telegram did not return results for message `{msg_id}` "
                f"({type(exc).__name__}). This version exposes "
                "`messages.GetPollResults`, so the usual causes are a deleted poll, "
                "a non-poll message id, or a chat where the account may not read results.",
            )
            return

        # Prefer the live message metadata: it is authoritative for option order.
        poll_question = (meta or {}).get("question", "Poll")
        options = (meta or {}).get("options", [])
        try:
            fetched = await client.get_messages(peer, ids=msg_id)
            if fetched and isinstance(fetched.media, MessageMediaPoll):
                poll_question = _plain(fetched.media.poll.question)
                options = [_plain(answer.text) for answer in fetched.media.poll.answers]
        except Exception:  # noqa: BLE001
            pass

        await _say(
            event,
            render_results(
                poll_question, options,
                getattr(result, "results", None),
                getattr(result, "total_voters", None),
            ),
        )

    async def _close(event):
        msg_id, meta = await _resolve_target(event)
        if not msg_id:
            await _say(event, "❌ No poll to close. Reply to a poll or create one here first.")
            return

        message = await client.get_messages(await tgsend.peer(event), ids=msg_id)
        if not message or not isinstance(message.media, MessageMediaPoll):
            await _say(event, f"❌ Message `{msg_id}` is not a poll.")
            return
        poll = message.media.poll
        if poll.closed:
            await _say(event, "ℹ️ That poll is already closed.")
            return

        closed = Poll(
            id=poll.id,
            question=poll.question,
            answers=poll.answers,
            hash=0,
            closed=True,
            public_voters=poll.public_voters,
            multiple_choice=poll.multiple_choice,
            quiz=poll.quiz,
            close_period=poll.close_period,
            close_date=poll.close_date,
        )
        correct_index = (meta or {}).get("correct_index")
        solution = (meta or {}).get("solution")
        media = InputMediaPoll(
            poll=closed,
            correct_answers=[correct_index] if correct_index is not None else None,
            solution=solution,
            solution_entities=[] if solution else None,
        )

        peer = await tgsend.peer(event)
        try:
            await client(EditMessageRequest(peer=peer, id=msg_id, media=media))
        except errors.MessageNotModifiedError:
            await _say(event, "ℹ️ Telegram reports the poll unchanged.")
            return
        except errors.ChatAdminRequiredError:
            await _say(event, "❌ Admin rights are required to close this poll.")
            return
        except errors.RPCError as exc:
            log.info("poll: close failed (%s)", type(exc).__name__)
            await _say(
                event,
                f"❌ Telegram refused to close poll `{msg_id}` ({type(exc).__name__}). "
                "Editing a poll this way is the documented close path, but some "
                "chats restrict it.",
            )
            return

        await _say(event, f"🔒 Closed poll `{msg_id}`.")

    async def _say(event, text):
        # Edit-then-reply is shared: see Com/core/reply.py.
        await say(event, text, name="poll")
