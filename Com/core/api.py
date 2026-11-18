"""One shared, cached, rate-limit-aware HTTP layer for every command module.

Why this module exists
----------------------
Before it, each command opened its own ``aiohttp.ClientSession`` per call, had
no timeout policy worth the name, ignored HTTP 429 and cached nothing. On
Replit's free tier a public API answering 429 or timing out produced either a
raw exception string in the chat or a silent empty result -- and every one of
those calls was made again on the next invocation.

What it provides
----------------
* a single reusable ``ClientSession`` (created lazily, inside the running loop)
* a small TTL cache, because free APIs are rate limited and the data the bot
  asks for (prices, geolocation, wiki pages) changes slowly
* explicit ``APIError`` / ``RateLimited`` exceptions that carry the HTTP status
  and the server's ``Retry-After`` when one was sent
* ``first_success()`` for provider fallback chains
* a bounded retry policy: one retry on 5xx / timeout / socket error, none on
  429 (retrying a rate limit makes it worse)

Nothing in here raises anything other than ``APIError`` subclasses, so a dead
or throttled API can never propagate into the Telethon client and take the
self-bot down with it.

This module has no ``setup()`` and no ``__HELP__``: main.py imports it during
the command scan and registers nothing for it.
"""
import asyncio
import json
import logging
import time
from urllib.parse import urlencode

import aiohttp

log = logging.getLogger("selftg.api")

DEFAULT_TIMEOUT = 12
CACHE_MAX_ENTRIES = 256
USER_AGENT = "SelfTG/1.0 (+https://github.com/HexploitTeam/SelfTG)"

_session = None
_session_lock = None
_cache = {}  # key -> (expires_at, value)


#------------------------------
#Errors
#------------------------------

class APIError(Exception):
    """A failed upstream call. Always safe to show to the user."""

    def __init__(self, message, *, status=None, provider=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.provider = provider
        self.retry_after = retry_after

    def describe(self):
        bits = [self.provider or "API", str(self)]
        if self.status:
            bits.append(f"HTTP {self.status}")
        if self.retry_after:
            bits.append(f"retry in {self.retry_after}s")
        return " · ".join(bits)


class RateLimited(APIError):
    """HTTP 429 or a provider-specific quota code."""


#------------------------------
#Session and cache
#------------------------------

def _get_lock():
    global _session_lock
    if _session_lock is None:
        _session_lock = asyncio.Lock()
    return _session_lock


async def get_session():
    """Return the shared session, creating it on first use."""
    global _session
    async with _get_lock():
        if _session is None or _session.closed:
            _session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT),
                headers={"User-Agent": USER_AGENT},
            )
        return _session


