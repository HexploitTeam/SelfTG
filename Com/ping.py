from telethon import events
import time

__HELP__ = "!ping → Shows the bot's latency"
__CATEGORY__ = "Setup"

def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!ping$"))
    async def ping(event):
        start = time.time()
        msg = await event.edit("Pinging...")
        end = time.time()
        latency = int((end - start) * 100)
        await msg.edit(f"Latency: {latency}ms")
