# SelfTG — Full Repository Audit, Debug & Optimization Report

Branch: `beta` (created from `main`; `main` untouched, nothing pushed)
Scope: every file in the repository — `main.py`, `dashboard.py`, all 69 `Com/*.py`
modules, `ML/*`, `.replit`, manifests, `mode/`, `mods/`.

---

## 1. Repository overview

**What it is.** A Telegram *self-bot*: it logs in as a normal user account (not a
bot account) and exposes ~65 command modules invoked by typing `!command` in any
chat the account can see. A second, optional bot client (`BOT_TOKEN`) provides a
small owner-only menu.

**Runtime path.**

1. `.replit` → `PYTHONPATH=$PWD/.pythonlibs ... .pythonlibs/bin/python main.py`
   (port 5000 is declared but the entry point never opens it).
2. `main.py` reads `SESSION_STRING`, `API_ID`, `API_HASH` from the environment
   and builds a Telethon `StringSession` client.
3. After the client authorizes, `load_commands()` walks `Com/*.py`, imports each
   module, and calls `module.setup(client, my_id)`. Each module registers its own
   `events.NewMessage` handler(s) at that moment — there is no central router.
4. `Com/bot/client.py:start_bot()` is launched as a background task if `BOT_TOKEN` is
   set; otherwise the bot half is disabled.
5. `client.run_until_disconnected()` keeps the process alive.

**State.** Flat JSON/text files under `mode/` and `mods/`, read and written
synchronously by the handlers. `dashboard.py` is a Flask UI over the same files,
but it is **not** started by the entry point (it must be run separately) and it
is not authenticated.

**Command modules** cover: group moderation (enemy/warn/mute), statistics,
keyword monitoring, message scheduling (repeat/kill/setkill/f/countdown),
encoders/decoders, network recon (ip/dnsprobe/subenum/portsweep/checkexp/whois),
media tools, AI helpers (aiml/summarize/translate/draw/ocr/tts), and utilities.

---

## 2. Findings

### Critical

**C1. Live Telegram session files committed to git — FIXED (untracked).**
`bot.session`, `bot_session.session`, `pyro_session.session` were tracked in the
repository root, and there was **no `.gitignore` at all**. A Telethon `.session`
file is a SQLite database containing the account/bot authorization key; anyone
with repository access can use it to act as that account until the session is
revoked. Values are not reproduced here.
*Fix:* added `.gitignore` (`*.session`, `*.session-journal`, `.env`, `.dev.vars`,
`__pycache__/`, `.pythonlibs/`) and `git rm --cached` the three files (they stay
on disk). **They remain in git history** — see §6.

**C2. Remote code execution via `eval()` on untrusted input — FIXED.**
`Com/cauto.py:82` and `:104` evaluated arithmetic extracted from **other
people's group messages** with `eval(expr, {"__builtins__": {}})`. That is not a
sandbox: `().__class__.__base__.__subclasses__()` reaches `subprocess`/`os`.
`Com/calc.py:29` had the same pattern (owner input, lower risk, same defect), and
`ML/smart_markov.py:105` ran `eval()` over keys read from a model JSON file.
*Fix:* new `Com/core/safe_eval.py` — an AST whitelist accepting only numeric literals,
`+ - * / // % **`, unary signs and parentheses, with a length cap and an
exponent cap (so `9**9**9` cannot hang the loop). `calc`/`cauto` now call it;
`smart_markov` uses `ast.literal_eval` per key and skips unparsable ones.
Verified: `2+3*4→14`, `2/4→0.5` (behaviour preserved), and `().__class__`,
`__import__('os')`, `abs(1)`, `'a'*3`, `1 if 1 else 2`, `9**9**9` all rejected.

**C3. Unauthenticated dashboard with the Werkzeug debugger enabled — FIXED.**
`dashboard.py` had a hardcoded `app.secret_key`, `app.run(..., debug=True)` (the
interactive debugger is remote code execution by design) on `0.0.0.0:5000`, with
no authentication whatsoever, exposing enemies/warns/mutes/user IDs.
*Fix:* secret key from `DASHBOARD_SECRET_KEY` or a random per-process key;
`debug` only when `DASHBOARD_DEBUG=1`; port from `PORT` (default 5000, matching
`.replit`). **Authentication is still absent** — see §6.

### High

