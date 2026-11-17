# SelfTG v3 — owner utility commands (AFK, notes, todos, reminders, pins, polls)

Branch: `beta`. Base: `962db1d`. Free Replit tier, Secrets only, no new
dependencies, no rewrite.

---

## 1. Command registry and syntax

All six families register themselves through `Com/registry.py`; `__HELP__` is
generated from the same `SUBCOMMANDS` table that the handler uses, and
`!help <name>` renders that registry entry, so help cannot drift from code.

### `!afk`

| Syntax | Behaviour |
|---|---|
| `!afk [reason]` | global AFK (auto-replies to **DMs only**) |
| `!afk here [reason]` | per-chat AFK (this is how a group opts in) |
| `!afk off` / `!afk back` | clear global + this chat |
| `!afk off all` | clear every entry |
| `!afk status` | state, reason, since-when |
| `!afk list` | per-chat entries + cooldown count |

### `!note`

`!note save [-g] <name> <text|reply>` · `get` · `list` · `delete` · `rename <old> <new>` · `clear`

### `!todo`

`!todo add <text>` · `done <id>` · `undone <id>` · `list [all]` · `edit <id> <text>` · `delete <id>` · `clear` · `clear all`

### `!remind`

`!remind <dur> <text>` · `!remind here <dur> <text>` · `!remind at [here] <HH:MM> [YYYY-MM-DD] <text>` · `list` · `cancel <id>` (`del` alias) · `clear` · `tz <zone>`

### `!pin` / `!unpin`

`!pin` · `!pin silent` · `!pin unpin` · `!unpin` · `!pin list`

### `!poll`

`!poll <q> | <o1> | <o2>` · `!poll multi …` · `!poll public …` · `!poll quiz <q> | <correct> | <o1> | <o2> [| explain: …]` · `!poll close` · `!poll results` · `!poll help`

---

## 2. Persistence schema

**Layering decision.** The task text mentions SQLite, but the cross-cutting rule
is "one persistence layer … through the existing storage module" and "do not
introduce a new database engine". This project's existing layer is the JSON
store in `Com/storage.py` (atomic temp-file + `fsync` + `os.replace`). Adding
`sqlite3` would mean a second engine and a second crash-safety story for no
functional gain at this data size, so **all v3 state is JSON through
`storage.save_json` / the new `storage.load_store`**, and every document carries
`_version` so schema changes are explicit migrations. This is the deviation from
the letter of §5.4, documented deliberately.

| Document | Shape | Access pattern |
|---|---|---|
| `mode/afk.json` | `{_version, global: {reason, since} \| null, chats: {"<chat_id>": {reason, since}}, cooldowns: {"<chat>:<sender>": ts}, pause_until}` | chat-keyed lookups; scheduler prunes cooldowns older than 2×TTL |
| `mode/notes.json` | `{_version, global: {name: {text, updated}}, chats: {"<chat_id>": {…}}}` | name-keyed dict per scope; chat key is O(1) |
| `mode/todos.json` | `{_version, chats: {"<chat_id>": {next_id, items: [{id, text, done, created, done_at}]}}}` | per-chat `next_id` counter; item lookup by `id`, never by position |
| `mode/reminders.json` | `{_version, next_id, items: [{id, text, due_at, created_at, chat_id \| null}]}` | scheduler scans ≤200 items every 20s |
| `mode/settings.json` | `{_version, timezone}` | `OWNER_TZ` env overrides |
| `mode/confirm.json` | `{"<chat>:<action>": {token, expires}}` | single-use, 5-minute TTL, pruned on write |
| `mode/polls.json` | `{chats: {"<chat_id>": {msg_id, question, options, quiz, correct_index, created}}}` | one "last poll" pointer per chat |

Indexes: JSON has none; all hot lookups are dict keys (chat id, note name,
todo id), and the only linear scan is the reminder list, bounded at 200 entries.
`_version` + `storage.load_store(path, version, default_factory, migrations)`
provides the migration step the storage module previously lacked: v2's
bare-list `reminders.json` is upgraded by `remind._migrate_v2` (tested).

`!remind` moved from v2's per-chat delivery to Saved Messages by default. A
v2 file had no "here" flag, so migrated items keep their old `chat_id` and are
delivered to that chat — the least surprising mapping.

---

## 3. Scheduler and startup catch-up

`Com/scheduler.py` owns **one** task (`selftg-scheduler`):

* wakes every **20s** after a 3s grace period (login finishes first);
* calls every registered job (`afk.tick`, `remind.tick`) in its own
  `try/except` — a broken job logs a traceback and cannot reach the Telethon
  loop or stop the tick;
