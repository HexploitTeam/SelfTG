"""!stats: per-chat and combined message statistics."""
import os
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from telethon import events

from Com.core import brand
from Com.core.reply import say
from Com.core.storage import save_json
import Com.core.tgsend as tgsend

__HELP__ = (
    "!stats → Show detailed stats for this chat\n"
    "!stats all → Show combined stats across ALL chats (top words, emojis, mentions, etc.)\n"
    "!stats reset → Reset stats for this chat\n"
    "!stats scan [limit] → Scan history and add to current stats"
)
__CATEGORY__ = "Information"

BASE_DIR = "mode"
STATS_FILE = os.path.join(BASE_DIR, "stats.json")
os.makedirs(BASE_DIR, exist_ok=True)

#------------------------------
#Helpers
#------------------------------

def is_emoji(c):
    code = ord(c)
    return (0x1F600 <= code <= 0x1F64F or
            0x1F300 <= code <= 0x1F5FF or
            0x1F680 <= code <= 0x1F6FF or
            0x2600 <= code <= 0x26FF or
            0x2700 <= code <= 0x27BF or
            0x1F900 <= code <= 0x1F9FF or
            0x1F1E6 <= code <= 0x1F1FF)

def extract_words(text):
    return re.findall(r'\b[a-zA-Z]{2,}\b', text.lower())

def extract_mentions(text):
    return re.findall(r'@\w+', text)

#------------------------------
#Stats storage
#------------------------------

# One in-memory copy, flushed once per event
_stats_cache = None

def load_stats(force_reload=False):
    global _stats_cache
    if _stats_cache is None or force_reload:
        _stats_cache = _read_stats_file()
    return _stats_cache

def _read_stats_file():
    if not os.path.exists(STATS_FILE):
        return {}
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_stats(data=None):
    save_json(STATS_FILE, _stats_cache if data is None else data)

def get_chat_stats(chat_id):
    data = load_stats()
    chat_id_str = str(chat_id)
    if chat_id_str not in data:
        data[chat_id_str] = {
            "total_msgs": 0,
            "total_chars": 0,
            "total_words": 0,
            "total_emojis": 0,
            "total_mentions": 0,
            "replies_given": 0,
            "media": {},
            "word_counts": {},
            "emoji_counts": {},
            "mention_counts": {},
            "reply_to_users": {},
            "reply_from_users": {},
            "daily_counts": {},
            "hourly_counts": {},
            "first_message": None,
            "last_message": None,
        }
    return data[chat_id_str]

def save_chat_stats(chat_id, stats, flush=True):
    data = load_stats()
    data[str(chat_id)] = stats
    if flush:
        save_stats()

def update_stats(chat_id, msg, flush=True):
    stats = get_chat_stats(chat_id)

    # Basic counts
    stats["total_msgs"] += 1
    if not stats["first_message"]:
        stats["first_message"] = msg.date.isoformat()
    stats["last_message"] = msg.date.isoformat()

    # Date/time counts
    date_str = msg.date.strftime("%Y-%m-%d")
    hour_str = str(msg.date.hour)
    stats["daily_counts"][date_str] = stats["daily_counts"].get(date_str, 0) + 1
    stats["hourly_counts"][hour_str] = stats["hourly_counts"].get(hour_str, 0) + 1

    # Text analysis
    text = msg.text or msg.raw_text or ""
    if text:
        stats["total_chars"] += len(text)
        words = extract_words(text)
        stats["total_words"] += len(words)
        # Count individual words
        for w in words:
            stats["word_counts"][w] = stats["word_counts"].get(w, 0) + 1
        # Emojis
        emojis = [c for c in text if is_emoji(c)]
        stats["total_emojis"] += len(emojis)
        for e in emojis:
            stats["emoji_counts"][e] = stats["emoji_counts"].get(e, 0) + 1
        # Mentions
        mentions = extract_mentions(text)
        stats["total_mentions"] += len(mentions)
        for m in mentions:
            stats["mention_counts"][m] = stats["mention_counts"].get(m, 0) + 1

    # Media
    if msg.media:
        media_type = msg.media.__class__.__name__
        stats["media"][media_type] = stats["media"].get(media_type, 0) + 1

    # Replies you give
    if msg.reply_to_msg_id:
        stats["replies_given"] += 1

    save_chat_stats(chat_id, stats, flush=flush)

