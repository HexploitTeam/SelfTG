"""Reactions: `!react` for one message, `!reaction` for every message a user sends.

Both commands send a real `messages.sendReaction` -- the reaction is attached to
the target message, nothing is posted in the chat.
"""
from telethon import errors, events
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
import os
import json
import asyncio
import logging
from datetime import datetime

from Com.core import flood
from Com.core.storage import save_json
import Com.core.tgsend as tgsend
from Com.core import brand
from Com.core.reply import say as _say

__HELP__ = (
    "!react <Emoji/alias> (reply) → React to the replied message; no message is posted\n"
    "!react (reply) → Same, with 👍\n"
    "!react clear (reply) → Remove your reaction from the replied message\n"
    "!reaction <@Username/ID> <Emoji/alias> → React with emoji to all future messages from the user\n"
    "!reaction (reply) <Emoji/alias> → React to messages of replied user\n"
    "!reaction stop <ID> → Stop the reaction task\n\n"
    "💡 `!react list` → every supported reaction and its aliases\n"
    "👍 like · 👎 dislike · ❤️ heart · 🔥 fire · 🩷 pinkheart · ❤️‍🔥 fireheart\n"
    "🎉 party · 🤣 laugh · 💯 100 · 🤝 handshake · 🫡 salute · 🫶 lovehand"
)
__CATEGORY__ = "Setup"

os.makedirs("mode", exist_ok=True)
REACTION_FILE = "mode/reactions.json"

#------------------------------
#Alias map
#------------------------------

# Telegram's set, plus the extras kept from v2
SUPPORTED_REACTIONS = {
    "👍", "👎", "❤️", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱",
    "🤬", "😢", "🎉", "🤩", "🤮", "💩", "🙏", "👌", "🕊️", "🤡",
    "🥱", "🥴", "😍", "🐳", "❤️‍🔥", "🌚", "🌭", "💯", "🤣", "⚡️",
    "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈",
    "😴", "😭", "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈", "😇", "😨",
    "🤝", "✍️", "🤗", "🫡", "🎅", "🎄", "☃️", "💅", "🤪", "🗿",
    "🆒", "💘", "🙉", "🦄", "😘", "💊", "🙊", "😎", "👾", "🤷‍♂️",
    "🤷", "🤷‍♀️", "😡", "😄", "💪", "😮‍💨", "🫶", "🩷", "🩵", "🩶",
    "🤍",
}

