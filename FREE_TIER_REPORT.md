# SelfTG — Replit free-tier fitness report

Branch `beta`, working tree (not committed). Builds on the transport/manifest work already
applied in `REPLIT_UPGRADE.md`; this pass targets the **free (Starter) plan** specifically.

---

## 1. Research findings

### 1.1 What Replit's free tier actually is

Sources: [Usage Quota & Limits](https://docs.replit.com/legal-and-security-info/usage),
[Pricing](https://replit.com/pricing) (plan table),
[Outbound data transfer](https://docs.replit.com/additional-resources/outbound-transfer),
[Always On](https://replit.com/blog/alwayson), [Secrets](https://docs.replit.com/core-concepts/project-editor/app-setup/secrets),
[Account inactivity](https://docs.replit.com/legal-and-security-info/account-inactivity).

**Officially documented (verified):**

- Per-app CPU, RAM, storage and bandwidth are *plan-determined* hard/soft limits. Replit
  does not publish them in the docs page — only in the pricing table.
- Replit imposes, **regardless of plan**, "a limit on the number of concurrent outgoing
  network connections in a given period" and soft network-bandwidth limits, and may
  throttle or disable egress when the plan's outbound allowance is exhausted.
- Repls sleep. Replit's own Always On announcement: *"when your repl is inactive for a
  little while it automatically goes to sleep"*, and Always On exists to *"keep it running
  even if you close your Replit browser tab."* Always On is a paid capability — Replit's
  current docs price **Reserved VM ("Bots, background work, always-on APIs — one dedicated
  server that never sleeps") at $15/month**. That is out of scope by constraint 1.
- Secrets are AES-256-encrypted and injected into the running process as **environment
  variables**; they are readable with `os.getenv`. They are *not* available to Static
  Deployments. A new secret is picked up by the process only after a **Stop → Run**.
- Account inactivity: a free account unused for a year may be terminated and its Apps
  deleted.

**Numbers from the pricing-page plan table** (that page renders its table client-side; these
values come from the plan table as indexed for `replit.com/pricing` — treat as current but
subject to change):

| Starter (free) | Value |
| --- | --- |
| Memory per App | **2 GiB** |
| Storage per App | **2 GiB** |
| Development time | **1200 minutes / month** |
| Outbound data transfer | 1 GiB (development row) / 10 GiB (deployments) |
| Public Apps | 10 |
| Private Apps | none |
| Concurrent Replit Apps | 20 |

**Not confirmed:**
- The exact idle timeout. Third-party guides say **~5 minutes** for free Repls; Replit's
  docs state only "inactive for a little while". Treat 5 min as indicative, not contractual.
- "Free Repls are public by default" comes from third-party security writeups; Replit's
  pricing table corroborates it indirectly (`Starter → Public apps only, no private apps`).
- Whether the single published app expires after 30 days (third-party claim).

### 1.2 The constraint that actually decides this project's fate

It is **not RAM, and not the port**. It is **1200 development minutes per month**:

- 1200 min = **20 hours of runtime per month**.
- A self-bot that must be online 24/7 needs ~730 hours — about **36× the allowance**.
- Keeping it up for **one single day** (1440 min) already exceeds the *entire month's* budget.

So on the free tier this cannot be an always-on bot, at any memory footprint. That is a
plan limitation, not a code defect, and per constraint 1 it is reported rather than
engineered around. The realistic free-tier operating model is: **the bot runs while you are
working in the Repl**, and is asleep the rest of the time. Everything I changed is aimed at
making those windows cheap to start, cheap to run, and safe to lose.

### 1.3 Python and packaging on the Repl

Carried over from `REPLIT_UPGRADE.md` and re-confirmed: retired module IDs `python-3.8`/
`3.9` resolve to **Python 3.10**; with `poetry.lock` present Replit uses poetry (not pip),
and that lock's `python = ">=3.8,<3.9"` made installation impossible. Both files are
removed; `requirements.txt` is now the single pinned manifest.

### 1.4 Telegram library and network rules

- Telegram's [MTProto transports](https://core.telegram.org/mtproto/transports) documentation:
  TCP "over a plain TCP socket on ports **80, 443, 5222** or other (a different port number
  may be returned by `help.getConfig`)", **but** "if the `this_port_only` dcOption flag is
  set, clients must use only the specified port, without trying any other port."
- `Telethon-repl` 1.33.1 hardcodes `self._port = 5222` for every connection (verified in the
  wheel). It therefore **cannot honour `this_port_only`** if Telegram ever sets it on a DC.
  That is a real, if latent, risk — and the reason `Com/net.py` keeps the port in project
  code rather than only in the dependency.
- I still could not verify from a primary source that free Repls block 443 egress today.
  The 5222 requirement is community/fork-derived. `TELEGRAM_DC_PORT` remains the escape
  hatch (only effective with upstream `telethon`, which honours the passed port).

### 1.5 Telegram-side constraints that matter on tiny hardware

Telethon's own docs warn that third-party Telegram libraries can get an **account banned**
if used against the ToS. Nothing I changed raises request volume, and
`flood_sleep_threshold` is left at its default so FLOOD_WAIT is auto-slept rather than
retried. The per-message work below is about CPU/IO, not about sending faster.

---

## 2. Dependency changelog

**No dependency changes this pass.** Deliberate:

| Considered | Decision | Why |
| --- | --- | --- |
| Drop `moviepy` (+`numpy`, `imageio-ffmpeg`) | Keep | Only loader of `!videometa`; already lazily imported, measured **+2 MiB** at runtime (see §4). Removing it would delete a command. |
| Drop `flask` | Keep | `dashboard.py` is a shipped feature; not loaded by `main.py`, so it costs nothing at runtime. |
| Drop `cryptg` | Keep | C AES is a net CPU win on shared vCPU; ~100 KiB; Telethon falls back if it fails. |
| Add TensorFlow for `ML/*_model.py` | **No** | Those modules are imported by nothing; TensorFlow would consume most of the 2 GiB and cannot train within a 1200-min budget. |
| Switch to upstream `telethon` | **No** (still) | 1.45.0 removed `KeyboardButtonCallback`/`KeyboardButtonUrl`, which `Com/bot.py` and `Com/inline.py` import. Documented in `REPLIT_UPGRADE.md` §1.1. |
| Pin anything new | None needed | No new imports were introduced. |

The pinned set from `REPLIT_UPGRADE.md` §2 stands unchanged, including the security bump of
`aiohttp` 3.8.4 → 3.10.11 (CVE-2023-47627, CVE-2024-23334) and the removal of the unused
`python-telegram-bot`/`openai`/`numpy`/`telegram` entries.

---

## 3. Changes applied

### 3.1 Replit free-tier compatibility (CPU / IO / RAM)

| File | Change | Why | What could break |
| --- | --- | --- | --- |
| `Com/stats.py` | Stats document cached in memory; **one** flush per event instead of read→read→write; `!stats scan` batches and writes once | Every message your account sent triggered **two full JSON parses and one fsynced atomic rewrite** of `stats.json`. `!stats scan` did that per message, up to 5000 times — on a shared vCPU that is the most expensive thing the bot does while idle. Measured: 5 messages went from 10 reads + 5 writes to **1 read + 5 writes**; a 3-message batch from 3 reads + 3 writes to **1 write**. Durability is unchanged per event. | If `dashboard.py` were run *concurrently* and edited `stats.json`, the bot's cache would not see it until restart. The dashboard is a separate process that `main.py` never starts, and it was already write-conflicting before. A crash mid-`scan` loses only that command's unflushed batch. |
| `Com/aiml.py` | `get_messages(limit=N)` → `iter_messages(limit=N)`, keeping only text | `get_messages` materialises every `Message` (text, entities, media) first; `!aiml train 10000` held all of them at once. Streaming keeps only the strings the Markov model actually uses. | None functionally; same filter (`!`-prefixed skipped), same error path. |
| `Com/stats.py`, `Com/aiml.py` only | (no other module touched) | `Com/monitor.py` also parses its JSON per incoming message, but it holds moderation state; I chose not to touch moderation semantics for a small, small-file parse. Listed in §6. |

### 3.2 Secrets handling

| File | Change | Why | What could break |
| --- | --- | --- | --- |
| `Com/bot.py` | Helper bot now uses an **in-memory `StringSession()`** instead of the `bot_session` SQLite file | Free Repls are public by default, so an auth-key file on disk is credential material readable by anyone who can open the Repl — exactly what constraint 2 excludes. The bot can always re-authenticate from `BOT_TOKEN` in Secrets. After this change **no code path writes session material to disk**: the self-bot uses `SESSION_STRING` from Secrets, the helper bot holds its session in RAM. | Each start performs one fresh bot sign-in (a single cheap API call). A stale on-disk session no longer papers over a rotated token — a wrong `BOT_TOKEN` now logs `[BOT] Login failed: …` instead of silently reusing an old session. |

**Finding, not fixed by me:** three credential files still sit in the working tree —
`bot.session`, `bot_session.session`, `pyro_session.session` (28 KiB each, SQLite with auth
keys). They are already untracked and gitignored, and after this change **nothing references
them**, but on a public Repl they are still readable. I did not delete them because they are
your data. Recommended: `rm bot.session bot_session.session pyro_session.session` after
revoking those sessions in Telegram → Devices. They are also still in the public git history
on `main` (see `REPLIT_UPGRADE.md` §5).

### 3.3 Bug fixes found while doing the above

| File | Finding | Status |
| --- | --- | --- |
| `Com/stats.py` | Write amplification described above was a correctness *risk* too: every message rewrote the whole 68 KB document, so a kill during a write was a live window (the atomic rename covered it, at the cost of an fsync per message). | Fixed by batching. |
| `mode/sys/sysmon.json` | Confirmed in the committed data: the file is a **dict** (`timestamp`, `cpu`, `memory`…), not the list `Com/sysmon.py` appends to — hard evidence that `Com/sysinfo.py`'s old shared path had already destroyed the sysmon history. `mode/sys/sysinfo.json` exists separately with an older schema. | Split paths (previous pass) are correct; the sysmon log will reset to a list on the next run. |

---

## 4. Free-tier fitness statement

Measured in this sandbox (CPython 3.12, not the Repl's 3.10) with the real pinned packages:

| State | Peak RSS |
| --- | --- |
| `import main` | 65 MiB |
| all 65 command modules + 155 handlers registered | **94 MiB** |
| + `moviepy` (only imported by `!videometa`) | 96 MiB |

- **RAM:** ~94 MiB steady state against a **2 GiB** Starter limit — roughly 5% of the
  budget, leaving ample headroom for Telethon's entity/update caches and a chat-history
  scan. TensorFlow is never installed, so the 2 GiB is not at risk from the ML files.
- **CPU:** the per-message path no longer parses or rewrites JSON. Remaining always-on
  per-message work is `Com/monitor.py`'s single small-file parse, the (default-off) logger
  and auto-solver, and pattern-matched handlers that exit immediately.
- **Storage:** repo is 139 MiB of the 2 GiB per-app allowance, of which **134 MiB is
  `mode/rockyou.txt`** (Git LFS). That is ~7% of the budget for a file `!wordlist download`
  can fetch on demand — see §6.
- **Sleep/wake:** the process is killed by the plan, not by a bug. On wake it cold-starts in
  ~1 s of imports, re-reads secrets from the environment, reconnects with Telethon's 3
  internal retries then my bounded 5→60 s backoff, and writes state atomically. No tight
  reconnect loop, no partially written JSON.
- **Networking:** one long-lived outbound MTProto TCP connection (plus short-lived aiohttp
  requests per command) — well inside "concurrent outgoing connections" expectations, and
  text-only traffic is negligible against the 1 GiB development outbound allowance.
- **What remains tight:** the **1200 dev-minutes/month** (§1.2) — you cannot run this
  continuously; and **storage**, where one `!wordlist download` (~200 MB) plus the tracked
  copy consumes ~17% of the per-app allowance.

---

## 5. Validation results

Run here: `py_compile` all files with `-W error::SyntaxWarning`; a fresh venv installed from
`requirements.txt`; every command module loaded against a real Telethon client.

| Check | Result |
| --- | --- |
| Compile all 74 Python files | **pass** |
| Load all `Com/*` modules in a running loop, real `TelegramClient` | **65/65 modules, 155 handlers, 0 failures** |
| Stats: 5 counted messages | **1 file read, 5 flushes** (was 10 reads + 5 fsynced writes); `total_msgs` correct |
| Stats: `!stats scan` batch path | **0 extra reads, 1 flush** for a 3-message batch |
| `!aiml` fetch streams and filters commands | **pass** (`['keep me', …]`, `!command` skipped) |
| Bot client has no on-disk session | **pass** — `StringSession()` in `start_bot`, no `"bot_session"` path |
| Credential files left in tree | **finding** — 3 stale `.session` files, unreferenced, gitignored |
| Memory | 94 MiB peak with everything loaded (§4) |

Earlier passes (still valid, not re-run): cold-start errors for missing/bad secrets, bounded
reconnect against a refused port, graceful `SIGTERM` shutdown, cp310 wheel resolution.

**Requires Replit-side verification (not performed here — no Repl access):**
1. That the free Repl actually installs `requirements.txt` after the poetry removal.
2. Whether 5222 is still required, and that the connection succeeds from a free Repl.
3. Real sleep → wake behaviour and the actual idle timeout.
4. Your dev-minute balance (`Settings → Usage`) while the bot runs — this is the number that
   decides how long you can keep it up.
5. Live login with your real `SESSION_STRING` / `BOT_TOKEN`.

---

## 6. Remaining risks and recommendations

**Free-tier limits that cannot be solved without paying (reported, not worked around):**

- **Always-on is impossible.** 1200 dev-min/month does not cover a persistent process, and
  keeping a Repl awake (Reserved VM, $15/mo; Always On) is outside the free plan. Practical
  free usage: keep the workspace open while you want the bot online, and **stop the Repl when
  you are done** so the minutes are not spent while you are away.
- **Sleep interrupts the bot.** Reconnect is handled, but messages that arrive while the Repl
  is asleep get no reply — they are simply seen later, if at all.
- **No private Apps on Starter.** The Repl is public; never place credentials in files (this
  pass removes the last one the code created).

**Recommended, not done:**

- Delete the three stale `.session` files and revoke those sessions; the credentials also
  persist in public git history on `main` (needs `git filter-repo` + force-push).
- `mode/rockyou.txt` (134 MiB, LFS) is ~7% of the 2 GiB allowance and `!wordlist download`
  can re-fetch it; removing it from the *working tree* would not reclaim LFS storage, so the
  real fix is a history rewrite or leaving it alone.
- `Com/monitor.py` parses its JSON on every incoming message. Left alone deliberately:
  changing moderation state handling for a small-file parse is not worth the risk today.
- `dashboard.py` still has no authentication and is not started by `main.py`. On a public
  Repl, do not expose it.
- `telethon-repl` is frozen at 1.33.1 (Dec 2023) and ignores per-DC ports; if Telegram ever
  sets `this_port_only` (see §1.4), it will fail. The migration path is in
  `REPLIT_UPGRADE.md` §5.

---

## 7. Final verdict

**Is the project free-tier-compatible?** For the parts code controls, **yes** — it fits in
~5% of the Starter RAM, does no per-message disk I/O, holds no credentials on disk, starts
clean from secrets, and recovers from sleep without a reconnect storm. **It is not an
"always online" deployment on the free tier, and no code change can make it one**: the
1200-minute monthly development budget and Repl sleeping are plan limits, and the only
documented fix (Reserved VM / Always On) is paid.

**Cost of the change, per message:** from two JSON parses plus one fsynced rewrite of the
whole stats document, to a dict update and (once) a write.

**Test manually on Replit, in this order:**
1. Fresh Rebuild → confirm dependencies install and `python3 main.py` is the Run command.
2. Real secrets → see `✅ Connected as …`, then `[BOT] Bot is running`.
3. Send a few messages yourself, then `!stats` — confirm counts land and `mode/stats.json`
   is written once per message rather than per parse.
4. `!stats scan 500` on a busy chat — it should finish quickly and write the file once.
5. `!aiml train 200` — confirm it completes without a memory spike.
6. Stop the Repl from the UI → log should end with `Session closed.`
7. Open `Settings → Usage` after a session to see what the bot costs you in development
   minutes, and plan around that number.
