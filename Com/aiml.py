"""!aiml commands: train a Markov model on chat history and generate replies from it."""
import os
import sys
import random
from telethon import events
import Com.core.tgsend as tgsend
from Com.core import brand
from Com.core.reply import say

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ML.smart_markov import SmartMarkov

__HELP__ = (
    "!aiml train [N] → Train Markov model on last N messages (default 500, max 10000).\n"
    "   - Instant training, uses 4‑gram Markov chain.\n"
    "   - Generates coherent sentences from real message fragments.\n"
    "!aiml generate <seed> → Generate text from a seed phrase.\n"
    "!aiml status → Show model stats.\n"
    "!aiml reset → Delete the model for this chat."
)
__CATEGORY__ = "AI"

MODEL_DIR = "ML/models"
os.makedirs(MODEL_DIR, exist_ok=True)

def get_model_path(chat_id):
    return os.path.join(MODEL_DIR, f"markov_{chat_id}.json")

async def fetch_messages(client, peer, limit=500):
    """Collect only the text of recent messages.

    iter_messages streams one message at a time. get_messages(limit=N) built the
    whole list of Message objects (text, entities, media) in memory first, which
    is a lot of RAM for a 10k-message train on a shared Repl where the training
    data is the same size either way.
    """
    texts = []
    try:
        async for message in client.iter_messages(peer, limit=limit):
            if message.text and not message.text.startswith("!"):
                texts.append(message.text)
    except Exception as e:
        return None, str(e)
    return texts, None

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml train(?:\s+(\d+))?$"))
    async def aiml_train(event):
        limit = 500
        arg = event.pattern_match.group(1)
        if arg:
            try:
                limit = int(arg)
                if limit < 10: limit = 10
                if limit > 10000: limit = 10000
            except:
                pass
        await say(event,
                  f"🧠 <b>Training</b> on the last <code>{limit}</code> messages "
                  "(instant).",
                  name="aiml", parse_mode="html")

        texts, err = await fetch_messages(client, await tgsend.peer(event), limit)
        if err:
            await say(event,
                      f"❌ Failed to fetch messages · <code>{brand.esc(err)}</code>",
                      name="aiml", parse_mode="html")
            return
        if not texts:
            await say(event, "❌ No text messages found.", name="aiml")
            return

        mc = SmartMarkov(order=4)
        mc.train(texts)
        mc.save(get_model_path(event.chat_id))

        stats = mc.get_stats()
        await say(event,
                  "✅ <b>Training complete</b>\n"
                  f"Transitions · <code>{stats['total_transitions']}</code>\n"
                  f"Unique states · <code>{stats['unique_states']}</code>\n"
                  f"Total words · <code>{stats['total_words']}</code>",
                  name="aiml", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml generate\s+(.+)$"))
    async def aiml_generate(event):
        chat_id = event.chat_id
        model_path = get_model_path(chat_id)
        if not os.path.exists(model_path):
            await say(event,
                      "❌ No model trained yet. Use <code>!aiml train</code> first.",
                      name="aiml", parse_mode="html")
            return

        seed = event.pattern_match.group(1).strip()
        mc = SmartMarkov.load(model_path)
        generated = mc.generate(seed, max_words=25)

        if not generated:
            generated = "I don't have enough data to continue that thought."

        await client.send_message(
            await tgsend.peer(event),
            brand.sign(f"🧠 <b>AI generated</b>\n{brand.esc(generated)}", "aiml"),
            reply_to=event.id, parse_mode="html")
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml status$"))
    async def aiml_status(event):
        chat_id = event.chat_id
        model_path = get_model_path(chat_id)
        if not os.path.exists(model_path):
            await say(event, "❌ No model trained.", name="aiml")
            return
        mc = SmartMarkov.load(model_path)
        stats = mc.get_stats()
        await say(event,
                  "📊 <b>Model Stats</b>\n"
                  "Order · <code>4</code>\n"
                  f"Transitions · <code>{stats['total_transitions']}</code>\n"
                  f"Unique states · <code>{stats['unique_states']}</code>\n"
                  f"Total words · <code>{stats['total_words']}</code>",
                  name="aiml", parse_mode="html")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml reset$"))
    async def aiml_reset(event):
        chat_id = event.chat_id
        model_path = get_model_path(chat_id)
        if os.path.exists(model_path):
            os.remove(model_path)
            await say(event, "✅ <b>Model reset</b> for this chat.",
                      name="aiml", parse_mode="html")
        else:
            await say(event, "❌ No model to reset.", name="aiml")
        await event.delete()