REACTION_ALIASES = {
    "like": "👍",
    "thumbsup": "👍",
    "dislike": "👎",
    "thumbsdown": "👎",
    "heart": "❤️",
    "love": "❤️",
    "redheart": "❤️",
    "fire": "🔥",
    "adore": "🥰",
    "lovey": "🥰",
    "clap": "👏",
    "applause": "👏",
    "party": "🎉",
    "celebrate": "🎉",
    "think": "🤔",
    "hmm": "🤔",
    "mindblown": "🤯",
    "mind": "🤯",
    "starstruck": "🤩",
    "stars": "🤩",
    "scream": "😱",
    "scared": "😱",
    "pray": "🙏",
    "please": "🙏",
    "eyes": "👀",
    "look": "👀",
    "100": "💯",
    "perfect": "💯",
    "muscle": "💪",
    "strong": "💪",
    "angry": "😡",
    "mad": "😡",
    "smile": "😄",
    "happy": "😄",
    "cry": "😢",
    "sad": "😢",
    "clown": "🤡",
    "joker": "🤡",
    "brokenheart": "💔",
    "heartbreak": "💔",
    "swear": "🤬",
    "curse": "🤬",
    "sigh": "😮‍💨",
    "relief": "😮‍💨",
    "salute": "🫡",
    "respect": "🫡",
    "handshake": "🤝",
    "deal": "🤝",
    "lovehand": "🫶",
    "heartsp": "🫶",
    "laugh": "🤣",
    "lol": "🤣",
    "grin": "😁",
    "bigsmile": "😁",
    "puke": "🤮",
    "sick": "🤮",
    "poop": "💩",
    "shit": "💩",
    "ok": "👌",
    "okay": "👌",
    "dove": "🕊️",
    "peace": "🕊️",
    "boring": "🥱",
    "yawn": "🥱",
    "drunk": "🥴",
    "woozy": "🥴",
    "inlove": "😍",
    "lovely": "😍",
    "whale": "🐳",
    "fireheart": "❤️‍🔥",
    "heartonfire": "❤️‍🔥",
    "lovefire": "❤️‍🔥",
    "moon": "🌚",
    "darkmoon": "🌚",
    "hotdog": "🌭",
    "bolt": "⚡️",
    "zap": "⚡️",
    "fast": "⚡️",
    "banana": "🍌",
    "trophy": "🏆",
    "win": "🏆",
    "confused": "🤨",
    "suspicious": "🤨",
    "neutral": "😐",
    "meh": "😐",
    "strawberry": "🍓",
    "champagne": "🍾",
    "cheers": "🍾",
    "kiss": "💋",
    "middlefinger": "🖕",
    "devil": "😈",
    "evil": "😈",
    "sleep": "😴",
    "sleepy": "😴",
    "sobbing": "😭",
    "sob": "😭",
    "nerd": "🤓",
    "ghost": "👻",
    "boo": "👻",
    "coder": "👨‍💻",
    "dev": "👨‍💻",
    "hacker": "👨‍💻",
    "pumpkin": "🎃",
    "halloween": "🎃",
    "monkey": "🙈",
    "nohear": "🙉",
    "nospeak": "🙊",
    "angel": "😇",
    "innocent": "😇",
    "fear": "😨",
    "worried": "😨",
    "write": "✍️",
    "hug": "🤗",
    "santa": "🎅",
    "xmas": "🎄",
    "snow": "☃️",
    "snowman": "☃️",
    "nails": "💅",
    "manicure": "💅",
    "crazy": "🤪",
    "goofy": "🤪",
    "moai": "🗿",
    "stone": "🗿",
    "cool": "🆒",
    "awesome": "🆒",
    "cupid": "💘",
    "arrowheart": "💘",
    "unicorn": "🦄",
    "kissface": "😘",
    "muah": "😘",
    "pill": "💊",
    "sunglasses": "😎",
    "chill": "😎",
    "alien": "👾",
    "spaceinvader": "👾",
    "shrugm": "🤷‍♂️",
    "shrug": "🤷",
    "shrugf": "🤷‍♀️",
    "rage": "😡",
    "furious": "😡",
    "pinkheart": "🩷",
    "pink": "🩷",
    "blueheart": "🩵",
    "lightblueheart": "🩵",
    "greyheart": "🩶",
    "grayheart": "🩶",
    "whiteheart": "🤍",
}

if not os.path.exists(REACTION_FILE):
    with open(REACTION_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f, indent=2)

active_reactions = {}

log = logging.getLogger("selftg.reaction")


#------------------------------
#!react arguments
#------------------------------

MAX_EMOJI_CODEPOINTS = 16   # family/flag ZWJ sequences run 8-10 codepoints
DEFAULT_REACTION = "👍"
CLEAR_WORDS = ("clear", "remove", "off", "none")

# Each task is a handler on every message
MAX_TASKS = 20

# Codepoint ranges one reaction emoji can be built from
_EMOJI_RANGES = (
    ("\u00a9", "\u00a9"),        # ©
    ("\u00ae", "\u00ae"),        # ®
    ("\u203c", "\u203c"),        # ‼
    ("\u2049", "\u2049"),        # ⁉
    ("\u2122", "\u2122"),        # ™
    ("\u2139", "\u2139"),        # ℹ
    ("\u2190", "\u21ff"),        # arrows, ↔️
    ("\u2300", "\u23ff"),        # ⌚ ⌛ ⏰
    ("\u25a0", "\u27bf"),        # geometric shapes, misc symbols, dingbats
    ("\u2934", "\u2935"),        # ⤴ ⤵
    ("\u2b00", "\u2bff"),        # ⭐ ⬆️
    ("\u3030", "\u3030"),        # 〰
    ("\u303d", "\u303d"),        # 〽
    ("\u3297", "\u3297"),        # ㊗
    ("\u3299", "\u3299"),        # ㊙
    ("\U0001f000", "\U0001faff"),  # all pictographs, flags, skin tones
    ("\U000e0020", "\U000e007f"),  # flag tag characters
)

# Skipped inside sequences, not counted
_EMOJI_JOINERS = frozenset("\u200d\ufe0e\ufe0f\u20e3")
_SKIN_TONES = ("\U0001f3fb", "\U0001f3ff")   # 👍🏽 etc. modify the emoji before them
_FLAGS = ("\U0001f1e6", "\U0001f1ff")        # two of these make one flag
_TAG_CHARS = ("\U000e0020", "\U000e007f")    # subdivide 🏴 into e.g. Scotland


