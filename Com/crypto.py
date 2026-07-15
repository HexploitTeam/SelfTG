# Com/crypto.py
import aiohttp
from telethon import events

__HELP__ = "!crypto <coin> → Show crypto price and 24h changes"
__CATEGORY__ = "Utilities"

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id,
                                 pattern=r"^!crypto\s+(\w+)"))
    async def crypto(event):
        try:
            coin = event.pattern_match.group(1).lower()

            # Map common tickers to CoinPaprika IDs
            ticker_map = {
                "btc": "btc-bitcoin",
                "eth": "eth-ethereum",
                "sol": "sol-solana",
                "xrp": "xrp-xrp",
                "ada": "ada-cardano",
                "doge": "doge-dogecoin",
                "dot": "dot-polkadot",
                "link": "link-chainlink",
                "ltc": "ltc-litecoin",
                "bch": "bch-bitcoin-cash",
                "atom": "atom-cosmos",
                "uni": "uni-uniswap",
                "avax": "avax-avalanche",
                "matic": "matic-polygon",
            }

            paprika_id = ticker_map.get(coin, coin)

            async with aiohttp.ClientSession() as session:
                url = f"https://api.coinpaprika.com/v1/tickers/{paprika_id}"
                async with session.get(url) as resp:
                    if resp.status == 404:
                        await event.reply(
                            f"❌ Coin '{coin}' not found.\n"
                            "💡 Try the full name (e.g., 'bitcoin', 'ethereum') or one of:\n"
                            f"   {', '.join(ticker_map.keys())}"
                        )
                        return
                    if resp.status != 200:
                        await event.reply(
                            f"❌ API error (status {resp.status}). Try again later."
                        )
                        return
                    data = await resp.json()

            name = data.get("name", "Unknown")
            symbol = data.get("symbol", "").upper()
            quotes = data.get("quotes", {}).get("USD", {})
            price = quotes.get("price", "N/A")
            change_1h = quotes.get("percent_change_1h", "N/A")
            change_24h = quotes.get("percent_change_24h", "N/A")
            change_7d = quotes.get("percent_change_7d", "N/A")
            market_cap = quotes.get("market_cap", "N/A")
            volume_24h = quotes.get("volume_24h", "N/A")

            def fmt_price(n):
                if n == "N/A" or not isinstance(n, (int, float)):
                    return "N/A"
                if n >= 1000:
                    return f"{n:,.2f}"
                return f"{n:.8f}"

            def fmt_change(n):
                if n == "N/A" or not isinstance(n, (int, float)):
                    return "N/A"
                return f"{n:+.2f}%"

            def fmt_big(n):
                if n == "N/A" or not isinstance(n, (int, float)):
                    return "N/A"
                return f"{n:,.0f}"

            message = (
                f"💰 **{name} ({symbol})**\n"
                f"💵 Price: `${fmt_price(price)}`\n"
                f"📈 1h: `{fmt_change(change_1h)}` • 24h: `{fmt_change(change_24h)}` • 7d: `{fmt_change(change_7d)}`\n"
                f"🏦 Market Cap: `${fmt_big(market_cap)}`\n"
                f"📊 24h Volume: `${fmt_big(volume_24h)}`"
            )

            await event.reply(message)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")