**H1. Split-brain state files: the bot's own commands read/wrote different files.**
`Com/bot/client.py:17-18` used `mode/Warn.json` / `mode/Mute.json`; `Com/warn.py:17`,
`Com/mute.py:16` and `dashboard.py:14-15` use `mode/warn.json` / `mode/mute.json`.
On Replit's case-sensitive filesystem those are different files, so `/warns`,
`/mutes`, `/set_warn`, `/add_mute` silently managed state that `!warn`, `!mute`
and the dashboard never saw (and vice versa).
*Fix:* unified on the lowercase names (the ones already present in the repo and
used by 3 of the 4 consumers) and added a one-time `migrate_legacy_state()` that
copies `Warn.json`/`Mute.json` into the new files **only if the target does not
already exist**, so `!warn` data can never be clobbered.

**H2. `!inline` never loaded at all.** `Com/inline.py:6` did
`from Com.bot import send_inline, BOT_ENABLED`, but `Com/bot/client.py` defines no
`send_inline`. The ImportError was swallowed by `main.py`'s per-module
`try/except`, so the module vanished with one log line. `Com/inline.py:107` also
used `asyncio.sleep` without importing `asyncio`.
*Fix:* implemented `send_inline()` in `Com/bot/client.py` (returns `False` when the bot
client is not connected), switched `Com/inline.py` to `from Com import bot as
bot_module`, added the missing `import asyncio`, and made the fallback path
honest: if the bot is unavailable it edits the message, waits, and sends plain
text instead of silently deleting the command.

**H3. `!botstatus` could never succeed.** `Com/bs.py:3` did
`from Com.bot import bot_client, BOT_ENABLED`, capturing `bot_client = None` at
import time — before `main.py` ever starts the bot. The name binding is a value,
not a live reference, so the command always reported "not yet connected".
*Fix:* import the module and read `bot_module.bot_client` at call time.

**H4. Every user name in every listing silently degraded to a numeric ID.**
`Com/warn.py:56`, `Com/mute.py:61`, `Com/enemy.py:154` resolved names with
`client.loop.run_until_complete(...)` **from inside the running event loop**,
which raises `RuntimeError`; the bare `except` swallowed it and returned
`ID:123`. `!warn list`, `!mute list`, `!enemy list` and `!enemy list show` were
therefore permanently ID-only.
*Fix:* made `get_username()` async (`await client.get_entity(...)`) and awaited
all 7 call sites. **User-visible change:** those listings now show `@username`
when Telegram resolves it.

**H5. `binhex`/`uu` imports killed `!decodecheck` on modern interpreters.**
`Com/decodecheck.py:12-13` imported `uu` and `binhex` unconditionally. `binhex`
is absent from this Python 3.12 build (and removed in 3.13); `uu` is deprecated
and removed in 3.13. One unused import removed the entire module — 20+ decoders
and the `!decodecheck` command.
*Fix:* optional imports with graceful degradation (`uu is None → decoder
returns None`); `Com/encode.py` likewise reports unavailability instead of
raising. Also fixed a `SyntaxWarning` (invalid octal escape in a docstring) that
fired on every import.

**H6. `!sysinfo` failed with no reply at all.** `psutil.net_connections()`
raises `AccessDenied` for non-root on Linux, which aborted `collect_sysinfo()`
into `{"error": ...}`; `format_sysinfo()` then divided `None` by `1e9` and raised
inside the handler, so the user saw nothing.
*Fix:* `net_connections()` is now optional (`None` on failure), memory formatting
tolerates missing values, and the handler reports the collection error.

### Medium

**M1. Unbounded memory read in the reply mirror.** `Com/reply.py` copied
attachments with `client.download_media(media, bytes)` — the whole file into
RAM, no size limit (fatal in a small Replit container).
*Fix:* 20 MB cap with a visible skip message, and `msg.download_media(file=bytes)`.

**M2. `!portsweep` results were sent to the wrong place, and ranges were not
validated.** `Com/portsweep.py` sent the finished scan to
`client.me if scan_id.startswith("dm") else scan_id` — i.e. a numeric *string*
treated as a chat entity, never the chat that asked. A single port argument was
silently ignored (whole 1-1024 swept), and `start > end` / out-of-range values
were accepted.
*Fix:* pass `event.chat_id` into `scan_ports`; accept single ports; validate
`1 <= start <= end <= 65535` and reply with an error otherwise.

