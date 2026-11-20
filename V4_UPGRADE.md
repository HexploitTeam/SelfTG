# SelfTG v4 — rate-limit policy, cheaper hot paths, repeatable validation

Branch `beta`, base `2e2cf39`. Free Replit tier, Secrets only, **no dependency
changes**, no rewrite. This pass executes the first four phases of the v4 plan;
Phase 3 (owner-check consolidation across all 74 modules) is deliberately not
started — see §6.

---

## 1. What changed, and why

### 1.1 One rate-limit policy (`Com/core/flood.py`)

Before: three separate answers to the same question. Telethon slept through
FLOOD_WAITs (`flood_sleep_threshold` at its default 60 s, set nowhere in the
code), nine modules caught `FloodWaitError` with their own wording, and the
commands that emit a *series* of messages — `!kill`, `!repeat`, `!setkill`,
`!f start` — slept on a fixed clock (1 s, 0.2 s, exact interval, 5 s) with no
jitter and nothing to stop the next burst after a penalty.

After: one module with three rules.

| Part | Behaviour |
| --- | --- |
| `pace(chat_id, gap)` | every message of a series waits a jittered gap (±30 %), per chat; called *before* each send |
| `note_flood(seconds)` | records a FLOOD_WAIT; three inside 10 minutes opens the breaker |
| `cooldown_left()` / `describe()` | 15-minute send pause (or the server's own wait, if longer), reported to the chat once |

`flood_sleep_threshold=60` is now explicit on **both** clients so the policy is
visible in the code instead of implicit in a library default. Nothing here makes
the bot faster: every change adds delay.

Wiring: `!kill`, `!repeat` (nothing on the fixed 0.2 s burst), `!setkill`
(interval jittered ±15 %, timer pauses while the breaker is open, stops and says
so after repeated floods), `!f start` (jittered 5 s, pauses, stops). `whois`
keeps its 7 s wait — that is a wait for *another bot's reply*, not send pacing,
and changing it would break the command.

### 1.2 Per-message reads removed from the hot path (`Com/core/storage.py`)

`enemy`, `monitor`, `reply`, `cauto` and `stats` each hold a catch-all
`NewMessage` handler; four of them re-parsed their JSON for *every message in
every chat*. `cached_json(path, default)` memoises the parsed document and
validates it against `(st_mtime_ns, st_size)`, so:

* steady state = zero parses per message;
* a write from this process invalidates it (the stat key changes);
* a write from `dashboard.py` (separate process) invalidates it too — no stale
  cross-process reads, which is the risk that made this worth validating before
  converting more than two modules.

`!stats` was already batched in the previous pass and is left alone.

### 1.3 Reaction tasks bounded (`Com/reaction.py`)

`!reaction` installs one catch-all handler per watched user and re-created them
on every boot with no limit. Capped at `MAX_TASKS = 20` with a visible refusal
that names `!reaction stop`; stored tasks beyond the cap are not restored and are
logged. The module's `print()` calls became `log` lines.

### 1.4 Bot state housekeeping (`Com/bot/kit.py`, `Com/bot/client.py`)

Expired flows and confirmation tokens were pruned lazily, i.e. only when the
owner reopened that screen, so `mode/botstate.json` kept dead entries — and the
chat ids inside them — for as long as the bot ran. `kit.prune()` runs from the
existing 30 s heartbeat: no new task, bounded file.

### 1.5 Library drift is now visible (`main.py`)

`_check_telethon()` logs the resolved version, warns when it is not the pinned
`1.33.1`, and **warns when both `Telethon-repl` and plain `Telethon` are
installed** — the shadowing failure described in `REPLIT_UPGRADE.md` §1.1, which
otherwise shows up as a mysterious connection failure.

### 1.6 Repeatable validation (`tools/smoke.py`)

The 573 ad-hoc checks from earlier passes lived in `/tmp` and vanished with the
sandbox. `tools/smoke.py` is in the repo (outside `Com/`, which holds command
modules only) and checks compile, six shared helpers, the per-message loaders,
and that every module imports and registers handlers against a stub client.

---

## 2. Dependency changelog

**No dependency changes.** No new import outside the standard library and
`telethon`; `requirements.txt` is untouched. `aiosqlite` remains rejected: JSON
plus a validated cache covers this data size, and a second engine would mean a
second crash-safety story.

---

## 3. Validation — verified here vs unverified

Run in this sandbox (CPython 3.12, real `Telethon-repl` 1.33.1 from the pin, all
runtime dependencies installed from `requirements.txt` except `moviepy`, which
no module needs at import time):

| Check | Result |
| --- | --- |
| `python3 tools/smoke.py` | **exit 0** — 99 files compile, 6/6 helper checks, per-message loaders exercised twice, 75 modules / 169 handlers |
| `flood` unit behaviour | two floods leave the breaker closed, the third opens it for ≥900 s; `reset()` closes it; jitter stays in 0.7–1.4× |
| Storage cache | document reused on the second read; write-through visible immediately; an **external** rewrite of the file invalidates the cache |
| Per-message loaders | `monitor.load_data`, `enemy.load_state`, `enemy.load_json`, `reply.load_data` called twice each against the real `mode/` files |
| `!react` regression harness (78 checks) | 0 failures |
| Callback budget | `kit.cb` still refuses >64 bytes; round trip unchanged |

One defect was caught by this pass's own tooling: `monitor.py` used
`cached_json` without importing it — it compiled fine and only failed at the
first message. The loader check exists so that class of bug cannot stay hidden.

**Not verified (no account, no Repl):** any real send, edit, pin, poll, reaction,
reminder delivery, the actual FLOOD_WAIT responses, `/setkill` and `!f` timing on
a live chat, and Replit-side install/sleep behaviour. Jitter and breaker
arithmetic are tested; the *experience* of being rate-limited is not.

---

## 4. Free-tier fitness

* No new dependency, no new process, no new socket, no new asyncio task (the bot
  sweep rides the existing heartbeat).
* Steady-state per-message cost went **down**: four catch-all handlers no longer
  touch the disk.
* Memory: one parsed document per state file in the cache (a dozen small files),
  reaction tasks capped at 20. Previous measurement was ~94 MiB with everything
  loaded; this change does not add a library.
* The binding limit is unchanged and cannot be fixed in code: 1200
  development-minutes per month ≈ 20 hours, so the bot is asleep most of the
  time. Everything above survives sleep because it lives on disk.

---

## 5. Risk register, as mitigated

| Risk | Mitigation actually shipped |
| --- | --- |
| Account flagged for automation | No volume increase; jitter only slows; breaker stops bursts; floods never retried |
| Floods cascading | Three strikes in 10 min → 15 min global send pause, announced in the chat, reset by the breaker's own clock |
| Handler reading stale state | Cache invalidated by mtime+size, tested against an external writer |
| Missing import that still compiles | `tools/smoke.py` calls the per-message loaders (found one) |
| Library shadowing / drift | Startup warning, with both distribution names and versions |
| Unbounded `botstate.json` | 30 s sweep, bounded by flow/pending TTLs |
| Handler growth in `!reaction` | Cap 20 with a visible refusal |

---

## 6. Deferred, with reasons

1. **Phase 3, one owner-check helper across every module.** Not started. Doing it
   for six of 74 modules would create exactly the inconsistency the change is
   meant to remove, and a 74-file mechanical sweep is not reviewable inside this
   pass. Current state is unchanged and still safe: every handler is registered
   with `from_users=my_id`, and the newest families (`ban`, `pin`, `chat`,
   `!react`) also check `event.out`/sender inside the handler.
2. **`!stats` top-N cap.** A data-shape change to a file that already holds
   historical data; it needs a deliberate decision about what to discard, so it
   stays out of a "cheap hot path" commit.
3. **`!reaction` single dispatcher.** The cap bounds the damage; replacing the
   per-task handler with one dispatcher is a behaviour-preserving refactor that
   deserves its own commit and its own tests.

---

## 7. Manual checklist on Replit

1. Rebuild → confirm `requirements.txt` installs (unchanged, but this is the
   first boot after the untracking) and that the log shows
   `telethon 1.33.1 (pinned)`.
2. `python3 tools/smoke.py` in the Repl shell → expect all checks green with
   `moviepy` present.
3. `!kill 3` in a private chat → messages arrive ~1 s apart, unevenly.
4. `!repeat 3 hi` → three copies, uneven gaps, command message deleted.
5. `!setkill start 5 hi` → interval varies slightly; `!setkill stop`.
6. Force a flood (send a rapid series in a busy chat) → the command stops with a
   count ("stopped after N of M"), and after three floods the breaker line
   appears instead of more sends.
7. Open the bot, start a flow, leave it >15 min, `/status` → the flow is gone
   from `mode/botstate.json` without reopening that screen.
8. `!reaction` to 20 users, then a 21st → refused with the cap message.