def _is_single_emoji(text):
    """True when `text` is exactly one emoji, not two of them or a word.

    Counting codepoints is not enough: `🔥🔥` is two emoji and a valid reaction
    needs one, while `👍🏽`, `❤️` and `🏴󠁧󠁢󠁳󠁣󠁴󠁿` are each one emoji made of several
    codepoints. So modifiers are skipped and the emoji *bases* are counted: one
    base, a ZWJ sequence (`👨‍👩‍👧`), or a two-regional-indicator flag (`🇺🇸`).
    """
    if not text or len(text) > MAX_EMOJI_CODEPOINTS:
        return False

    bases = []
    for char in text:
        if char in _EMOJI_JOINERS:
            continue
        if _SKIN_TONES[0] <= char <= _SKIN_TONES[1]:
            continue
        if _TAG_CHARS[0] <= char <= _TAG_CHARS[1]:
            continue
        if not any(low <= char <= high for low, high in _EMOJI_RANGES):
            return False
        bases.append(char)

    if len(bases) == 1:
        return True
    if "\u200d" in text:   # several bases joined into one glyph
        return True
    if len(bases) == 2:     # a flag is two regional indicators and one emoji
        return all(_FLAGS[0] <= char <= _FLAGS[1] for char in bases)
    return False


def resolve_reaction(argument):
    """Turn `!react`'s argument into ``(emoji, error_text)``.

    ``emoji is None`` with no error means "remove the reaction": that is what
    sends ``reaction=None``, i.e. the field left out of the request. An empty
    vector is not the same thing -- Telegram answers it with REACTION_EMPTY.
    """
    text = (argument or "").strip()
    if not text:
        return DEFAULT_REACTION, None

    lowered = text.lower()
    if lowered in CLEAR_WORDS:
        return None, None
    if lowered in REACTION_ALIASES:
        return REACTION_ALIASES[lowered], None
    if _is_single_emoji(text):
        return text, None

    shown = text if len(text) <= 20 else text[:19] + "…"
    return None, (
        f"❌ <b>{brand.esc(shown)}</b> is not a single emoji, so it cannot "
        "be a reaction.\n"
        "Reply to a message and send <code>!react 🔥</code> — or "
        "<code>!react</code> alone for 👍.\n"
        "Send <code>!react list</code> for every reaction and alias."
    )


