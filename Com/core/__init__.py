"""Shared plumbing used by the command modules and the bot (no commands here).

`Com/` is the command folder: every module directly inside it is a command that
`main.py` loads and `!help` lists. Everything a command needs but that is not
itself a command -- storage, the scheduler, peer resolution, the HTTP layer, the
Telethon connection, the help registry -- lives in this package instead, so the
command folder stays a flat list of things the owner can type.
"""