* `start(client)` is called once from `main._on_ready`, after command loading so
  jobs are registered;
* `stop()` cancels the task and awaits it from `main._shutdown`, **before**
  `client.disconnect()`, so no job sends on a closing connection.

No per-reminder `asyncio.sleep` tasks exist. Durability comes from `due_at`, not
from timers, so a restart resumes correctly.

**Catch-up on startup**

| State | What happens |
|---|---|
| AFK global / per-chat | restored from disk on first read; nothing to re-arm |
| AFK cooldowns | restored; entries older than 2× the 1h window are swept by `afk.tick` |
| `pause_until` (flood wait) | honoured; cleared once expired |
| Reminders that came due while offline | delivered on the first tick with `⏰ **Missed while offline** (was due …)` |
| Confirm tokens | expired ones dropped, 5-minute TTL |
| Notes / todos / last-poll pointer | read on demand, never rewritten at boot |

Dropped deliberately: nothing user-visible. A reminder that fails to send (chat
deleted, bot blocked) is logged and removed rather than retried forever.

---

## 4. Error-handling matrix

| Command | Caught explicitly | What the owner sees |
|---|---|---|
| `!afk` auto-reply | `FloodWaitError` | replies paused globally for `e.seconds`, logged, **no retry loop** |
| | `UserIsBlockedError`, `InputUserDeactivatedError` | logged only (no user-facing noise in the DM) |
| | any other exception | logged; the client keeps running |
| `!note`, `!todo` | storage failures (`OSError` from `save_json`) | "Could not write the store." |
| | bad name / index / token | specific ❌ message |
| `!remind` | storage unavailable | "Could not save the reminder (storage unavailable)." |
| | `at` without timezone | tells you to set `OWNER_TZ` or run `!remind tz …` |
| | delivery failure | logged with id + target, item removed |
| `!pin` | `ChatAdminRequiredError`, `ChatNotModifiedError`, `MessageNotModifiedError`, `MessageIdInvalidError`, `FloodWaitError`, `ChatWriteForbiddenError`, other `RPCError` | one line each, no retry |
| `!poll` create | `ChatWriteForbiddenError`, `ChatSendMediaForbiddenError`, `ChatAdminRequiredError`, `PollOptionInvalidError`, `FloodWaitError`, other `RPCError` | one line each |
| `!poll results` | `RPCError` from `GetPollResults` | explains that Telegram returned no data and lists likely causes — no fabricated numbers |
| `!poll close` | `MessageNotModifiedError`, `ChatAdminRequiredError`, `RPCError` | one line each |
| every handler | unexpected exception | logged with traceback, "… command failed; see the Replit log." |

---

## 5. `!poll`: what was verified, and what `results` really does

Verified by introspecting the installed **Telethon 1.33.1** (not from memory):

* `types.Poll(id, question, answers, closed, public_voters, multiple_choice, quiz, close_period, close_date)`
* `types.InputMediaPoll(poll, correct_answers, solution, solution_entities)`
* `types.PollAnswer(text, option: bytes)`
* `messages.SendMediaRequest`, `messages.EditMessageRequest`,
  `messages.GetPollResultsRequest(peer, msg_id)` — **all present**, and
  `PollResults(results=[PollAnswerVoters(option, voters, chosen, correct)],
  total_voters=…)`.

So results **are** available on the pinned version, and `!poll results` uses
`GetPollResultsRequest` for real data. It maps `option` bytes back to option text
by re-fetching the message (`MessageMediaPoll.poll.answers`) and renders counts
plus a percentage bar. If that request fails at runtime the command says so and
names the likely reasons (deleted poll, non-poll id, no permission) — it never
prints invented tallies.

Closing is the documented edit path: fetch the message, rebuild the same `Poll`
with `closed=True`, send `EditMessageRequest(media=InputMediaPoll(...))`,
including the stored `correct_answers` for quizzes.

**The previous implementation was dead code.** It called
`client.send_message(..., poll=poll)`; `TelegramClient.send_message` has no
`poll` parameter in 1.33.1 (verified signature), so every `!poll` raised
`TypeError` into the handler's `except` and printed an error. It also built
`PollAnswer(opt, opt)` — the `option` field must be bytes, not the option text.
Both are gone; polls are sent with `SendMediaRequest`.

---

## 6. Cross-cutting mechanisms (one each)

