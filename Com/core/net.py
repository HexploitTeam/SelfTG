"""Telegram transport settings for Replit.

Replit does not allow arbitrary outbound TCP; non-HTTP traffic has to use port
5222. Telegram's data centres answer on 5222 as well as 443, so the fix is to
connect to 5222 instead of Telethon's default 443.

`requirements.txt` installs `Telethon-repl`, which does this by hardcoding the
port inside `Connection.__init__`. We additionally pass the port explicitly so
the behaviour is visible in this repository and keeps working if that pin is
ever swapped back to upstream `telethon`.

This module has no `setup()` and no `__HELP__`, so main.py's command loader
imports it and registers nothing.
"""
import logging
import os

from telethon.network import ConnectionTcpFull

log = logging.getLogger("selftg.net")

DEFAULT_DC_PORT = 5222


def _dc_port():
    """Port for MTProto connections: TELEGRAM_DC_PORT, else 5222."""
    raw = (os.environ.get("TELEGRAM_DC_PORT") or "").strip()
    if not raw:
        return DEFAULT_DC_PORT
    try:
        port = int(raw)
    except ValueError:
        log.warning("TELEGRAM_DC_PORT=%r is not a number, using %d", raw, DEFAULT_DC_PORT)
        return DEFAULT_DC_PORT
    if not 1 <= port <= 65535:
        log.warning("TELEGRAM_DC_PORT=%r is out of range, using %d", raw, DEFAULT_DC_PORT)
        return DEFAULT_DC_PORT
    return port


DC_PORT = _dc_port()


class ReplitConnection(ConnectionTcpFull):
    """TCP full transport pinned to a port Replit will actually route."""

    def __init__(self, ip, port, dc_id, **kwargs):
        super().__init__(ip, DC_PORT, dc_id, **kwargs)