async def close_session():
    """Close the shared session (used by tests and graceful shutdown)."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


def _cache_key(url, params):
    if not params:
        return url
    return url + "?" + urlencode(sorted(params.items()))


def _cache_get(key):
    entry = _cache.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if expires_at and expires_at < time.monotonic():
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key, value, ttl):
    if ttl <= 0:
        return
    if len(_cache) >= CACHE_MAX_ENTRIES:
        # Cheap eviction: drop the entries that expire first.
        for stale_key, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[:32]:
            _cache.pop(stale_key, None)
    _cache[key] = (time.monotonic() + ttl, value)


def clear_cache():
    _cache.clear()


def _retry_after(headers):
    for name in ("Retry-After", "X-RateLimit-Reset"):
        raw = headers.get(name)
        if not raw:
            continue
        try:
            return max(0, int(float(raw)))
        except (TypeError, ValueError):
            continue
    return None


async def _request(method, url, *, params=None, json_body=None, data=None,
                   headers=None, timeout=None, retries=1, provider="unknown"):
    """Perform one HTTP call and return the raw body bytes."""
    session = await get_session()
    timeout_obj = aiohttp.ClientTimeout(total=timeout or DEFAULT_TIMEOUT)
    last_error = None

    for attempt in range(retries + 1):
        try:
            async with session.request(
                method, url, params=params, json=json_body, data=data,
                headers=headers, timeout=timeout_obj,
            ) as resp:
                body = await resp.read()
                if resp.status == 429:
                    raise RateLimited(
                        "rate limit reached",
                        status=429,
                        provider=provider,
                        retry_after=_retry_after(resp.headers),
                    )
                if resp.status >= 500:
                    last_error = APIError(
                        "server error", status=resp.status, provider=provider
                    )
                    if attempt < retries:
                        await asyncio.sleep(1.0 + attempt)
                        continue
                    raise last_error
                if resp.status >= 400:
                    raise APIError(
                        f"request rejected ({resp.status})",
                        status=resp.status,
                        provider=provider,
                    )
                return body
        except asyncio.TimeoutError:
            last_error = APIError("timed out", provider=provider)
        except aiohttp.ClientError as exc:
            last_error = APIError(
                f"network error ({type(exc).__name__})", provider=provider
            )
        except RateLimited:
            raise
        if attempt < retries:
            await asyncio.sleep(1.0 + attempt)

    raise last_error or APIError("request failed", provider=provider)


def _decode_json(body, provider):
    try:
        return json.loads(body)
    except ValueError:
        raise APIError("returned something that is not JSON", provider=provider) from None


#------------------------------
#Public helpers
#------------------------------

async def fetch_json(url, *, params=None, provider="unknown", cache_ttl=0,
                     timeout=None, retries=1, headers=None):
    """GET `url` and return parsed JSON, optionally cached for `cache_ttl` s."""
    key = _cache_key(url, params)
    if cache_ttl:
        cached = _cache_get(key)
        if cached is not None:
            return cached
    body = await _request(
        "GET", url, params=params, headers=headers, timeout=timeout,
        retries=retries, provider=provider,
    )
    value = _decode_json(body, provider)
    _cache_set(key, value, cache_ttl)
    return value


async def fetch_text(url, *, params=None, provider="unknown", cache_ttl=0,
                     timeout=None, retries=1, headers=None):
    key = _cache_key(url, params)
    if cache_ttl:
        cached = _cache_get(key)
        if cached is not None:
            return cached
    body = await _request(
        "GET", url, params=params, headers=headers, timeout=timeout,
        retries=retries, provider=provider,
    )
    value = body.decode("utf-8", errors="replace")
    _cache_set(key, value, cache_ttl)
    return value


async def fetch_bytes(url, *, params=None, provider="unknown", timeout=None,
                      retries=0, headers=None):
    return await _request(
        "GET", url, params=params, headers=headers, timeout=timeout,
        retries=retries, provider=provider,
    )


async def post_json(url, payload, *, provider="unknown", timeout=None,
                    headers=None, retries=0, data=None):
    merged = {"Accept": "application/json"}
    if headers:
        merged.update(headers)
    body = await _request(
        "POST", url, json_body=payload if data is None else None, data=data,
        headers=merged, timeout=timeout, retries=retries, provider=provider,
    )
    return _decode_json(body, provider)


async def post_form(url, form, *, provider="unknown", timeout=None,
                    headers=None, retries=0):
    """POST a multipart form (aiohttp.FormData) and return the raw body."""
    merged = {"Accept": "*/*"}
    if headers:
        merged.update(headers)
    return await _request(
        "POST", url, data=form, headers=merged, timeout=timeout,
        retries=retries, provider=provider,
    )


async def first_success(attempts):
    """Try providers in order and return the first non-exception result.

    `attempts` is a list of ``(label, callable_returning_awaitable)``. The
    callables are invoked lazily so a working first provider costs nothing.
    """
    failures = []
    for label, factory in attempts:
        try:
            result = await factory()
        except RateLimited as exc:
            failures.append(f"{label}: {exc.describe()}")
            log.info("fallback chain: %s rate limited (%s)", label, exc.describe())
            continue
        except (APIError, asyncio.TimeoutError, ValueError, KeyError) as exc:
            failures.append(f"{label}: {type(exc).__name__}")
            log.info("fallback chain: %s failed (%s)", label, exc)
            continue
        if result:
            return result
        failures.append(f"{label}: empty result")
    raise APIError("; ".join(failures) or "no provider configured")


def describe(exc):
    """Short user-facing text for an API failure."""
    if isinstance(exc, APIError):
        return exc.describe()
    return f"{type(exc).__name__}: {exc}"