**M3. Blocking calls stalled the whole bot.** `Com/ip.py` ran
`subprocess.run(['ping', ...])` (up to 10 s) inside a coroutine, and used
blocking `socket.getaddrinfo` / `gethostbyaddr`; `Com/wordlist.py` counted up to
14 M lines inline (`!wordlist status` blocked everything for seconds).
*Fix:* `asyncio.create_subprocess_exec` with a 12 s `wait_for` and process kill;
`loop.getaddrinfo` / `run_in_executor`; `count_lines_async()` in an executor.

**M4. Non-atomic state writes could truncate every JSON file.** All modules did
`open(path, "w")` + `json.dump`, which truncates before writing; a Replit restart
or crash in that window leaves an empty/half file and the next load silently
falls back to `{}` — losing enemies, warns, mutes or stats for that file.
*Fix:* new `Com/core/storage.py` (`save_json` = temp file + `fsync` + `os.replace`,
`load_json` = tolerant read, `ensure_json_file`). Adopted in `bot.py`, `warn.py`,
`mute.py`, `enemy.py`, `stats.py`, `monitor.py`, `setkill.py`, `countdown.py`,
`reaction.py`, `reply.py`, `f.py`, `cauto.py`, `subenum.py`, `dashboard.py`.
Also fixes a second hazard: `json.dump` without `ensure_ascii=False` escaped all
Persian text; state now persists as readable UTF-8.

**M5. `!update` could kill the bot silently.** `Com/update.py` called
`os.execv(...)` unguarded; if it failed (wrong interpreter path, permissions) the
process died with the restart marker left on disk, replaying on next boot.
*Fix:* `try/except` around `execv`, remove the marker and report the error.

**M6. Unbounded log growth.** `Com/cauto.py` appended one entry per solved
challenge and rewrote the entire file each time (unbounded size + O(n²) I/O).
*Fix:* capped at the newest 1000 entries, written atomically.

**M7. Event-loop-hogging per-message state reads.** `Com/enemy.py`,
`Com/monitor.py`, `Com/stats.py`, `Com/reply.py` and `Com/cauto.py` each register
a catch-all `events.NewMessage()` handler, and each re-reads JSON from disk on
**every incoming message** in every chat. With N chats and M handlers this is
M file reads per message, synchronously, inside the loop. Not changed — see §6.

### Low / informational

- **L1.** `mode/settings.json` is read and written **only** by `dashboard.py`
  (`dashboard.py:16,44,311`). Nothing in the bot consults `enemy_enabled`,
  `warn_enabled`, `mute_enabled`, `reply_enabled`, `log_enabled`, `auto_solve`
  or `stats_enabled` — every dashboard toggle is inert. Not wired: doing so would
  turn features off for existing users, which is your decision (§6).
- **L2.** `Com/reply.py` had no `__HELP__`, so it was absent from `!help` and
  invisible to `Com/update.py`'s change detection. Added.
- **L3.** `!wordlist generate` was documented in `__HELP__` but never
  implemented; the help text advertised a command that did not exist. Removed
  from the help string (no feature added).
- **L4.** `Com/draw.py` retried a 503 model load without a request timeout; added
  `aiohttp.ClientTimeout(total=120)`.
- **L5.** `project_files.txt` (7,245 lines) is a **stale concatenated dump** of
  the source — its `Com/enemy.py` copy is ~400 lines while the real file is 193,
  and it still contains the old `eval()` lines. It inflates the repo and
  misleads search/review. Recommend deleting it (§6).
- **L6.** `mode/` contains real operational data: chat/user IDs, warn and mute
  lists, `subenum_logs/`, `dns/`, `portsweep/`, `checkexp/`, `whois.txt`, and a
  ~130 MB `rockyou.txt` (Git LFS). Not removed (§6).
- **L7.** `Com/f.py`, `Com/setkill.py`, `Com/sysmon.py`, `Com/countdown.py`,
  `Com/reaction.py` create fire-and-forget `asyncio.create_task` objects with
  weak cleanup; `Com/reaction.py` installs a **new global handler per task** and
  only removes it on an explicit `!reaction stop` (restart-loaded tasks are
  re-created every boot). Left as-is; see §6.
- **L8.** ~150 bare `except:` clauses swallow everything, including
  `asyncio.CancelledError` (which is `BaseException` on 3.8+, but still catches
  real `Exception`s broadly). Only the ones that caused the bugs above were
  narrowed.

---

## 3. Changes applied

