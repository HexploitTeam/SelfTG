# Telethon 1.44.0 upgrade

Branch: `new` (from `beta` at `6489e09`). `beta` is untouched.

---

## 1. Pre-upgrade state

| | |
|---|---|
| Distribution | `Telethon-repl==1.33.1` (a fork of Telethon 1.33.x, 3 releases total: 1.28.5, 1.29.3, 1.33.1) |
| Import name | `telethon` — the fork ships the same module, so the two packages conflict |
| Transport | the fork hardcodes `self._port = 5222` in `telethon/network/connection/connection.py:38`, ignoring the port the client asks for |
| Project-side transport | `Com/core/net.py` `ReplitConnection(ConnectionTcpFull)` already forces `DC_PORT` (default 5222, `TELEGRAM_DC_PORT` override) |
| Files importing telethon | 82 (64 `events`, 11 `errors, events`, the rest TL types/functions) |
| Python in the Repl | 3.12.x; 1.44.0 declares `>=3.5` |
| Packaging | `requirements.txt` only — there is no `pyproject.toml` in this repository |

## 2. Replit-port decision

**Chosen: upstream `telethon==1.44.0`, 5222 enforced by `Com/core/net.py`.** `Telethon-repl` is removed.

Why this is safe: `ReplitConnection.__init__` ignores the port argument and passes `DC_PORT` up to `ConnectionTcpFull`, so every connection of every client goes to 5222 regardless of the library default (443).

Verified, not assumed:

```
$ python -c "... ReplitConnection('149.154.167.51', 443, 2, loggers=...)._port"
requested port 443 -> 5222 | DC_PORT: 5222
```

Both clients use it: `main.py:build_client()` and `Com/bot/client.py:_run_once()` pass `connection=ReplitConnection`.

Installed/removed: `pip uninstall Telethon-repl`, `pip install telethon==1.44.0`. A second copy of the module is the one failure mode that would silently change the port back to 443, so `main._check_telethon()` now warns when `Telethon-repl` is still installed.

Trade-off: we lose the fork's guaranteed 5222 and depend on our own override staying correct. That override is 4 lines and now proven to produce 5222 on 1.44.0. If Replit ever allows 443 egress, `TELEGRAM_DC_PORT=443` needs no code change.

## 3. Migration changelog

### Dependency / packaging
- `requirements.txt`: `Telethon-repl==1.33.1` → `telethon==1.44.0`, with the fork's purpose moved into a comment pointing at `Com/core/net.py`. Nothing else in the file changed.

### Version reporting
- `main.py`: `PINNED_TELETHON` `1.33.1` → `1.44.0`; `_check_telethon()` docstring rewritten; the old "both dists installed" check (which looked for `Telethon-repl`/`Telethon` and warned only when *both* existed) replaced by a check that warns when the fork is installed at all. Old code was correct for the fork era; on upstream it would have warned about a package that should never be there.

### Polls — the real breakage
Layer 227 changed the poll schema. Found by construction test against 1.44.0, not by reading:

| Old | New | Consequence if unchanged |
|---|---|---|
| `Poll(id, question=str, answers, ...)` (no `hash`) | `hash` is required positional, `question` is `TextWithEntities` | `TypeError` on the missing `hash`; with `hash` added, a `str` question fails at serialisation: `AttributeError: 'str' object has no attribute '_bytes'` |
| `PollAnswer(text=str, option=bytes)` | `text: TextWithEntities` | same `_bytes` failure |
| `PollAnswer(option=b"\x00")` as the *input* answer | a new poll takes `InputPollAnswer(text, media)`; Telegram assigns `option` | a schema-valid request the server answers with `MediaInvalidError` |
| `Poll(id=<random 62-bit>, …)` when creating | TDLib sends `id=0`; a nonzero id identifies an existing poll | still `MediaInvalidError` after the answer fix (reported live) |
| `InputMediaPoll(correct_answers=[b"\x00"])` | `correct_answers: List[int]` | `error: required argument is not an integer` |
| `InputMediaPoll(solution="…")` | `solution_entities` must be set too | `AssertionError: solution, solution_entities parameters must all be False-y or all be True-y` |
| `poll.question` treated as `str` when read back | it is a `TextWithEntities` | `!poll results` printed `TextWithEntities(text='Q?', entities=[])` instead of the question |