def reaction_list_text():
    """Every advertised reaction, with the words that select it."""
    names = {}
    for alias, emoji in REACTION_ALIASES.items():
        names.setdefault(emoji, []).append(alias)
    lines = [f"💡 <b>{len(SUPPORTED_REACTIONS)} reactions</b> · "
             "<code>!reaction &lt;user&gt; &lt;one&gt;</code>"]
    for emoji in sorted(SUPPORTED_REACTIONS):
        words = sorted(names.get(emoji, ()))
        lines.append(f"{emoji} " + ", ".join(words) if words else emoji)
    return "\n".join(lines)


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):

    def get_new_task_id():
        used = set(active_reactions.keys())
        for i in range(1, 1000):
            if i not in used:
                return i
        # fallback if all 1-999 are taken
        return int(datetime.now().timestamp() * 1000)
        
    def save_reactions():
        data = {}
        for tid, info in active_reactions.items():
            data[str(tid)] = {"user_id": info["user_id"], "emoji": info["emoji"]}
        save_json(REACTION_FILE, data)

    async def load_existing_reactions():
        if not os.path.exists(REACTION_FILE):
            return
        try:
            with open(REACTION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            return
        for task_id_str, info in data.items():
            if len(active_reactions) >= MAX_TASKS:
                log.warning("reaction: %d stored task(s) not restored (cap %d)",
                            len(data) - len(active_reactions), MAX_TASKS)
                break
            user_id = info["user_id"]
            emoji = info["emoji"]
            task_id = int(task_id_str)
            handler = await create_reaction_handler(user_id, emoji)
            active_reactions[task_id] = {
                "user_id": user_id,
                "emoji": emoji,
                "handler": handler
            }

    async def create_reaction_handler(user_id, emoji):
        @client.on(events.NewMessage)
        async def handler(event):
            if event.sender_id == user_id and event.raw_text:
                try:
                    await client(SendReactionRequest(
                        peer=await tgsend.peer(event),
                        msg_id=event.message.id,
                        reaction=[ReactionEmoji(emoticon=emoji)]
                    ))
                    log.info("reaction: %s on message %s", emoji, event.message.id)
                except Exception as exc:  # noqa: BLE001 - one message, not the client
                    log.warning("reaction: %s on message %s failed (%s)",
                                emoji, event.message.id, type(exc).__name__)
        return handler

    asyncio.create_task(load_existing_reactions())

    # Exactly one of the two patterns matches
    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"(?i)^!reaction\s+stop\b\s*(\S*)\s*$"))
    async def stop_reaction(event):
        argument = event.pattern_match.group(1)
        if not argument.isdigit():
            await say(event,
                      "❌ <code>!reaction stop</code> needs the task ID that "
                      "was printed when the task started: "
                      "<code>!reaction stop 3</code>.",
                      name="reaction")
            return
        task_id = int(argument)
        info = active_reactions.get(task_id)
        if not info:
            await say(event,
                      f"❌ No active reaction task with ID "
                      f"<code>{task_id}</code>",
                      name="reaction", parse_mode="html")
            return
        handler = info.get("handler")
        if handler:
            try:
                client.remove_event_handler(handler)
            except Exception as e:
                await say(event,
                          f"❌ <b>Could not remove the handler</b> · "
                          f"<code>{brand.esc(e)}</code>",
                          name="reaction", parse_mode="html")
                return
        del active_reactions[task_id]
        save_reactions()
        await say(event,
                  f"✅ <b>Stopped reaction task</b> · <code>{task_id}</code>",
                  name="reaction", parse_mode="html")

    # `(?!stop\b)` keeps this off the stop handler
    @client.on(
        events.NewMessage(
            from_users=my_id,
            pattern=r"(?i)^!reaction\s+(?!stop\b)(?:(@?\w+)|reply)\s+(.+)$"))
    async def set_reaction(event):
        try:
            target = event.pattern_match.group(1)
            emoji = event.pattern_match.group(2).strip()

            emoji_lower = emoji.lower()
            if emoji_lower in REACTION_ALIASES:
                emoji = REACTION_ALIASES[emoji_lower]

            # Shape only: Telegram decides
            if emoji not in SUPPORTED_REACTIONS and not _is_single_emoji(emoji):
                await say(event,
                          f"❌ <b>{brand.esc(emoji)}</b> is not a single emoji, "
                          "so it cannot be a reaction.\n"
                          "Send <code>!react list</code> for every reaction "
                          "and alias.",
                          name="reaction", parse_mode="html")
                return

            if target is None or target.lower() == "reply":
                if not event.is_reply:
                    await say(event,
                              "❌ Must reply to a message when using the "
                              "<code>reply</code> option.",
                              name="reaction", parse_mode="html")
                    return
                reply_msg = await event.get_reply_message()
                user_id = reply_msg.sender_id
            else:
                if target.isdigit():
                    user_id = int(target)
                else:
                    try:
                        user_entity = await client.get_entity(target)
                        user_id = user_entity.id
                    except Exception as e:
                        await say(event,
                                  f"❌ <b>Could not find that user</b> · "
                                  f"<code>{brand.esc(e)}</code>",
                                  name="reaction", parse_mode="html")
                        return

            if len(active_reactions) >= MAX_TASKS:
                await say(event,
                          f"❌ <b>{MAX_TASKS} reaction tasks</b> are already "
                          "running. Stop one with "
                          "<code>!reaction stop &lt;ID&gt;</code> first — each "
                          "task is a handler on every incoming message.",
                          name="reaction", parse_mode="html")
                return

            task_id = get_new_task_id()
            handler = await create_reaction_handler(user_id, emoji)
            active_reactions[task_id] = {
                "user_id": user_id,
                "emoji": emoji,
                "handler": handler
            }
            save_reactions()

            await say(event,
                      "✅ <b>Reaction task started</b>\n"
                      f"User · <code>{user_id}</code>\n"
                      f"Emoji · <code>{brand.esc(emoji)}</code>\n"
                      f"Task ID · <code>{task_id}</code>",
                      name="reaction", parse_mode="html")

        except Exception as e:
            await say(event,
                      f"❌ <b>Could not set the reaction</b> · "
                      f"<code>{brand.esc(e)}</code>",
                      name="reaction", parse_mode="html")

    #------------------------------
    #One-off reaction to a replied message
    #------------------------------

    async def say(event, text):
        """Answer in place with the Spooku Self signature, else reply.

        Every body in this module is HTML, so the shared helper only appends the
        signature.
        """
        await _say(event, text, name="react", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!react(?:\s+([\s\S]+))?$"))
    async def react_once(event):
        """`!react <emoji>` as a reply: reacts to that message, posts nothing.

        There is deliberately no "react to the previous message" mode: the
        command's trigger message is itself the newest message in the chat, and
        guessing which message the owner meant is exactly the surprise this
        command must not produce. Without a reply it explains itself instead.
        """
        if not event.out or event.sender_id != my_id:
            return

        if (event.pattern_match.group(1) or "").strip().lower() in ("list", "aliases"):
            await say(event, reaction_list_text())
            return

        if not event.is_reply:
            await say(event,
                      "❌ <code>!react</code> needs a target: reply to the "
                      "message you want to react to, then send "
                      "<code>!react 🔥</code> (or <code>!react</code> for 👍).\n"
                      "Nothing is posted in the chat — the reaction is attached "
                      "to that message.")
            return

        reply = await event.get_reply_message()
        if reply is None:
            await say(event, "❌ The replied message is not available any more; "
                             "nothing to react to.")
            return

        emoji, problem = resolve_reaction(event.pattern_match.group(1))
        if problem:
            await say(event, problem)
            return

        try:
            await client(SendReactionRequest(
                peer=await tgsend.peer(event),
                msg_id=reply.id,
                reaction=None if emoji is None else [ReactionEmoji(emoticon=emoji)],
            ))
        except errors.MessageNotModifiedError:
            if emoji is None:
                await say(event,
                          "ℹ️ You have no reaction on message "
                          f"<code>{reply.id}</code>.")
            else:
                await say(event,
                          f"ℹ️ <code>{brand.esc(emoji)}</code> is already "
                          "your reaction on that message.")
            return
        except errors.ReactionEmptyError:
            await say(event, "❌ Telegram reported an empty reaction; that "
                             "should only happen on removal. Try "
                             "<code>!react 🔥</code> instead.")
            return
        except errors.ReactionInvalidError:
            await say(event,
                      f"❌ Telegram refused <code>{brand.esc(emoji)}</code> "
                      "here. Either that emoji is not in its reaction set, or "
                      "this chat restricts reactions to a fixed list. 👍 and 🔥 "
                      "are accepted everywhere that allows reactions.")
            return
        except errors.ReactionsTooManyError:
            await say(event,
                      "❌ Message "
                      f"<code>{reply.id}</code> already has the maximum number "
                      "of different reactions, so a new emoji cannot be added. "
                      "Replace an existing one instead of adding a new type.")
            return
        except errors.PremiumAccountRequiredError:
            await say(event, "❌ Telegram wants a Premium account for this "
                             "reaction. Plain emoji from the standard set still work.")
            return
        except errors.DocumentInvalidError:
            await say(event, "❌ Telegram rejected the reaction's document — "
                             "custom (Premium) emoji are not supported here.")
            return
        except (errors.MessageIdInvalidError, errors.MsgIdInvalidError):
            await say(event, "❌ Message "
                             f"<code>{reply.id}</code> no longer exists in "
                             "this chat, so it cannot be reacted to.")
            return
        except errors.ChatWriteForbiddenError:
            await say(event, "❌ The account cannot write in this chat, so it "
                             "cannot react either. Reactions follow the same "
                             "write permission.")
            return
        except errors.UserBannedInChannelError:
            await say(event, "❌ The account is banned in this channel; reactions "
                             "are refused for the same reason messages are.")
            return
        except (errors.ChannelPrivateError, errors.ChannelInvalidError):
            await say(event, "❌ This channel is private or no longer valid. "
                             "Open a chat the account is still a member of.")
            return
        except errors.PeerIdInvalidError:
            await say(event, "❌ Telegram does not recognise this chat any more. "
                             "Send any message here and try again.")
            return
        except flood.FLOOD_ERRORS as exc:
            await say(event, "⏳ <b>Telegram rate-limited reactions</b> · "
                             f"wait <code>{exc.seconds}s</code> and try again. "
                             "Nothing was retried automatically.")
            return
        except errors.RPCError as exc:
            log.warning("react: RPC failure %s", type(exc).__name__)
            await say(event, "❌ Telegram rejected the reaction · "
                             f"<code>{type(exc).__name__}</code>; see the "
                             "Replit log.")
            return
        except Exception:  # noqa: BLE001 - a reaction must never kill the client
            log.exception("react: unexpected failure")
            await say(event, "❌ Reaction failed; see the Replit log.")
            return

        # Drop the command message
        try:
            await event.delete()
        except Exception:  # noqa: BLE001 - without delete rights it just stays
            log.info("react: could not delete the command message")
        log.info("react: %s on message %s", emoji or "(cleared)", reply.id)
