# Com/crypto.py
import aiohttp
from telethon import events

__HELP__ = "!crypto <coin> → Show crypto price and 24h changes"


def setup(client, my_id):

    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!crypto\s+(\w+)"))
    async def crypto(event):
        try:
            coin = event.pattern_match.group(1).lower()

            async with aiohttp.ClientSession() as session:
                url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={coin}"
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await event.reply(
                            f"❌ Failed to fetch data. Status code: {resp.status}"
                        )
                        return
                    data = await resp.json()

            if not data:
                await event.reply(f"❌ Coin '{coin}' not found!")
                return

            coin_data = data[0]
            name = coin_data.get("name", "N/A")
            symbol = coin_data.get("symbol", "N/A").upper()
            price = coin_data.get("current_price", "N/A")
            change_24h = coin_data.get("price_change_percentage_24h", "N/A")
            market_cap = coin_data.get("market_cap", "N/A")
            volume = coin_data.get("total_volume", "N/A")

            message = (f"💰 {name} ({symbol})\n"
                       f"Price: ${price}\n"
                       f"24h Change: {change_24h}%\n"
                       f"Market Cap: ${market_cap}\n"
                       f"24h Volume: ${volume}")

            await event.reply(message)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
