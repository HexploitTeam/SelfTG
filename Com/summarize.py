"""!summarize: extractive local summary with an optional Gemini pass."""
import logging
import os
import re
from collections import Counter

from telethon import events
import Com.core.tgsend as tgsend
from Com.core import brand
from Com.core.reply import say

import Com.core.api as api

# Free-tier Gemini; GEMINI_MODEL (comma separated) overrides the chain
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODELS = [
    model.strip()
    for model in (os.getenv("GEMINI_MODEL") or "").split(",")
    if model.strip()
] or [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
]

log = logging.getLogger("selftg.summarize")

__HELP__ = (
    "!summarize <text> → Summarize text you type (Gemini when configured).\n"
    "!summarize chat [N] → Summarize the last N messages, locally (default 50).\n"
    "Chat text and replied messages are summarized locally and never sent to a "
    "model; only text you type leaves the machine. Works for Persian & English."
)
__CATEGORY__ = "Utilities"


#------------------------------
#Local summarization
#------------------------------

def summarize_locally(text, max_sentences=5, max_chars=2000):
    """Extract key sentences using word frequency (works for Persian & English)."""
    if not text:
        return "No text to summarize."

    if len(text) < 200:
        return text

    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    # fa/en sentence boundaries
    sentence_splitter = re.compile(r'(?<=[.!?…؟])\s+')
    all_sentences = []
    for p in paragraphs:
        if not re.search(r'[.!?…؟]', p):
            all_sentences.append(p.strip())
        else:
            for s in sentence_splitter.split(p):
                s = s.strip()
                if s:
                    all_sentences.append(s)

    # Drop < 3-word sentences
    all_sentences = [s for s in all_sentences if len(s.split()) >= 3]

    if not all_sentences:
        return text[:500] + "..." if len(text) > 500 else text

    if len(all_sentences) <= max_sentences:
        summary = " ".join(all_sentences)
        if len(summary) > max_chars:
            return summary[:max_chars] + "..."
        return summary

    # Persian + English stopwords
    stopwords = {
        "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
        "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
        "this", "but", "his", "by", "from", "they", "we", "say", "her", "she",
        "or", "an", "will", "my", "one", "all", "would", "there", "their",
        "what", "so", "up", "out", "if", "about", "who", "get", "which", "go",
        "me", "when", "make", "can", "like", "time", "no", "just", "him", "know",
        "take", "people", "into", "year", "your", "good", "some", "could", "them",
        "see", "other", "than", "then", "now", "look", "only", "come", "its", "over",
        "think", "also", "back", "after", "use", "two", "how", "our", "work", "first",
        "well", "way", "even", "new", "want", "because", "any", "these", "give", "day",
        "most", "us", "is", "am", "are", "was", "were", "been", "being",
        # Persian stopwords
        "و", "به", "از", "با", "برای", "که", "این", "آن", "را", "در", "روی",
        "بر", "تا", "هم", "همین", "چون", "چرا", "آیا", "اما", "اگر", "هر", "چه",
        "شود", "می", "نیز", "همچنین", "بله", "خیر", "نه", "یا", "ولی", "باز",
        "داشت", "دارد", "دارند", "باش", "بود", "بوده", "بودند"
    }

    word_freq = Counter()
    for sent in all_sentences:
        # Persian letters, digits, apostrophes
        words = re.findall(r'[\w\u0600-\u06FF]+', sent.lower())
        for w in words:
            if w not in stopwords and len(w) > 1:
                word_freq[w] += 1

    scored = []
    for sent in all_sentences:
        words = re.findall(r'[\w\u0600-\u06FF]+', sent.lower())
        score = sum(word_freq.get(w, 0) for w in words)
        # Normalise by length
        score = score / (len(words) + 1)
        scored.append((sent, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    top_sentences = [s for s, _ in scored[:max_sentences]]

    ordered = []
    for sent in all_sentences:
        if sent in top_sentences:
            ordered.append(sent)

    summary = " ".join(ordered)

    if len(summary) > max_chars:
        summary = summary[:max_chars] + "..."

    # Fall back to truncation
    if len(summary) >= len(text) * 0.8:
        return text[:500] + "..." if len(text) > 500 else text

    return summary if summary else text[:500] + "..."


#------------------------------
#Gemini summarization
#------------------------------

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)
MAX_PROMPT_CHARS = 12000  # keeps us inside the free per-minute token budget

# First model that answered
_working_model = {"name": None}


def _extract_text(data):
    for candidate in data.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            text = part.get("text")
            if text:
                return text.strip()
    return None


async def summarize_with_gemini(text):
    """Return a summary, or None to fall back to the local summarizer."""
    if not GEMINI_API_KEY:
        return None

    prompt = (
        "Summarize the following text in a few plain sentences. No preamble, "
        "no markdown headings.\n\n" + text[:MAX_PROMPT_CHARS]
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 600},
    }

    models = list(GEMINI_MODELS)
    if _working_model["name"] in models:
        models.remove(_working_model["name"])
        models.insert(0, _working_model["name"])

    for model in models:
        try:
            data = await api.post_json(
                GEMINI_URL.format(model=model),
                payload,
                provider=f"gemini({model})",
                headers={"x-goog-api-key": GEMINI_API_KEY},
                timeout=25,
                retries=0,
            )
        except api.RateLimited as exc:
            # Quota is per project
            log.info("gemini: rate limited (%s), using local summarizer", exc.describe())
            return None
        except api.APIError as exc:
            log.info("gemini: %s failed (%s)", model, exc.describe())
            continue
        except Exception as exc:  # noqa: BLE001
            log.info("gemini: %s crashed (%s)", model, type(exc).__name__)
            continue

        summary = _extract_text(data)
        if summary:
            _working_model["name"] = model
            return summary
        log.info("gemini: %s returned no text", model)

    return None


