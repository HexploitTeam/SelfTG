# Com/aiml.py
import os
import sys
import random
from telethon import events
import Com.tgsend as tgsend

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
        await event.edit(f"🧠 Training on last {limit} messages... (instant)")

        texts, err = await fetch_messages(client, await tgsend.peer(event), limit)
        if err:
            await event.edit(f"❌ Failed to fetch messages: {err}")
            return
        if not texts:
            await event.edit("❌ No text messages found.")
            return

        mc = SmartMarkov(order=4)
        mc.train(texts)
        mc.save(get_model_path(event.chat_id))

        stats = mc.get_stats()
        await event.edit(f"✅ Training complete!\n"
                         f"Total transitions: {stats['total_transitions']}\n"
                         f"Unique states: {stats['unique_states']}\n"
                         f"Total words: {stats['total_words']}")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml generate\s+(.+)$"))
    async def aiml_generate(event):
        chat_id = event.chat_id
        model_path = get_model_path(chat_id)
        if not os.path.exists(model_path):
            await event.edit("❌ No model trained yet. Use `!aiml train` first.")
            return

        seed = event.pattern_match.group(1).strip()
        mc = SmartMarkov.load(model_path)
        generated = mc.generate(seed, max_words=25)

        if not generated:
            generated = "I don't have enough data to continue that thought."

        await client.send_message(await tgsend.peer(event), f"🧠 **AI generated:**\n{generated}", reply_to=event.id)
        await event.delete()

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml status$"))
    async def aiml_status(event):
        chat_id = event.chat_id
        model_path = get_model_path(chat_id)
        if not os.path.exists(model_path):
            await event.edit("❌ No model trained.")
            return
        mc = SmartMarkov.load(model_path)
        stats = mc.get_stats()
        await event.edit(f"📊 **Model Stats**\n"
                         f"Order: 4\n"
                         f"Total transitions: {stats['total_transitions']}\n"
                         f"Unique states: {stats['unique_states']}\n"
                         f"Total words: {stats['total_words']}")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!aiml reset$"))
    async def aiml_reset(event):
        chat_id = event.chat_id
        model_path = get_model_path(chat_id)
        if os.path.exists(model_path):
            os.remove(model_path)
            await event.edit("✅ Model reset for this chat.")
        else:
            await event.edit("❌ No model to reset.")
        await event.delete()