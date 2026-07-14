# Com/setreaction.py
from telethon import events
import os
import json
import asyncio
from datetime import datetime

__HELP__ = (
    "!setreaction <@Username/ID> <Emoji> → React with emoji to all future messages from the user\n"
    "!setreaction (reply) <Emoji> → React to messages of replied user\n"
    "!setreaction stop <ID> → Stop the reaction task")
__CATEGORY__ = "Setup"

os.makedirs("mode", exist_ok=True)
REACTION_FILE = "mode/reactions.json"

# Load or create reactions file
if not os.path.exists(REACTION_FILE):
    with open(REACTION_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f, indent=2)

# Active tasks dict
active_reactions = {}  # task_id: {"user_id": int, "emoji": str, "task": Task}


def setup(client, my_id):

    def save_reactions():
        data = {
            tid: {
                "user_id": info["user_id"],
                "emoji": info["emoji"]
            }
            for tid, info in active_reactions.items()
        }
        with open(REACTION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    async def load_existing_reactions():
        try:
            with open(REACTION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for task_id_str, info in data.items():
                user_id = info["user_id"]
                emoji = info["emoji"]
                task_id = int(task_id_str)
                task = asyncio.create_task(reaction_task(user_id, emoji))
                active_reactions[task_id] = {
                    "user_id": user_id,
                    "emoji": emoji,
                    "task": task
                }
        except Exception:
            pass

    async def reaction_task(user_id, emoji):

        async def handler(event):
            if event.sender_id == user_id and event.raw_text:
                try:
                    await event.reply(emoji)
                except Exception:
                    pass

        return client.add_event_handler(handler, events.NewMessage)

    @client.on(
        events.NewMessage(from_users=my_id,
                          pattern=r"^!setreaction stop (\d+)$"))
    async def stop_reaction(event):
        task_id = int(event.pattern_match.group(1))
        info = active_reactions.get(task_id)
        if info:
            task = info["task"]
            client.remove_event_handler(task)
            del active_reactions[task_id]
            save_reactions()
            await event.edit(f"✅ Stopped reaction task {task_id}")
        else:
            await event.edit(f"❌ No active reaction task with ID {task_id}")

    @client.on(
        events.NewMessage(
            from_users=my_id,
            pattern=r"^!setreaction\s+(?:@?(\w+)|reply)\s+(.+)$"))
    async def set_reaction(event):
        try:
            target = event.pattern_match.group(1)
            emoji = event.pattern_match.group(2).strip()

            # Determine user_id
            if target is None or target.lower() == "reply":
                if not event.is_reply:
                    await event.edit(
                        "❌ Must reply to a message if not providing username/ID"
                    )
                    return
                reply_msg = await event.get_reply_message()
                user_id = reply_msg.sender_id
            else:
                if target.isdigit():
                    user_id = int(target)
                else:
                    user_entity = await client.get_entity(target)
                    user_id = user_entity.id

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            task_id = int(datetime.now().timestamp() * 1000)

            # Start task
            task = await reaction_task(user_id, emoji)

            active_reactions[task_id] = {
                "user_id": user_id,
                "emoji": emoji,
                "task": task
            }
            save_reactions()

            await event.edit(
                f"✅ Reaction task started for {user_id} with emoji '{emoji}'. Task ID: {task_id}"
            )

        except Exception as e:
            await event.edit(f"❌ Failed to set reaction: {str(e)}")

    # Load existing reactions on startup
    asyncio.create_task(load_existing_reactions())