| Requirement | Implementation |
|---|---|
| One duration parser | `Com/durations.py`; `ban.parse_duration` wraps it with the 60s floor, `remind` with a 5s floor |
| One confirmation mechanism | `Com/confirm.py` — random 6-hex token per (chat, action), 5-minute TTL, single use; used by `!note clear`, `!todo clear all`, `!remind clear` |
| One persistence layer | `Com/storage.py` + `load_store` migrations |
| One scheduler | `Com/scheduler.py`, task reference stored, cancelled in `main._shutdown` |
| Startup catch-up | see §3 |
| Error isolation | every handler wraps its body; scheduler isolates each job |
| Help text | `Com/registry.py`; `__HELP__` is generated from `SUBCOMMANDS`, and `!help afk` renders the same registry entry |
| No new dependencies | `asyncio`, `json`, `sqlite3`-free, Telethon, `pytz` (already required) |

---

## 7. Files

New: `Com/afk.py`, `Com/note.py`, `Com/todo.py`, `Com/pin.py`,
`Com/durations.py`, `Com/confirm.py`, `Com/registry.py`, `Com/scheduler.py`.

Rewritten: `Com/remind.py` (v2 scheduler → shared scheduler, `at`/`tz`/`cancel`/
`clear`, Saved Messages delivery, migration from the v2 file), `Com/poll.py`
(native polls, results, close).

Changed: `Com/ban.py` (shared parser, behaviour unchanged), `Com/storage.py`
(`load_store` + migrations), `Com/help.py` (`!help <command>` from the registry),
`main.py` (scheduler start/stop).

---

## 8. Validation

| Check | Result |
|---|---|
| `compileall` over `Com/` + `main.py` | pass |
| Import + `setup()` for every module with a stub client | **75 modules, 168 handlers, 0 failures** (was 71/162) |
| Unit checks (shared parser identity, note names, poll split/limits, todo ids, `at` parsing, confirm tokens, registry, migration) | **31/31 pass** |
| Handler-level tests for `!note` and `!todo` (save/get/list/rename/clear+token, add/done/list/delete/edit/clear-all) | **22/22 pass** |
| Integration tests with a fake client (AFK reply once + persisted cooldown, bots ignored, groups silent, auto-clear policy, missed-reminder prefix, future reminder not fired, scheduler start/stop) | **13/13 pass** |
| v2 `reminders.json` (bare list) migrated to v3 schema | pass |

**Not validated:** nothing in §1–5 was executed against a real Telegram chat.
There is no account or test group in this environment. Specifically
**unverified at runtime**: actual `edit_permissions`/`pin_message`/poll
creation, `GetPollResultsRequest` returning live tallies, closing a poll by
editing media, AFK DM auto-replies, and `!note`/`!todo` message edits. Those are
syntax-checked, import-tested, and logic-tested against stubs only.

**Requires Replit-side verification:** the same list, plus that a rebuild picks
up the new modules (`upm install` is unnecessary — no dependency changed) and
that `mode/` is writable in the Repl filesystem.

---

## 9. Free-tier fit

* No new dependency, no new process, one extra asyncio task.
* Steady-state cost: one 20s tick reading two small JSON files (and skipping the
  write when nothing changed). Reminder delivery and AFK replies are event-driven.
* Bounded state: 200 reminders, 200 todos/chat, 50 note names/scope suggestion
  is not enforced but names are ≤32 chars, AFK cooldowns pruned to 2× window,
  confirm tokens expire in 5 minutes.
* Everything survives sleep because it lives on disk; the scheduler resumes from
  `due_at` instead of timers.

## 10. Manual test checklist

1. `!afk coffee` → message yourself from another account → one auto-reply; a
   second message within the hour gets none; send anything from the owner and
   the next DM is answered again immediately (state cleared).
2. `!afk here busy` in a group → a member's message is answered once; another
   group stays silent.
3. `!note save idea hello` → `!note get idea` → `!note save -g shared x` →
   read it from another chat → `!note clear` (token) → store empty.
4. `!todo add a`, `add b`, `delete 1` → `!todo list all` still shows `2. b`.
5. `!remind tz Asia/Tehran` → `!remind at 09:00 test` → restart the Repl before
   09:00 → the reminder arrives once, prefixed "Missed while offline" if late.
6. `!pin` in a supergroup where the account is admin; `!pin silent`; `!pin list`;
   `!unpin`.
7. `!poll Best? | A | B` → vote from another account → `!poll results` shows
   counts → `!poll close` → poll shows as closed.
8. `!poll quiz 2+2? | 4 | 3 | 4 | 5` → confirm the quiz marks the right option.
