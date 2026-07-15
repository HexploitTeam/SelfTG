# Com/alias.py
import re
from telethon import events

__HELP__ = "Aliases for Persian commands (e.g., !راهنما → !help)"
__CATEGORY__ = "Setup"

# Mapping from Persian command word to English command word
PERSIAN_ALIASES = {
    # Core commands
    "راهنما": "help",
    "پینگ": "ping",
    "اطلاعات": "info",
    "سیستم": "sysinfo",
    "مانیتور": "sysmon",
    "بروزرسانی": "update",
    "uptime": "uptime",

    # Enemy management
    "دشمن": "enemy",
    "دشمنان": "enemy",

    # Reaction
    "واکنش": "reaction",
    "ریاکشن": "reaction",

    # Who is
    "کیست": "whois",

    # Crypto
    "ارز": "crypto",

    # Encoding/Decoding
    "کدگشایی": "decodecheck",
    "کدگذاری": "encode",

    # Monitor
    "نظارت": "monitor",

    # Others
    "خلاصه": "summarize",
    "ترجمه": "translate",
    "فایل": "fileinfo",
    "کوتاه": "shorturl",
}


def setup(client, my_id):
    # Pattern to match ! followed by Persian letters (and optional arguments)
    # Persian Unicode range: \u0600-\u06FF
    @client.on(
        events.NewMessage(
            from_users=my_id,
            pattern=r"^!([\u0600-\u06FF]+)(?:\s+(.*))?$"
        )
    )
    async def persian_alias_handler(event):
        persian_word = event.pattern_match.group(1)
        rest = event.pattern_match.group(2) or ""

        # Look up the alias
        english_word = PERSIAN_ALIASES.get(persian_word)
        if not english_word:
            return  # Not a known alias

        # Construct the English command
        if rest:
            english_cmd = f"!{english_word} {rest}"
        else:
            english_cmd = f"!{english_word}"

        # Send the English command to the same chat (as ourselves)
        await client.send_message(event.chat_id, english_cmd)

        # Delete the original Persian command message
        await event.delete()