def combine_stats_all(data):
    """Combine stats from all chats into one large dict with counters."""
    combined = {
        "total_msgs": 0,
        "total_chars": 0,
        "total_words": 0,
        "total_emojis": 0,
        "total_mentions": 0,
        "replies_given": 0,
        "media": Counter(),
        "word_counts": Counter(),
        "emoji_counts": Counter(),
        "mention_counts": Counter(),
        "daily_counts": Counter(),
        "hourly_counts": Counter(),
        "first_message": None,
        "last_message": None,
    }
    for chat_id_str, stats in data.items():
        combined["total_msgs"] += stats.get("total_msgs", 0)
        combined["total_chars"] += stats.get("total_chars", 0)
        combined["total_words"] += stats.get("total_words", 0)
        combined["total_emojis"] += stats.get("total_emojis", 0)
        combined["total_mentions"] += stats.get("total_mentions", 0)
        combined["replies_given"] += stats.get("replies_given", 0)
        combined["media"].update(stats.get("media", {}))
        combined["word_counts"].update(stats.get("word_counts", {}))
        combined["emoji_counts"].update(stats.get("emoji_counts", {}))
        combined["mention_counts"].update(stats.get("mention_counts", {}))
        combined["daily_counts"].update(stats.get("daily_counts", {}))
        combined["hourly_counts"].update(stats.get("hourly_counts", {}))
        # First/last
        first = stats.get("first_message")
        last = stats.get("last_message")
        if first:
            if not combined["first_message"] or first < combined["first_message"]:
                combined["first_message"] = first
        if last:
            if not combined["last_message"] or last > combined["last_message"]:
                combined["last_message"] = last
    return combined

def format_stats(stats, title="📊 Stats"):
    if stats["total_msgs"] == 0:
        return "📭 No messages counted yet."

    lines = []
    lines.append(f"<b>{brand.esc(title)}</b>")
    lines.append(f"📨 <b>Messages</b> · <code>{stats['total_msgs']}</code>")
    if stats.get("first_message"):
        lines.append(f"🕒 <b>First</b> · <code>{brand.esc(stats['first_message'])}</code>")
        lines.append(f"🕒 <b>Last</b> · <code>{brand.esc(stats['last_message'])}</code>")
    lines.append(f"📝 <b>Characters</b> · <code>{stats['total_chars']}</code>")
    lines.append(f"📝 <b>Words</b> · <code>{stats['total_words']}</code>")
    lines.append(f"😊 <b>Emojis</b> · <code>{stats['total_emojis']}</code>")
    lines.append(f"📣 <b>Mentions</b> · <code>{stats['total_mentions']}</code>")
    lines.append(f"💬 <b>Replies given</b> · <code>{stats['replies_given']}</code>")

    if stats.get("media"):
        media_str = ", ".join(
            f"{brand.esc(k.replace('MessageMedia', ''))}: {v}"
            for k, v in stats["media"].items()
        )
        lines.append(f"🖼️ <b>Media</b> · {media_str}")

    # Top words
    word_counter = stats.get("word_counts", {})
    if word_counter:
        top_words = sorted(word_counter.items(), key=lambda x: x[1], reverse=True)[:5]
        if top_words:
            lines.append(
                "📝 <b>Top words</b> · "
                + ", ".join(f"<code>{brand.esc(w)}</code>×{c}" for w, c in top_words)
            )

    # Top emojis
    emoji_counter = stats.get("emoji_counts", {})
    if emoji_counter:
        top_emojis = sorted(emoji_counter.items(), key=lambda x: x[1], reverse=True)[:5]
        if top_emojis:
            lines.append(
                "😊 <b>Top emojis</b> · "
                + " ".join(f"{brand.esc(e)}×{c}" for e, c in top_emojis)
            )

    # Top mentions
    mention_counter = stats.get("mention_counts", {})
    if mention_counter:
        top_mentions = sorted(mention_counter.items(), key=lambda x: x[1], reverse=True)[:5]
        if top_mentions:
            lines.append(
                "📣 <b>Top mentions</b> · "
                + ", ".join(f"<code>{brand.esc(m)}</code>×{c}" for m, c in top_mentions)
            )

    # Daily average
    if stats.get("first_message") and stats.get("last_message"):
        try:
            first = datetime.fromisoformat(stats["first_message"])
            last = datetime.fromisoformat(stats["last_message"])
            days = (last - first).days + 1
            if days > 0:
                avg = stats["total_msgs"] / days
                lines.append(f"📈 <b>Avg per day</b> · <code>{avg:.1f}</code>")
        except:
            pass

    # Most active day
    daily = stats.get("daily_counts", {})
    if daily:
        top_day = max(daily.items(), key=lambda x: x[1])
        lines.append(
            f"📅 <b>Most active day</b> · <code>{brand.esc(top_day[0])}</code> "
            f"({top_day[1]} messages)"
        )

    # Most active hour
    hourly = stats.get("hourly_counts", {})
    if hourly:
        top_hour = max(hourly.items(), key=lambda x: x[1])
        lines.append(
            f"⏰ <b>Most active hour</b> · <code>{brand.esc(top_hour[0])}:00</code> "
            f"({top_hour[1]} messages)"
        )

    return "\n".join(lines)