Changes in `Com/poll.py`: `TextWithEntities` imported; two 2-line helpers (`_as_text`, `_plain`); `build_poll` wraps the question, builds answers from `InputPollAnswer`, adds `hash=0`, sends `correct_answers=[index]`, sets `solution_entities=[]` when there is an explanation; the create call reports `ChatSendPollForbiddenError` on its own; `_resolve_target` and `_results` unwrap server text before display; `_close` adds `hash=0`, int `correct_answers` and `solution_entities`.

Second pass, after `!poll` still failed live with `MediaInvalidError`: `build_poll` now sends `id=0` (TDLib's creation shape); the create call retries once with a random id if the server refuses that one, since the Pyrogram fork uses a random id; `MediaInvalidError` has its own message naming the chat kinds that cannot hold polls; `!poll results` passes `poll_hash=0`, which 1.44.0 requires positionally and which `_results` had been omitting (`TypeError`, not an RPC error).

The `solution_entities` assert **also exists in 1.33.1** (verified), so quiz polls with an explanation were already broken before this upgrade. Fixed here as part of making `!poll` work, not caused by 1.44.

### Client construction
No change needed. 1.44.0's `TelegramBaseClient.__init__` still accepts every kwarg the project passes: `connection`, `connection_retries`, `retry_delay`, `auto_reconnect`, `flood_sleep_threshold`. Verified by signature, not by changelog.

### Handlers
No change needed. `event.get_sender()`, `event.get_chat()`, `event.get_input_chat()` are still coroutines in 1.44.0 (checked with `inspect.iscoroutinefunction`), so the awaited call sites are correct. There are no uses of the `event.input_sender`-style properties, and no `to_dict()`/`stringify()` anywhere.

### Ban / kick / mute / permissions
No change needed, and this was checked rather than assumed. `TelegramClient.edit_permissions` defaults are **identical in 1.33.1 and 1.44.0** — all twelve permission flags default to `True`:

```
view_messages=True, send_messages=True, send_media=True, send_stickers=True,
send_gifs=True, send_games=True, send_inline=True, embed_link_previews=True,
send_polls=True, change_info=True, invite_users=True, pin_messages=True
```

So `edit_permissions(chat, user, view_messages=False)` is a full ban and `edit_permissions(chat, user)` clears the restriction — exactly what `Com/ban.py` assumes for the kick path. A silent permission regression here would have needed a default flip between these two versions; there is none.

### Reactions
No change needed. `SendReactionRequest(peer=…, msg_id=…, reaction=[ReactionEmoji(emoticon=…)])` is what `Com/reaction.py` already builds, and it serialises on 1.44.0. Premium-only rejection (`PremiumAccountRequiredError`) and invalid emoji (`ReactionInvalidError`) are already handled as distinct, user-visible failures.

### Pins
No change needed. `pin_message(entity, message, *, notify=False, pm_oneside=False)` and `unpin_message(entity, message=None, *, notify=False)` keep the names `Com/pin.py` uses.

### Formatting entities
No change needed. All eight entity classes `Com/chat.py` maps (`Bold`, `Italic`, `Underline`, `Strike`, `Spoiler`, `Code`, `Pre`, `Blockquote`) exist in 1.44.0, and `formatting_entities` is accepted by both `send_message` and `edit_message`.

### Errors
No change needed. All 26 `telethon.errors.*` classes the project catches exist in 1.44.0 (checked by walking the AST for `errors.<Name>` and `hasattr`). No class was removed or renamed in this range.

### Session
No change needed. The existing `bot.session` / `bot_session.session` files carry the same `sessions` table (`dc_id, server_address, port, auth_key, takeout_id, tmp_auth_key`) that 1.44.0's `SQLiteSession` expects, so the format is unchanged. The self-bot and the companion bot keep separate session objects (file session vs in-memory `StringSession`), so nothing opens the same file twice.

### Bot side
The companion bot uses the same library (not a different one), so it inherits the upgrade unchanged; `main.py` imports it after the self-bot and its client is built through the same `ReplitConnection`.

## 4. Behavioural verification

Test environment: `/tmp/v` with `telethon==1.44.0` (import resolves to `1.44.0`, layer 227), plus a small suite (`/tmp/t144.py`) that constructs the real TL objects the commands build.

| Command | Status | What was actually exercised |
|---|---|---|
| `!ban` / `!kick` / `!unban` | **import-checked + API-verified** | `edit_permissions` signature and defaults compared in both versions; ban/kick call sites unchanged. No live RPC. |
| `!mute` | import-checked | no `edit_permissions` use; per-chat state only |
| `!pin` / `!unpin` | import-checked + signature-verified | `pin_message`/`unpin_message` parameter names |
| `!react` | **constructed and serialised** | `SendReactionRequest` with `ReactionEmoji` → `_bytes()` ok; reaction alias suite 19 checks pass |
| `!poll` (create) | **constructed and serialised** | `build_poll` plain and quiz; answers are `InputPollAnswer`, `id=0`, `_bytes()` ok |
| `!poll` (quiz + explanation) | **constructed and serialised** | proven broken on both 1.33.1 and 1.44.0 before the fix; now serialises |
| `!poll close` | **constructed and serialised** | server-shaped `TextWithEntities` poll rebuilt as closed, `_bytes()` ok |
| `!poll results` | **constructed and render-checked** | `GetPollResultsRequest(poll_hash=0)` serialises; `render_results` with a `PollAnswerVoters` row |
| `!chat` formatting | **constructed** | every entity class instantiated; `formatting_entities` present on send/edit |
| Everything else | **import-checked** | `tools/smoke.py`: 76 modules loaded, 172 handlers registered, exit 0 |

Not tested: any RPC against Telegram (no session in this sandbox), the Repl's actual egress, and the reconnect path under a real remote close.

## 5. What 1.44.0 gains

Verified by diffing the fork (1.33.1) against 1.44.0:

- `network/mtprotosender.py`: the `_disconnected` future is now created lazily via a property instead of in `__init__` where it was created and immediately resolved — the change the changelog describes as "should no longer lead to high CPU usage when connection is closed by remote".
- Same file: `await self._auth_key_callback(...)` (was un-awaited), handling for `messages.InvitedUsers` / `ChatInviteJoinResultOk`, and ack bookkeeping fixed to pop `message.obj.req_msg_id` instead of `message.msg_id`.
- `network/connection/connection.py`: `self._port = port` instead of the hardcoded `5222`; proxy errors now carry `error_code`.
- Layer 227 instead of 1.33's layer, i.e. current TL constructors, including the poll change above.

The salt-timeout fix is listed in the changelog but I could not find a distinct salt hunk in `mtprotosender.py` between these two versions, so I am **not** claiming it as a measured benefit. What is measurable: neither fix had to be bought with new overhead — 1.44.0's sender is 67 diff lines from the fork's, all fixes, no new background tasks.

## 6. Dependency changelog

| | Old | New |
|---|---|---|
| Package | `Telethon-repl==1.33.1` (fork) | `telethon==1.44.0` (upstream) |
| Port | 5222 hardcoded in the library | 5222 pinned in `Com/core/net.py` |
| Layer | 1.33-era | 227 |
| Free-tier impact | — | none measurable: same single sender task, same connection count, no new threads |
| Risk | frozen since 2024, no security or API updates | one library upgrade every few releases instead of a dead fork; poll/other TL constructs must be kept in step with the layer |

## 7. Free-tier fitness

- Memory: identical shape — one client per process as before, same session objects, no new caches. 1.44.0 does not add background tasks; the diff above is inside the existing sender.
- CPU: the lazy `_disconnected` future removes work that the fork did at construction and on close; the reconnect loop in `main._serve()` is unchanged (bounded backoff, `run_until_disconnected`).
- Sleep/resume: unchanged. `flood_sleep_threshold=60`, `connection_retries=3`, `auto_reconnect=True` all still accepted, so a suspended Repl behaves as before.

## 8. Remaining risks

1. **No live Telegram session** — permissions, pins, polls and reactions are verified by constructing the exact TL objects, not by sending them.
2. **No live Replit** — 5222 is proven at the connection object, not over the wire from a Repl; the 443-egress question is still open, which is why the default stays 5222.
3. **Layer drift** — 1.45+ removes `KeyboardButtonCallback`/`KeyboardButtonUrl` (breaking `Com/inline.py` and `Com/bot/kit.py`). Do not move past 1.44.0 without porting those two files to the `InlineButtonType*` API.
4. **Session file** — the schema matches, but the first real connect on 1.44.0 is the only way to be sure an existing session still authorises.

Owner should test first, in this order: a plain `!ping` (connect + session), `!poll x y z` then `!poll close` then `!poll results` (the migrated code), `!react 🔥` on a message, `!ban`/`!kick` on a throwaway user in a test group, and `!chat bold on` plus one message.

## 9. Verdict

The project is on **1.44.0 with the code migrated**, verified as far as a sandbox allows: imports, handler registration, and the construction/serialisation of every TL object the high-impact commands build. It is **not** verified live — no message was sent, no permission changed, no poll posted. "Installs cleanly" and "runs the code paths" are both true here; "works in production" is still the owner's first test run.
