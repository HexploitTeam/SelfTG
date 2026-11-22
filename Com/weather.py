"""`!weather` -- current conditions and a short forecast from free, keyless APIs.

Providers (both free, no API key, no credit card):
  * Open-Meteo  -- geocoding + forecast, ~10k requests/day per IP, no signup.
  * wttr.in     -- plain-text/JSON fallback, best-effort and heavily cached.

Geocoding results are cached for 24h and forecasts for 10 minutes: a city's
coordinates never change and weather does not change faster than that, so the
free quota is only spent when the data is actually new.
"""
import logging

from telethon import events

from Com.core import brand
from Com.core.reply import say
import Com.core.api as api

__HELP__ = (
    "!weather <city> → Current weather and a 3-day outlook (Open-Meteo, no key)\n"
    "Example: !weather Tehran   |   !weather Berlin"
)
__CATEGORY__ = "Information"

log = logging.getLogger("selftg.weather")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
WTTR_URL = "https://wttr.in/{city}?format=j1"

#------------------------------
#Data
#------------------------------

# WMO weather interpretation codes used by Open-Meteo.
WMO = {
    0: ("☀️", "clear sky"),
    1: ("🌤️", "mainly clear"),
    2: ("⛅", "partly cloudy"),
    3: ("☁️", "overcast"),
    45: ("🌫️", "fog"),
    48: ("🌫️", "depositing rime fog"),
    51: ("🌦️", "light drizzle"),
    53: ("🌦️", "drizzle"),
    55: ("🌦️", "dense drizzle"),
    56: ("🌧️", "freezing drizzle"),
    57: ("🌧️", "dense freezing drizzle"),
    61: ("🌦️", "light rain"),
    63: ("🌧️", "rain"),
    65: ("🌧️", "heavy rain"),
    66: ("🌧️", "freezing rain"),
    67: ("🌧️", "heavy freezing rain"),
    71: ("🌨️", "light snow"),
    73: ("🌨️", "snow"),
    75: ("❄️", "heavy snow"),
    77: ("❄️", "snow grains"),
    80: ("🌦️", "light showers"),
    81: ("🌧️", "showers"),
    82: ("⛈️", "violent showers"),
    85: ("🌨️", "snow showers"),
    86: ("❄️", "heavy snow showers"),
    95: ("⛈️", "thunderstorm"),
    96: ("⛈️", "thunderstorm with hail"),
    99: ("⛈️", "severe thunderstorm with hail"),
}


def describe_code(code):
    return WMO.get(int(code), ("🌡️", f"weather code {code}"))


#------------------------------
#Providers
#------------------------------

async def _geocode(city):
    data = await api.fetch_json(
        GEOCODE_URL,
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        provider="open-meteo geocoding",
        cache_ttl=24 * 3600,
        timeout=10,
    )
    results = data.get("results") or []
    if not results:
        raise api.APIError(f"no place called {city!r} found", provider="open-meteo geocoding")
    hit = results[0]
    return (
        hit["latitude"],
        hit["longitude"],
        hit.get("name") or city,
        hit.get("country") or "",
    )


async def _open_meteo(city):
    lat, lon, name, country = await _geocode(city)
    data = await api.fetch_json(
        FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                       "precipitation,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 3,
        },
        provider="open-meteo forecast",
        cache_ttl=600,
        timeout=10,
    )

    current = data.get("current") or {}
    emoji, label = describe_code(current.get("weather_code", -1))
    lines = [
        f"{emoji} <b>{brand.esc(name)}"
        f"{brand.esc(', ' + country) if country else ''}</b>",
        f"{brand.esc(label)} · "
        f"<code>{current.get('temperature_2m', '?')}°C</code> "
        f"(feels <code>{current.get('apparent_temperature', '?')}°C</code>)",
        f"💧 <b>Humidity</b> "
        f"<code>{current.get('relative_humidity_2m', '?')}%</code> · "
        f"🌬️ <b>Wind</b> <code>{current.get('wind_speed_10m', '?')} km/h</code> · "
        f"🌧️ <b>Precip</b> "
        f"<code>{current.get('precipitation', '?')} mm</code>",
    ]

    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    if dates:
        lines.append("")
        for index, day in enumerate(dates[:3]):
            day_emoji, day_label = describe_code(
                (daily.get("weather_code") or [0])[index]
            )
            lines.append(
                f"<code>{brand.esc(day)}</code> {day_emoji} "
                f"<code>{daily.get('temperature_2m_min', ['?'])[index]}…"
                f"{daily.get('temperature_2m_max', ['?'])[index]}°C</code>, "
                f"{brand.esc(day_label)}, rain "
                f"{daily.get('precipitation_probability_max', ['?'])[index]}%"
            )
    lines.append("\n<i>source: Open-Meteo (free, no key)</i>")
    return "\n".join(lines)


async def _wttr(city):
    data = await api.fetch_json(
        WTTR_URL.format(city=api_url_quote(city)),
        provider="wttr.in",
        cache_ttl=600,
        timeout=12,
    )
    current = (data.get("current_condition") or [{}])[0]
    desc = (current.get("weatherDesc") or [{}])[0].get("value", "unknown")
    lines = [
        f"🌡️ <b>{brand.esc(city)}</b> (wttr.in fallback)",
        f"{brand.esc(desc)} · <code>{current.get('temp_C', '?')}°C</code> "
        f"(feels <code>{current.get('FeelsLikeC', '?')}°C</code>)",
        f"💧 <b>Humidity</b> <code>{current.get('humidity', '?')}%</code> · "
        f"🌬️ <b>Wind</b> <code>{current.get('windspeedKmph', '?')} km/h</code>",
        "\n<i>source: wttr.in (free, no key)</i>",
    ]
    return "\n".join(lines)


def api_url_quote(text):
    from urllib.parse import quote
    return quote(text, safe="")


async def get_weather(city):
    """Open-Meteo first, wttr.in second. Raises APIError only if both fail."""
    try:
        return await _open_meteo(city)
    except api.APIError as exc:
        log.info("weather: Open-Meteo failed (%s), trying wttr.in", exc.describe())
    except Exception as exc:  # noqa: BLE001
        log.info("weather: Open-Meteo crashed (%s), trying wttr.in", type(exc).__name__)
    return await _wttr(city)


#------------------------------
#Command handlers
#------------------------------

def setup(client, my_id):
    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!weather(?:\s+([\s\S]+))?$"))
    async def weather_cmd(event):
        city = (event.pattern_match.group(1) or "").strip()
        if not city:
            await say(
                event,
                "Usage: <code>!weather &lt;city&gt;</code> — e.g. "
                "<code>!weather Tehran</code>",
                name="weather",
                parse_mode="html",
            )
            return
        await say(
            event,
            f"🌍 <b>Looking up weather</b> for {brand.esc(city)}…",
            name="weather",
            parse_mode="html",
        )
        try:
            report = await get_weather(city)
        except api.APIError as exc:
            await say(
                event,
                f"❌ <b>Weather unavailable.</b> {brand.esc(exc.describe())}.\n"
                "Both free providers failed or are rate limited — try again in a "
                "minute.",
                name="weather",
                parse_mode="html",
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("weather: unexpected failure")
            await say(
                event,
                f"❌ <b>{brand.esc(type(exc).__name__)}</b> · {brand.esc(exc)}",
                name="weather",
                parse_mode="html",
            )
            return
        await say(event, report, name="weather", parse_mode="html")
