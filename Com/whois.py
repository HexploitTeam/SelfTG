# Com/whois.py
from telethon import events
import os
import json
import asyncio
from datetime import datetime
import pytz

__HELP__ = ("!whois set @BotUsername → Set the bot to fetch info from\n"
            "!whois @Username/NumberID → Fetch info from the set bot\n"
            "!whois (reply to a message) → Fetch info of the message sender\n"
            "!whois here (reply) → Legacy: same as replying without argument")
__CATEGORY__ = "Information"

WHOIS_FILE = "mode/whois.txt"
tz = pytz.timezone("Asia/Tehran")

# Mapping of fancy/bullshit characters to normal ones
FONT_MAP = str.maketrans({
    "γ": "y",
    "τ": "t",
    "η": "n",
    "ρ": "p",
    "α": "a",
    "σ": "s",
    "ß": "b",
    "Ｃ": "c",
    "қ": "k",
    "ƒ": "f",
    "ł": "l",
    "℮": "e",
    "Ƒ": "f",
    "ց": "g",
    "ᴜ": "u",
    "Ғ": "f",
    
    # add more mappings if needed
})


def setup(client, my_id):

    # ---------------------------
    # Set the bot
    # ---------------------------
    @client.on(
        events.NewMessage(from_users=my_id, pattern=r"^!whois set\s+@(\w+)$"))
    async def set_bot(event):
        bot_username = event.pattern_match.group(1)
        os.makedirs(os.path.dirname(WHOIS_FILE), exist_ok=True)
        with open(WHOIS_FILE, "w", encoding="utf-8") as f:
            f.write(bot_username)
        await event.edit(f"✅ Whois bot set to @{bot_username}")

    # ---------------------------
    # Fetch info
    # ---------------------------
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!whois\s*(.*)$"))
    async def whois(event):
        target = event.pattern_match.group(1).strip()
        await event.delete()  # Delete command

        # Load bot username
        if not os.path.exists(WHOIS_FILE):
            await event.respond(
                "❌ Please set the bot first with !whois set @BotUsername")
            return
        with open(WHOIS_FILE, "r", encoding="utf-8") as f:
            bot_username = f.read().strip()

        bot_entity = await client.get_entity(bot_username)

        # Determine user to query
        reply = await event.get_reply_message()
        if target.lower() == "here" and reply:
            user_to_query = reply.sender_id
        elif target:
            try:
                user_entity = await client.get_entity(target)
                user_to_query = user_entity.id
            except Exception:
                await event.respond("❌ Could not find the user.")
                return
        elif reply:
            # No target argument but replying to a message -> use that message's sender
            user_to_query = reply.sender_id
        else:
            await event.respond("❌ Usage: !whois (reply to a message) OR !whois @Username/ID OR !whois here (reply)")
            return

        # Send the user ID to the bot
        await client.send_message(bot_entity, str(user_to_query))

        # Get the ID of the latest message from the bot BEFORE the reply arrives
        old_msgs = await client.get_messages(bot_entity, limit=1)
        old_id = old_msgs[0].id if old_msgs else 0

        # Wait 7 seconds for the bot to process
        await asyncio.sleep(7)

        # Fetch messages from the bot that are newer than old_id
        new_msgs = await client.get_messages(bot_entity, min_id=old_id, limit=1)
        if not new_msgs:
            await event.respond("❌ Bot did not respond.")
            return

        raw_text = new_msgs[0].message


        # Remove Stickersets line
        lines = raw_text.splitlines()
        lines = [
            line for line in lines
            if not line.strip().startswith("Stickersets")
        ]

        # Replace fancy fonts
        clean_lines = [line.translate(FONT_MAP) for line in lines]

        # Parse and create default form
        final_lines = []
        final_lines.append("📊 Whois Information:\n")
        for line in clean_lines:
            # fix spacing and bullets
            if line.strip():
                final_lines.append(line)

        # Append Tehran timestamp at bottom
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        final_lines.append(f"\nFetched at Tehran time: {now}")

        final_msg = "\n".join(final_lines)
        await event.respond(final_msg)
