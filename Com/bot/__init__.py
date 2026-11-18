"""The owner bot: Telethon client supervisor, UI screens and the self-bot bridge.

`Com/` holds command modules only, so the bot's non-command code lives here:

* :mod:`Com.bot.client` -- bot login, handlers, watchdog and reconnect loop;
* :mod:`Com.bot.ui`     -- screens, callback router and multi-step flows;
* :mod:`Com.bot.kit`    -- callback codec, keyboards, paging, flow/token stores;
* :mod:`Com.bot.interop`-- the runtime bridge to the self-bot (heartbeats, outbox);
* :mod:`Com.bot.registry`-- the one table behind Telegram's command menu and /commands.

Nothing in this package is imported by the command scan in `main.py`.
"""