def setup(client, my_id):
    # Live counter
    @client.on(events.NewMessage(from_users=my_id))
    async def counter(event):
        if event.sender_id == my_id:
            update_stats(event.chat_id, event.message)

    # !stats (current chat)
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!stats$"))
    async def show_stats_current(event):
        chat_id = event.chat_id
        stats = get_chat_stats(chat_id)
        output = format_stats(stats, title="📊 Stats for this chat")
        await say(event, output, name="stats", parse_mode="html")

    # !stats all
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!stats all$"))
    async def show_stats_all(event):
        data = load_stats()
        if not data:
            await say(event, "📭 No stats found in any chat.", name="stats")
            return
        combined = combine_stats_all(data)
        output = format_stats(combined, title="🌍 Total stats across all chats")
        await say(event, output, name="stats", parse_mode="html")

    # !stats reset
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!stats reset$"))
    async def reset_stats(event):
        chat_id = event.chat_id
        data = load_stats()
        chat_id_str = str(chat_id)
        if chat_id_str in data:
            del data[chat_id_str]
            save_stats(data)
            await say(event, "✅ Stats reset for this chat.", name="stats")
        else:
            await say(event, "❌ No stats to reset for this chat.", name="stats")
        await event.delete()

    # !stats scan [limit]
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!stats scan(?:\s+(\d+))?$"))
    async def scan_stats(event):
        limit = event.pattern_match.group(1)
        if limit:
            limit = int(limit)
            if limit < 100:
                limit = 100
        else:
            limit = 5000

        chat_id = event.chat_id
        await say(
            event,
            f"⏳ <b>Scanning</b> up to <code>{limit}</code> messages in history…",
            name="stats",
            parse_mode="html",
        )

        try:
            msgs = await client.get_messages(await tgsend.peer(event), limit=limit)
        except Exception as e:
            await say(
                event,
                f"❌ <b>Could not fetch messages.</b> {brand.esc(e)}",
                name="stats",
                parse_mode="html",
            )
            return

        own_msgs = [m for m in msgs if m.sender_id == my_id]
        if not own_msgs:
            await say(event, "📭 You have no messages in the scanned range.", name="stats")
            return

        # One write per scan
        for msg in own_msgs:
            update_stats(chat_id, msg, flush=False)
        save_stats()

        await say(
            event,
            f"✅ <b>Added</b> <code>{len(own_msgs)}</code> messages from history to stats.",
            name="stats",
            parse_mode="html",
        )
        await event.delete()