#------------------------------
#Command
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!summarize(?:\s+(.*))?$"))
    async def summarize_cmd(event):
        try:
            arg_str = event.pattern_match.group(1)
            if not arg_str and not event.is_reply:
                await say(event, "📖 <b>Summarize Help</b>\n\n" + brand.esc(__HELP__),
                          name="summarize", parse_mode="html")
                return

            # Chat summarization
            if arg_str and arg_str.startswith("chat"):
                parts = arg_str.split()
                limit = 50
                if len(parts) > 1:
                    try:
                        limit = int(parts[1])
                        if limit < 1:
                            limit = 1
                        if limit > 200:
                            limit = 200
                    except:
                        pass

                await say(event,
                          f"⏳ <b>Fetching</b> the last "
                          f"<code>{limit}</code> messages…",
                          name="summarize", parse_mode="html")
                try:
                    messages = await client.get_messages(await tgsend.peer(event), limit=limit)
                except Exception as e:
                    await say(event,
                              f"❌ <b>Could not fetch messages</b> · "
                              f"<code>{brand.esc(e)}</code>",
                              name="summarize", parse_mode="html")
                    return

                if not messages:
                    await say(event, "📭 No messages found.", name="summarize")
                    return

                texts = []
                for m in messages:
                    if m.text and not m.text.startswith("!"):
                        texts.append(m.text)
                if not texts:
                    await say(event, "📭 No text messages to summarize.",
                              name="summarize")
                    return

                combined = " ".join(texts)
                await say(event, "⏳ <b>Summarizing</b>…", name="summarize",
                          parse_mode="html")

                # Chat text stays local: Telegram data is never sent to a model
                summary = summarize_locally(combined, max_sentences=7, max_chars=2000)
                output = (f"📝 <b>Chat Summary</b> "
                          f"<i>(local, last {len(messages)} messages)</i>\n\n"
                          f"<blockquote>{brand.esc(summary)}</blockquote>")

                if len(output) > 4000:
                    import io
                    bio = io.BytesIO(brand.plain(output).encode("utf-8"))
                    bio.name = "summary.txt"
                    await client.send_file(
                        await tgsend.peer(event), bio,
                        caption=brand.sign("📝 <b>Chat Summary</b>",
                                           "summarize"),
                        parse_mode="html")
                    await event.delete()
                else:
                    await say(event, output, name="summarize",
                              parse_mode="html")
                return

            # Text summarization
            text = arg_str
            from_reply = False
            if not text and event.is_reply:
                reply = await event.get_reply_message()
                text = reply.text or reply.raw_text
                from_reply = True
            if not text:
                await say(event,
                          "❌ No text provided. Use "
                          "<code>!summarize &lt;text&gt;</code> or reply to a "
                          "message.",
                          name="summarize", parse_mode="html")
                return

            await say(event, "⏳ <b>Summarizing</b>…", name="summarize",
                      parse_mode="html")

            # A typed message may go to Gemini; a Telegram reply stays local
            summary = None if from_reply else await summarize_with_gemini(text)
            if summary:
                output = (f"📝 <b>Summary</b>\n\n"
                          f"<blockquote>{brand.esc(summary)}</blockquote>")
            else:
                summary = summarize_locally(text, max_sentences=5, max_chars=2000)
                output = (f"📝 <b>Summary</b> <i>(local)</i>\n\n"
                          f"<blockquote>{brand.esc(summary)}</blockquote>")

            if len(output) > 4000:
                import io
                bio = io.BytesIO(brand.plain(output).encode("utf-8"))
                bio.name = "summary.txt"
                await client.send_file(
                    await tgsend.peer(event), bio,
                    caption=brand.sign("📝 <b>Summary</b>", "summarize"),
                    parse_mode="html")
                await event.delete()
            else:
                await say(event, output, name="summarize", parse_mode="html")

        except Exception as e:
            await say(event, f"❌ <b>Error</b> · <code>{brand.esc(e)}</code>",
                      name="summarize", parse_mode="html")