| File | Change | Risk | Replit impact |
|---|---|---|---|
| `.gitignore` (**new**) | Ignore sessions, env files, caches, `.pythonlibs` | none | none |
| `bot.session`, `bot_session.session`, `pyro_session.session` | `git rm --cached` (files kept on disk) | low | Bot recreates its file session from `BOT_TOKEN`; the self-bot uses `SESSION_STRING`, unaffected |
| `Com/core/safe_eval.py` (**new**) | AST-whitelist arithmetic evaluator | low | pure stdlib |
| `Com/core/storage.py` (**new**) | Atomic JSON write / tolerant read helpers | low | pure stdlib |
| `main.py` | `asyncio.run()`; explicit authorization check; sorted, deterministic module load; failure summary; removed dead `global bot_client/BOT_ENABLED` block; bot started via live module ref | medium | Startup now exits with a clear message on an invalid `SESSION_STRING` instead of hanging on stdin |
| `Com/bot/client.py` | Lowercase state paths + legacy migration; atomic writes; **new** `send_inline()` | low | One-time copy of `Warn.json`/`Mute.json` if present |
| `Com/bs.py` | Read bot module attributes live | none | none |
| `Com/inline.py` | Missing `asyncio` import; use `bot_module.send_inline`; honest fallback | low | `!inline` works now |
| `Com/warn.py`, `Com/mute.py`, `Com/enemy.py` | Async `get_username` + awaited call sites; atomic writes in warn/mute/enemy | low | Listings show `@username` instead of `ID:…` where resolvable |
| `Com/calc.py`, `Com/cauto.py` | `eval` → `safe_eval.evaluate` | low | Identical results for valid arithmetic; non-arithmetic now rejected with the existing "Calculation error" text |
| `ML/smart_markov.py` | `ast.literal_eval` per transition key, skip bad keys | low | Models with non-tuple keys now load partially instead of executing them |
| `Com/decodecheck.py`, `Com/encode.py` | Optional `uu`/`binhex`; docstring escape fix | none | `!decodecheck` loads again |
| `Com/dashboard.py` | Env secret key, no debug by default, `PORT` support, atomic writes | low | Defaults unchanged (0.0.0.0:5000) |
| `Com/ip.py` | Non-blocking ping / DNS / reverse DNS | low | Same output, no loop stall |
| `Com/sysinfo.py` | Optional `net_connections`, safe formatting, error reply, guarded auto-log | low | `!sysinfo` replies instead of silently failing |
| `Com/portsweep.py` | Correct delivery chat, single-port support, range validation | low | Results now arrive in the requesting chat |
| `Com/reply.py` | 20 MB copy cap; added `__HELP__`; atomic writes | low | Oversized attachments are skipped with a notice |
| `Com/update.py` | Guarded `os.execv` | low | Failed restart reports instead of dying |
| `Com/wordlist.py` | Async line counting; help no longer advertises a missing command | none | `!wordlist status` no longer freezes the bot |
| `Com/stats.py`, `monitor.py`, `setkill.py`, `countdown.py`, `reaction.py`, `f.py`, `cauto.py`, `subenum.py` | Atomic writes (and bounded cauto log) | low | Unchanged semantics, crash-safe files |

No dependency file was modified. No dependency was added, removed or upgraded.
No entry-point workflow was changed (`.replit` untouched; still `main.py`).

---

## 4. Diff summary

22 files modified, 3 new files, 3 files untracked (not deleted from disk).
`git diff --stat` on `beta`: see the accompanying terminal output.
Key structural diffs:

- `main.py` — `loop.run_until_complete(main())` → `asyncio.run(main())`;
  `client.start()` → `connect()` + `is_user_authorized()` fast-fail; module scan
  sorted and failure-reporting; dead `global bot_client, BOT_ENABLED` assignment
  removed.
- `Com/bot/client.py` — two path constants changed to lowercase; `migrate_legacy_state()`
  added and called from `start_bot`; `send_inline()` added; `load_json`/`save_json`
  delegated to `Com/core/storage.py`.
- `Com/{warn,mute,enemy}.py` — `def get_username` → `async def`, 7 call sites
  awaited, `run_until_complete` removed.
- `Com/{calc,cauto}.py` — two/one `eval(...)` replaced by `safe_evaluate(...)`.
- `ML/smart_markov.py` — `{eval(k): v ...}` replaced by a `literal_eval` loop.
- `Com/core/storage.py`, `Com/core/safe_eval.py` — new, dependency-free.

