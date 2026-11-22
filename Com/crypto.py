"""`!crypto` -- prices from free, keyless providers with a fallback chain.

Old behaviour: one CoinPaprika call per invocation, a fresh TCP session each
time, no cache, and a raw exception string on failure.

New behaviour:
  * CoinGecko public API first (no key, ~5-15 req/min per IP),
  * CoinPaprika second (no key, ~10 req/min) if CoinGecko throttles or is down,
  * 60s cache, so asking for the same coin five times in a minute costs one
    upstream request,
  * 429 / timeout / server errors surface as a readable message, never as a
    traceback in the chat.
"""
import logging

from telethon import events

import Com.core.api as api
from Com.core import brand
from Com.core.reply import say

__HELP__ = "!crypto <coin> → Show crypto price and 24h changes (CoinGecko → CoinPaprika)"
__CATEGORY__ = "Utilities"

log = logging.getLogger("selftg.crypto")

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
COINPAPRIKA_URL = "https://api.coinpaprika.com/v1/tickers/{id}"

CACHE_TTL = 60  # seconds; prices do not need to be fresher than that

# ticker -> (coingecko id, coinpaprika id)
COINS = {
    "btc": ("bitcoin", "btc-bitcoin"),
    "eth": ("ethereum", "eth-ethereum"),
    "sol": ("solana", "sol-solana"),
    "xrp": ("ripple", "xrp-xrp"),
    "ada": ("cardano", "ada-cardano"),
    "doge": ("dogecoin", "doge-dogecoin"),
    "dot": ("polkadot", "dot-polkadot"),
    "link": ("chainlink", "link-chainlink"),
    "ltc": ("litecoin", "ltc-litecoin"),
    "bch": ("bitcoin-cash", "bch-bitcoin-cash"),
    "atom": ("cosmos", "atom-cosmos"),
    "uni": ("uniswap", "uni-uniswap"),
    "avax": ("avalanche-2", "avax-avalanche"),
    "matic": ("matic-network", "matic-polygon"),
    "trx": ("tron", "trx-tron"),
    "ton": ("the-open-network", "ton-toncoin"),
    "near": ("near", "near-near-protocol"),
    "shib": ("shiba-inu", "shib-shiba-inu"),
}


def _fmt_price(value):
    if not isinstance(value, (int, float)):
        return "N/A"
    return f"{value:,.2f}" if value >= 1000 else f"{value:.8f}"


def _fmt_change(value):
    if not isinstance(value, (int, float)):
        return "N/A"
    return f"{value:+.2f}%"


def _fmt_big(value):
    if not isinstance(value, (int, float)):
        return "N/A"
    return f"{value:,.0f}"


def render(name, symbol, price, change_1h, change_24h, change_7d,
           market_cap, volume_24h, source):
    lines = [
        f"💰 <b>{brand.esc(name)} ({brand.esc(symbol)})</b>",
        f"💵 Price · <code>{_fmt_price(price)}</code>",
        f"📈 1h · <code>{_fmt_change(change_1h)}</code> · "
        f"24h · <code>{_fmt_change(change_24h)}</code> · "
        f"7d · <code>{_fmt_change(change_7d)}</code>",
        f"🏦 Market cap · <code>{_fmt_big(market_cap)}</code>",
        f"📊 24h volume · <code>{_fmt_big(volume_24h)}</code>",
        f"<i>source: {brand.esc(source)}, cached {CACHE_TTL}s</i>",
    ]
    return "\n".join(lines)


#------------------------------
#Providers
#------------------------------

async def _coingecko(coin_id, ticker):
    data = await api.fetch_json(
        COINGECKO_URL,
        params={
            "ids": coin_id,
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_market_cap": "true",
            "include_24hr_vol": "true",
        },
        provider="coingecko",
        cache_ttl=CACHE_TTL,
        timeout=10,
    )
    quotes = data.get(coin_id) or {}
    if not quotes:
        raise api.APIError(f"unknown coin id {coin_id!r}", provider="coingecko")
    return render(
        coin_id.replace("-", " ").title(),
        ticker.upper(),
        quotes.get("usd"),
        None,  # CoinGecko's simple/price has no 1h/7d delta
        quotes.get("usd_24h_change"),
        None,
        quotes.get("usd_market_cap"),
        quotes.get("usd_24h_vol"),
        "CoinGecko",
    )


async def _coinpaprika(paprika_id, ticker):
    data = await api.fetch_json(
        COINPAPRIKA_URL.format(id=paprika_id),
        provider="coinpaprika",
        cache_ttl=CACHE_TTL,
        timeout=10,
    )
    quotes = (data.get("quotes") or {}).get("USD") or {}
    return render(
        data.get("name") or paprika_id,
        (data.get("symbol") or ticker).upper(),
        quotes.get("price"),
        quotes.get("percent_change_1h"),
        quotes.get("percent_change_24h"),
        quotes.get("percent_change_7d"),
        quotes.get("market_cap"),
        quotes.get("volume_24h"),
        "CoinPaprika",
    )


async def get_quote(ticker):
    """CoinGecko first, CoinPaprika second. Raises APIError if both fail."""
    ticker = ticker.lower()
    coingecko_id, paprika_id = COINS.get(ticker, (ticker, ticker))
    return await api.first_success([
        ("coingecko", lambda: _coingecko(coingecko_id, ticker)),
        ("coinpaprika", lambda: _coinpaprika(paprika_id, ticker)),
    ])


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!crypto\s+(\w+)"))
    async def crypto(event):
        ticker = event.pattern_match.group(1).lower()
        try:
            message = await get_quote(ticker)
        except api.APIError as exc:
            await _reply(
                event,
                f"❌ <b>Could not get a price for</b> "
                f"<code>{brand.esc(ticker)}</code>\n"
                f"Both free providers failed · {brand.esc(exc)}\n"
                f"Known tickers · {', '.join(sorted(COINS))}",
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("crypto: unexpected failure")
            await _reply(event, f"❌ <code>{brand.esc(type(exc).__name__)}</code> · {brand.esc(exc)}")
            return
        await _reply(event, message)

    async def _reply(event, text):
        # Edit-then-reply is shared: see Com/core/reply.py.
        await say(event, text, name="crypto", parse_mode="html")
