"""`!ping` -- measure the round trip to Telegram.

The first edit is the measurement and the second is the answer, so the number
the owner sees is the time they actually waited, not a loopback timer. Both
messages carry the Spooku Self signature: a command that answers in 300 ms
should still look like the product.
"""
import time

from telethon import events

from Com.core import brand

__HELP__ = "!ping → Shows the bot's latency"
__CATEGORY__ = "Setup"


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!ping$"))
    async def ping(event):
        start = time.time()
        msg = await event.edit(
            brand.sign("⏳ <b>Pinging…</b>", "ping"), parse_mode="html"
        )
        latency = int((time.time() - start) * 100)
        await msg.edit(
            brand.sign(f"🏓 <b>Pong</b> · <code>{latency} ms</code>", "ping"),
            parse_mode="html",
        )