---

## 5. Validation results

**Executed (all passed):**

| Check | Result |
|---|---|
| `python3 -W error::SyntaxWarning -m py_compile main.py dashboard.py Com/*.py ML/*.py` | exit 0 (SyntaxWarning previously emitted by `decodecheck.py` now gone) |
| Stdlib AST undefined-name scan over all 72 source files | **0** unresolved names; previously `Com/draw.py:36` and `Com/inline.py:107` used `asyncio` without importing it |
| Import + `setup()` smoke test for all 65 command modules, with stubbed `telethon`/`aiohttp`/`psutil`/etc. | **65/65 loaded, 155 handlers registered, 0 failures** (before fixes: `decodecheck`, `inline` and others failed to import) |
| `safe_eval` behaviour: 6 valid expressions match `eval` results; 7 hostile/unsupported expressions blocked | pass |
| `SmartMarkov` save→load round-trip; model containing `__import__('os').system(...)` as a key | round-trip works; hostile key ignored, 4 valid states kept |
| `Com/core/storage.py`: write/read, corrupt-file fallback, missing-file default, no `.tmp-` leftovers, UTF-8 round-trip | pass |
| Wiring assertions (`send_inline` defined, lowercase paths, migration present, `inline` no longer imports a missing name) | pass |

**Not executed — do not treat as verified:**

- **No live Telegram run.** Telethon is not installed in this environment and
  adding it is forbidden by your constraints, so `client.connect()`,
  `StringSession` authorization, real handler dispatch, and every actual
  Telegram API call are **untested**. The smoke test only proves that modules
  import and register handlers.
- **Handlers were not executed against events.** `!calc`, `!enemy list`,
  `!portsweep`, `!sysinfo`, `!inline`, `!warn`, `!mute`, `!update`, `!draw`,
  `!wordlist` and the rest were reviewed statically and their helpers tested, but
  no end-to-end command flow was run.
- **`dashboard.py` was not started** (Flask is not installed here) and no page
  was rendered.
- **Modules whose third-party library is absent were imported against stubs**
  (`psutil`, `PIL`, `PyPDF2`, `mutagen`, `moviepy`, `gtts`, `qrcode`, `pygments`,
  `dns`, `faker`, `pytz`, `aiohttp`). Import wiring is proven; their real
  behaviour is not.
- **No tests or linters exist in the repository**, so none were run beyond what
  is listed above.

---

## 6. Unresolved issues and recommendations

**Not applied — needs your decision or would violate a constraint**

1. **`Com/settings.json` toggles are inert** (L1). Wiring
   `enemy_enabled`/`warn_enabled`/`mute_enabled`/`stats_enabled`/`auto_solve`/
   `reply_enabled` into their handlers would make existing dashboard switches
   start disabling features — a behaviour change I did not make unilaterally.
2. **`project_files.txt`** (L5) is a stale 7,245-line dump of the source. Delete
   it (and optionally add `project_files.txt` to `.gitignore`); nothing reads it.
3. **`mode/` operational data is tracked** (L6): real chat/user IDs, scan output
   for third-party domains, and a Git-LFS `rockyou.txt`. Removing it from git is
   safe for the repository but a `git pull` on an unmodified Replit checkout
   would delete those files there — so this needs to be done deliberately (back
   up `mode/` first, then `git rm --cached -r mode mods`).
4. **Session files remain in git history.** Untracking stops future leaks but
   does not revoke what is already published. Do, in order: (a) terminate the
   session in Telegram → Settings → Devices for the affected account, (b) rotate
   `BOT_TOKEN` via @BotFather, (c) rewrite history (`git filter-repo --invert-paths
   --path bot.session --path bot_session.session --path pyro_session.session`) and
   force-push, (d) optionally delete the repo and re-create it. I did not rewrite
   history or force-push.
5. **`dashboard.py` still has no authentication.** If you expose it publicly,
   put it behind Replit's private deployment or add a login; `DASHBOARD_DEBUG=1`
   re-enables the RCE-capable debugger and should never be set publicly.
6. **Per-message JSON reads** (M7) are the main remaining performance issue. A
   scoped fix would be an in-memory cache in `Com/core/storage.py` (load once, write
   through) plus a single shared catch-all dispatcher instead of one
   `events.NewMessage()` handler per feature. That is an architectural change and
   was deliberately left out of this pass.
