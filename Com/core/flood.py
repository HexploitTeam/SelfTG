"""Rate limiting for the commands that send more than one message per command.

Why this module exists
----------------------
Telethon already sleeps through short FLOOD_WAITs (``flood_sleep_threshold``),
but that protects one *request*, not a *series*: `!kill 20`, `!repeat 20`,
`!f start` and `!setkill` emit messages on a fixed interval inside one command.
A fixed interval is the pattern Telegram's anti-spam is looking for, and when a
burst does trip FLOOD_WAIT there was nothing to stop the next burst.

Three rules, in one place, so they cannot drift apart:

* :func:`pace` -- every message in a series waits a jittered gap, per chat.
* :func:`note_flood` -- a FLOOD_WAIT is recorded; enough of them inside the
  window opens the breaker, which refuses to send at all for a cooldown.
* :func:`cooldown_left` -- the visible consequence: the command stops and says
  how long, instead of retrying into a longer penalty.

The numbers are deliberately slow. Nothing in this project needs to be fast and
the account is the thing at risk, so the defaults add seconds, never remove them.

This module has no ``setup()`` and no ``__HELP__``.
"""
import asyncio
import logging
import random
import time

log = logging.getLogger("selftg.flood")

MIN_GAP = 1.0            # seconds between two messages of one series
JITTER = 0.3             # +/- 30 %, so no two gaps are identical
FLOOD_WINDOW = 600       # a flood older than this no longer counts
FLOOD_LIMIT = 3          # floods inside the window before the breaker opens
BREAKER_COOLDOWN = 900   # how long sending stays paused once it opens

_last_send = {}   # chat_id -> monotonic time of the last message we sent
_floods = []      # monotonic timestamps of recent FLOOD_WAITs
_open_until = 0.0


#------------------------------
#Pacing
#------------------------------

def _gap(gap):
    """`gap` with symmetric jitter, never below one second."""
    spread = gap * JITTER
    return max(1.0, random.uniform(gap - spread, gap + spread))


async def pace(chat_id, gap=MIN_GAP):
    """Wait until the next message to `chat_id` may be sent.

    Called *before* each message of a series. The state is per chat because two
    different chats are two different rate buckets on Telegram's side, and one
    chat's slow series must not stall the other.
    """
    now = time.monotonic()
    due = _last_send.get(chat_id, 0.0) + _gap(gap)
    if due > now:
        await asyncio.sleep(due - now)
    _last_send[chat_id] = time.monotonic()


def forget(chat_id):
    """Drop one chat's pacing state (used when a series ends)."""
    _last_send.pop(chat_id, None)


#------------------------------
#Breaker
#------------------------------

def _prune(now):
    global _floods
    _floods = [stamp for stamp in _floods if now - stamp <= FLOOD_WINDOW]


def cooldown_left():
    """Seconds sending stays paused; 0 when the breaker is closed."""
    return max(0, int(round(_open_until - time.monotonic())))


def is_open():
    return cooldown_left() > 0


def note_flood(seconds=0):
    """Record one FLOOD_WAIT; returns the breaker's cooldown in seconds (0 if closed).

    `seconds` is the wait Telegram asked for. The breaker never opens for *less*
    time than that, or the next send would walk straight back into the same
    penalty.
    """
    global _open_until, _floods
    now = time.monotonic()
    _floods.append(now)
    _prune(now)

    if len(_floods) < FLOOD_LIMIT:
        log.info("flood: %d/%d floods in the window", len(_floods), FLOOD_LIMIT)
        return 0

    cooldown = max(BREAKER_COOLDOWN, int(seconds or 0))
    _open_until = max(_open_until, now + cooldown)
    _floods = []
    log.warning("flood: breaker open for %ds after %d waits", cooldown, FLOOD_LIMIT)
    return cooldown


def reset():
    """Close the breaker and forget the history (tests, and a manual unstick)."""
    global _open_until, _floods
    _open_until = 0.0
    _floods = []
    _last_send.clear()


def describe(seconds):
    """One user-facing line for a command that has to stop sending."""
    return (
        f"⏸ Sending paused for {seconds}s after {FLOOD_LIMIT} flood waits. "
        "Nothing is retried automatically."
    )
