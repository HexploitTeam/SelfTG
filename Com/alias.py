"""Rewrite Persian !command aliases into their English equivalents before dispatch."""
import re
from telethon import events
import Com.core.tgsend as tgsend

__HELP__ = "Aliases for Persian commands (e.g., !راهنما → !help)"
__CATEGORY__ = "Setup"

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

    # Moderation / formatting / v2 additions
    "مسدود": "ban",
    "آزاد": "ban",
    "چت": "chat",
    "قالب": "chat",
    "آبوهوا": "weather",
    "هوا": "weather",
    "ویکی": "wiki",
    "دانشنامه": "wiki",
    "یادآوری": "remind",
    "یادآور": "remind",
    "سرگرمی": "trivia",
}


def setup(client, my_id):
    # Persian letters, optional arguments (\u0600-\u06FF)
    @client.on(
        events.NewMessage(
            from_users=my_id,
            pattern=r"^!([\u0600-\u06FF]+)(?:\s+(.*))?$"
        )
    )
    async def persian_alias_handler(event):
        persian_word = event.pattern_match.group(1)
        rest = event.pattern_match.group(2) or ""

        english_word = PERSIAN_ALIASES.get(persian_word)
        if not english_word:
            return

        if rest:
            english_cmd = f"!{english_word} {rest}"
        else:
            english_cmd = f"!{english_word}"

        await client.send_message(await tgsend.peer(event), english_cmd)

        await event.delete()