7. **`Com/reaction.py`** adds a global handler per reaction task and only removes
   it on `!reaction stop` (L7); tasks restored from `mode/reactions.json` are
   re-registered every boot. Bounding the number of tasks and using one
   dispatcher with an in-memory map would fix it.
8. **`Com/kill.py` / `Com/setkill.py` / `Com/f.py`** can post messages
   indefinitely at intervals; there is no global rate limit or "stop all".
9. **Unbounded `mode/` growth**: `stats.json` (`Com/stats.py`) accumulates every
   word/emoji/mention ever seen per chat and is rewritten in full per message, so
   it grows without limit. Consider capping `word_counts` to the top N per chat.

**Dependency-related (explicitly NOT applied)**

10. `requirements.txt` declares only `aiohttp` and `python-telegram-bot`, but the
    code imports `telethon`, `flask`, `psutil`, `pytz`, `dnspython` (`dns`),
    `Pillow` (`PIL`), `PyPDF2`, `mutagen`, `moviepy`, `gtts`, `qrcode`,
    `pygments`, `faker`, and `openai`/`numpy` (declared in `pyproject.toml`
    only). `python-telegram-bot` is **never imported**. On Replit this works only
    because `.pythonlibs` was populated by hand; a clean rebuild will fail
    module-by-module (silently — `main.py` swallows the errors). Recommendation:
    align `requirements.txt` with reality and drop the unused
    `python-telegram-bot`. Not changed, per your constraint 1/2.
11. `pyproject.toml` pins `python = ">=3.8.0,<3.9"` while `.replit` declares
    `modules = ["python-3.8"]` and the workflow runs `.pythonlibs/.../python3.10`,
    and this audit ran on 3.12. The Poetry metadata is stale and contradictory.
    Recommendation: relax the Python constraint and pin one interpreter version.
12. `moviepy` (used by `Com/mediatools.py`) is unmaintained and heavy; the
    `PIL`/`PyPDF2`/`moviepy` imports at module top also slow startup. Not touched.

**Replit-specific concerns for a human**

13. The Run command depends on `.pythonlibs/` existing in the Repl; it is not in
    the repository (and is now gitignored). A fresh clone cannot start until
    that environment is rebuilt.
14. `!update` restarts via `os.execv`; Replit's supervisor may or may not
    re-exec the workflow. If restarts look unreliable, use the Replit Stop/Start
    button instead.
15. `.replit` declares port 5000 but the entry point never listens on it —
    nothing serves HTTP unless you run `dashboard.py` separately.

---

## 7. Final verdict

**Is it better?** Yes, materially:

- The three confirmed code-execution paths are gone (`eval` on group text, and on
  model files), and the dashboard no longer ships an enabled debugger.
- Six features that were dead or lying to you now work or report honestly:
  `!inline` (never loaded), `!botstatus` (always "not connected"), `!decodecheck`
  (module import failure), `!sysinfo` (silent failure), `!portsweep` (results
  filed nowhere), and the bot's `/warns`/`/mutes`/`/set_warn`/`/add_mute` family
  (writing to files nothing else read).
- All state files withstand a crash mid-write, and Persian text is stored as
  UTF-8 instead of `\uXXXX` escapes.
- Startup fails fast and loudly on a bad session instead of hanging, and broken
  modules are listed instead of vanishing.
- 65/65 command modules now import and register cleanly (previously at least
  `inline.py` could not import at all on any interpreter, and `decodecheck.py`
  could not on this one).

**What remains risky?**

- Session credentials are still in git **history** until you revoke and rewrite
  (§6.4). This is the most urgent remaining item.
- No live Telegram validation was possible here — every fix is
  statically/unit-verified only. Test the changed commands in a private chat
  before relying on them in groups.
- The dashboard remains unauthenticated and unstarted by the entry point.
- Per-message JSON reads and unbounded `stats.json` growth will get slower as the
  bot accumulates chats, and `reaction.py` handler registration grows with tasks.
- The project cannot be rebuilt from `requirements.txt` alone.

**Review before deploying:** the four behaviour-changing fixes are
`Com/warn.py` + `Com/mute.py` + `Com/enemy.py` (names instead of IDs — H4),
`Com/bot/client.py` (unified warn/mute state + one-time migration — H1), `main.py`
(exit instead of interactive auth; sorted load order), and
`Com/portsweep.py`/`Com/reply.py` (single-port support; 20 MB attachment cap).
Everything else is intended to be behaviour-neutral.
