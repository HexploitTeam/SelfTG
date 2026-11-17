# Com/reaction.py
from telethon import events
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
import os
import json
import asyncio
from datetime import datetime

from Com.storage import save_json
import Com.tgsend as tgsend

__HELP__ = (
    "!reaction <@Username/ID> <Emoji/alias> → React with emoji to all future messages from the user\n"
    "!reaction (reply) <Emoji/alias> → React to messages of replied user\n"
    "!reaction stop <ID> → Stop the reaction task\n\n"
    "💡 Supported reaction aliases:\n"
    "👍 like, 👍 | 👎 dislike, 👎 | 🤣 Laugh 🤣 | ❤️ heart, love, ❤️\n"
    "🔥 fire, 🔥 | 🥰 adore, 🥰 | 👏 clap, 👏\n"
    "🎉 party, 🎉 | 🤔 think, 🤔 | 🤯 mindblown, 🤯\n"
    "🤩 starstruck, 🤩 | 😱 scream, 😱 | 🙏 pray, 🙏\n"
    "👀 eyes, 👀 | 💯 100, 💯 | 💪 muscle, 💪\n"
    "😡 angry, 😡 | 😄 smile, 😄 | 😢 cry, 😢\n"
    "🤡 clown, 🤡 | 💔 brokenheart, 💔 | 🤬 swear, 🤬\n"
    "😮‍💨 sigh, 😮‍💨 | 🫡 salute, 🫡 | 🤝 handshake, 🤝 | 🫶 lovehand, 🫶"
)
__CATEGORY__ = "Setup"

os.makedirs("mode", exist_ok=True)
REACTION_FILE = "mode/reactions.json"

# Emoji alias mapping (text → actual emoji)
SUPPORTED_REACTIONS = {
    "👍", "👎", "❤️", "🔥", "🥰", "👏", "🎉", "🤔", "🤯", "🤩",
    "😱", "🙏", "👀", "💯", "💪", "😡", "😄", "😢", "🤡", "💔",
    "🤬", "😮‍💨", "🫡", "🤝", "🫶", "🤣"
}

REACTION_ALIASES = {
    # thumbs
    "like": "👍",
    "thumbsup": "👍",
    "dislike": "👎",
    "thumbsdown": "👎",
    # heart
    "heart": "❤️",
    "love": "❤️",
    "redheart": "❤️",
    # fire
    "fire": "🔥",
    # adore
    "adore": "🥰",
    "lovey": "🥰",
    # clap
    "clap": "👏",
    "applause": "👏",
    # party
    "party": "🎉",
    "celebrate": "🎉",
    # think
    "think": "🤔",
    "hmm": "🤔",
    # mindblown
    "mindblown": "🤯",
    "mind": "🤯",
    # starstruck
    "starstruck": "🤩",
    "stars": "🤩",
    # scream
    "scream": "😱",
    "scared": "😱",
    # pray
    "pray": "🙏",
    "please": "🙏",
    # eyes
    "eyes": "👀",
    "look": "👀",
    # 100
    "100": "💯",
    "perfect": "💯",
    # muscle
    "muscle": "💪",
    "strong": "💪",
    # angry
    "angry": "😡",
    "mad": "😡",
    # smile
    "smile": "😄",
    "happy": "😄",
    # cry
    "cry": "😢",
    "sad": "😢",
    # clown
    "clown": "🤡",
    "joker": "🤡",
    # brokenheart
    "brokenheart": "💔",
    "heartbreak": "💔",
    # swear
    "swear": "🤬",
    "curse": "🤬",
    # sigh
    "sigh": "😮‍💨",
    "relief": "😮‍💨",
    # salute
    "salute": "🫡",
    "respect": "🫡",
    # handshake
    "handshake": "🤝",
    "deal": "🤝",
    # lovehand
    "lovehand": "🫶",
    "heartsp": "🫶",
    # laugh
    "laugh": "🤣",
    "lol": "🤣",
}

if not os.path.exists(REACTION_FILE):
    with open(REACTION_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f, indent=2)

active_reactions = {}


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
                    print(f"[SUCCESS] Reacted with {emoji} to msg {event.message.id}")
                except Exception as e:
                    print(f"[ERROR] Reaction failed: {e}")
        return handler

    asyncio.create_task(load_existing_reactions())

    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!reaction\s+stop\s+(\d+)$"))
    async def stop_reaction(event):
        task_id = int(event.pattern_match.group(1))
        info = active_reactions.get(task_id)
        if not info:
            await event.edit(f"❌ No active reaction task with ID {task_id}")
            return
        handler = info.get("handler")
        if handler:
            try:
                client.remove_event_handler(handler)
            except Exception as e:
                await event.edit(f"❌ Failed to remove handler: {e}")
                return
        del active_reactions[task_id]
        save_reactions()
        await event.edit(f"✅ Stopped reaction task {task_id}")

    @client.on(
        events.NewMessage(
            from_users=my_id,
            pattern=r"^!reaction\s+(?:(@?\w+)|reply)\s+(.+)$"))
    async def set_reaction(event):
        try:
            target = event.pattern_match.group(1)
            emoji = event.pattern_match.group(2).strip()

            # Map alias to emoji
            emoji_lower = emoji.lower()
            if emoji_lower in REACTION_ALIASES:
                emoji = REACTION_ALIASES[emoji_lower]

            # Ensure the emoji is supported by Telegram
            if emoji not in SUPPORTED_REACTIONS:
                await event.edit(f"❌ '{emoji}' is not a supported Telegram reaction.\n"
                                 f"Use one of: {', '.join(sorted(SUPPORTED_REACTIONS))}")
                return

            if target is None or target.lower() == "reply":
                if not event.is_reply:
                    await event.edit(
                        "❌ Must reply to a message when using 'reply' option."
                    )
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
                        await event.edit(f"❌ Could not find user: {e}")
                        return

            task_id = get_new_task_id()
            handler = await create_reaction_handler(user_id, emoji)
            active_reactions[task_id] = {
                "user_id": user_id,
                "emoji": emoji,
                "handler": handler
            }
            save_reactions()

            await event.edit(
                f"✅ Reaction task started for user `{user_id}` with emoji '`{emoji}`'. Task ID: `{task_id}`"
            )

        except Exception as e:
            await event.edit(f"❌ Failed to set reaction: {str(e)}")