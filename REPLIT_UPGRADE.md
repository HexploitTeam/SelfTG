# SelfTG — Replit upgrade report

Scope: make the repository run and stay running on Replit, modernize dependencies where
that actually matters, and fix defects found along the way. Branch: `beta` (working tree,
not committed). `main` untouched.

---

## 1. Research verification

### 1.1 `telethon` vs `telethon-repl` — confirmed, with one correction

The repository did **not** depend on `telethon` in any manifest that Replit reads.
`requirements.txt` contained only `aiohttp==3.8.4` and `python-telegram-bot==20.7`;
every module imports `telethon`, which was installed only by hand, or not at all. A cold
Repl could not have started the bot.

`pyproject.toml` did declare `telethon = "^1.41.2"`, but see §1.3 — that file could not be
installed successfully either.

Verified against the actual published artefacts rather than the summary:

| Check | Result |
| --- | --- |
| `Telethon-repl` latest version | **1.33.1** (31 Jan 2024) — the only recent release; also 1.29.3, 1.28.5 |
| Its module name | `telethon` (distribution `Telethon-repl`) — so it shadows/conflicts with plain `telethon` |
| `Requires-Python` | `>=3.5` |
| Port handling in the wheel | `telethon/network/connection/connection.py`: `def __init__(self, ip, port, dc_id, *, ...)` then **`self._port = 5222`** — hardcoded, the `port` argument is ignored |
| Runtime proof | A client asked for port 443 and logged `Connecting to 149.154.167.51:5222/Replit` |

Correction to the working hypothesis: this is not a configurable "use 5222 on Replit"
switch. The fork forces 5222 for **every** connection, of **every** client, in any
environment. Anything that changes the port (proxy setups, local development, a future
`TELEGRAM_DC_PORT`) is silently overridden while this distribution is installed.

Upstream `telethon` version gap, measured by importing the symbols this repo uses:

| Version | `ReplyInlineMarkup`, `KeyboardButtonRow`, `KeyboardButtonUrl`, `Poll`, `ReactionEmoji`, … | `KeyboardButtonCallback` |
| --- | --- | --- |
| 1.33.1 (= `Telethon-repl`) | present | present |
| 1.35.0 | present | present |
| **1.41.2** (previously locked) | present | present |
| **1.45.0** (latest) | present | **removed** |

So: upgrading to latest upstream would break `Com/bot.py` and `Com/inline.py` (two
`KeyboardButtonCallback`/`KeyboardButtonUrl` imports) *and* still need a port override.
`Telethon-repl` is API-compatible with the code as written and needs no code change, which
is why it is the value shipped. The staleness cost is real and is listed in §5.

**Not verified:** whether Replit still blocks 443 egress. Replit's current docs describe
*inbound* port mapping and say nothing about outbound port restrictions, and this
sandbox has no Repl. 5222 is a valid Telegram DC port, the change is a drop-in, and it is
reversible (§5), but the premise itself needs a Replit-side check.

### 1.2 Effective Python version — 3.10

Three independent signals:

1. `.replit` requests `modules = ["python-3.8"]`.
2. Replit's own `replit/nixmodules` documentation states retired module IDs resolve
   forward: *"Python 3.8/3.9 to 3.10"*. A `python-3.8` Repl therefore runs **3.10**.
3. The repository's own run command pointed `PYTHONPATH` at
   `.pythonlibs/lib/python3.10/site-packages` — someone already discovered this the hard way.

Not measured on the Repl itself (no Repl access here); the sandbox is CPython 3.12.3.

### 1.3 The actual blocker nobody had spotted

Replit's docs: *"When you create a Python Replit App, your package manager is poetry by
default. This means pip install does not manage your dependencies."* With `poetry.lock`
committed, **poetry is authoritative and `requirements.txt` is ignored** — which explains
why that file had drifted into irrelevance.

And poetry cannot install this project on Replit, because `pyproject.toml` said:

```toml
python = ">=3.8.0,<3.9"
```

while the runtime is 3.10. Poetry refuses to operate when the running interpreter is not
allowed by the project. Between "wrong package manager" and "impossible Python
constraint", nothing in the repo could have produced a working dependency set on a cold
Repl.

### 1.4 Dependency set, before and after

**Before** — three conflicting sources of truth:

- `requirements.txt`: `aiohttp==3.8.4`, `python-telegram-bot==20.7` (no `telethon` at all).
- `pyproject.toml` (poetry): `python >=3.8.0,<3.9`, `numpy ^1.22.2`, `telegram ^0.0.1`,
  `telethon ^1.41.2`, `openai ^1.107.1`.
- `poetry.lock` (lock-version 2.0, 23 packages): the above plus transitive deps.
- Imported by the code but declared nowhere: `psutil`, `pytz`, `pygments`, `PIL`,
  `qrcode`, `PyPDF2`, `mutagen`, `moviepy`, `gtts`, `faker`, `dns`, `flask`,
  `googletrans`, `cryptg` (optional), `tensorflow` (dead code, see below).

**After** — one source of truth (`requirements.txt`), 18 exact pins, poetry removed.

---

## 2. Dependency changelog

| Package | Before | After | Reason | Replit impact | Risk |
| --- | --- | --- | --- | --- | --- |
| `telethon` | absent from `requirements.txt`; `^1.41.2` in pyproject | **`Telethon-repl==1.33.1`** | Only distribution that connects on port 5222; API-compatible with existing code | **Bot can connect at all** | Frozen at Dec 2023; see §5 |
| `python-telegram-bot` | `==20.7` | **removed** | No `telegram` import anywhere in the repo; unused | Smaller install, fewer conflicts | None — nothing imports it |
| `aiohttp` | `==3.8.4` | `==3.10.11` | 3.8.4 has open CVE-2023-47627 (header injection) and CVE-2024-23334 (path traversal) | Security fix; used by ~15 modules | API unchanged for these uses |
| `numpy` | `^1.22.2` (pyproject) | **removed as a direct dependency** | Only referenced directly by `ML/aiml_model.py` / `ML/lstm_model.py`, which **nothing imports** (and which pull TensorFlow) | It still arrives transitively as a `moviepy` dependency, so no install saving — but with `moviepy` now imported lazily it is only loaded into RAM when `!videometa` runs, which is what matters on 512 MB | None — verified unreachable |
| `tensorflow` | never declared | **deliberately not added** | Dead code: `main.py` loads `Com/*` only; `Com/aiml.py` uses `ML/smart_markov.py`, pure Python | Avoids a ~500 MB dependency that cannot fit Replit's RAM | None |
| `openai` | `^1.107.1` | **removed** | No `openai` import anywhere; it was the only reason a modern `httpx` was required | Smaller install, unblocks `googletrans` | None |
| `telegram` | `^0.0.1` | **removed** | Unrelated stub package on PyPI, not `python-telegram-bot`; unused | Removes a confusing name collision with the `telethon` module | None |
| `psutil` | undeclared | `==5.9.8` | Imported by `sysinfo`, `sysmon`, `uptime` | Makes those commands installable | Pinned, no change |
| `pytz` | undeclared | `==2024.1` | Imported by 6 modules | Installable | Chose over stdlib `zoneinfo`, which needs system tzdata that a Nix Python may lack |
| `Pygments` | undeclared | `==2.18.0` | `!syntax`, `!prettify` | Installable | Low |
| `Pillow` | undeclared | `==10.4.0` | Image commands | Installable | Low |
| `qrcode` | undeclared | `==7.4.2` | `!qr` | Installable | Low |
| `PyPDF2` | undeclared | `==3.0.1` | `!pdfinfo`, `!convertpdf` | Installable | Deprecated upstream (renamed `pypdf`), but 3.0.1 is the final working API for this code |
| `mutagen` | undeclared | `==1.47.0` | `!audiometa` | Installable | Low |
| `moviepy` | undeclared | **`==2.2.1`** | **1.x has been removed from PyPI** (only 0.2.x and 2.x are downloadable), so `moviepy.editor` cannot be installed at all | Fixes a latent hard failure | Required a code migration (§3.2) |
| `gTTS` | undeclared | `==2.5.1` | `!tts` | Installable | Low |
| `requests` | undeclared | `==2.32.3` | gTTS transport | Installable | Low |
| `Faker` | undeclared | `==24.14.0` | `!mock` | Installable | Low |
| `dnspython` | undeclared | `==2.6.1` | `!dnsprobe`, reverse DNS in `!ip` | Installable | Low |
| `Flask` | undeclared | `==3.0.3` | `dashboard.py` | Installable | Low |
| `googletrans` | undeclared (old pin `4.0.0rc1` gone from PyPI) | `==4.0.2` | `!translate`; 4.0.2 is the current release | Installable | Third-party scraping client, brittle by nature |
| `httpx` | nothing (old hazard: `googletrans 4.0.0rc1` forced `httpx==0.13.3`) | `==0.28.1` | Required by `googletrans 4.0.2` (`>=0.27.2`); the ancient pin is obsolete | Fixes a dependency dead end | Low |
| `cryptg` | absent | `==0.4.0` | C implementation of Telethon's AES/IGE path | Meaningful on 0.5 vCPU | Optional — Telethon falls back if it fails to load |
| `poetry.lock`, `pyproject.toml` | present (poetry authoritative) | **deleted** | See §1.3: the lock made Replit use poetry, and the pyproject pinned Python `<3.9`. Deleting both is Replit's documented switch to pip | Makes dependency install possible at all | **Largest workflow change** — see §5 |

---

## 3. Changes applied

### 3.1 Replit compatibility

| File | Change |
| --- | --- |
| `requirements.txt` | Rewritten: every imported package declared, exact pins, comments explaining the non-obvious ones. |
| `poetry.lock`, `pyproject.toml` | Deleted so Replit installs from `requirements.txt` (documented switch, and the only way past the `>=3.8,<3.9` constraint). |
| `Com/net.py` *(new)* | `ReplitConnection(ConnectionTcpFull)` pinning MTProto to 5222, plus `TELEGRAM_DC_PORT` override with validation. No `setup()`/`__HELP__`, so the loader imports it and registers nothing. |
| `main.py` | Client built with `connection=ReplitConnection`. |
| `Com/bot.py` | The helper **bot** client also uses `ReplitConnection`. Previously it would have used 443 even if the self-bot connected — a second client that silently never connects. |
| `.replit` | `modules = ["python-3.10"]` (explicit, no reliance on the retirement map); Nix channel `stable-21_11` → `stable-23_05` (2021 channel no longer in Replit's set); Run task `.pythonlibs/bin/python main.py` → `python3 main.py` (`.pythonlibs` only exists in poetry mode); `PYTHONUNBUFFERED=1`; the `[[ports]] 5000` mapping commented out (nothing serves it — `main.py` never starts the Flask app). |

### 3.2 Bug fixes

| File | Change | Why / what could break |
| --- | --- | --- |
| `Com/sysinfo.py` | `SYS_LOG_FILE` → `mode/sys/sysinfo.json` (was `mode/sys/sysmon.json`), atomic write | It wrote a **dict** to the file `Com/sysmon.py` keeps as a **list** of samples, every 5 s — each module destroyed the other's data and `!sysmon export` returned one snapshot instead of history. Old shared path is not migrated; only that log's history is affected. |
| `Com/sysinfo.py` | Background auto-log now opt-in (`SYSINFO_AUTOLOG=1`) and every 60 s instead of unconditional 5 s | It ran forever, wrote a file nothing else read, and burned a permanent wakeup on a 0.5 vCPU host. **Behaviour change**: no snapshot log unless the env var is set. `!sysinfo` itself is unchanged. |
| `Com/bot.py` | `start(bot_token=...)` → `connect()` + `is_user_authorized()` + `sign_in(bot_token=...)`, with the failure logged and the client closed | `start()` falls back to an interactive phone/code prompt when the token is rejected — on Replit that hangs forever. |
| `Com/mediatools.py` | `moviepy.editor` → lazy `from moviepy import VideoFileClip`; probe runs in `asyncio.to_thread`; clip closed in `finally` | `moviepy.editor` does not exist in installable versions; and decoding inside the handler froze the event loop. |
| `Com/translate.py` | `Translator().translate()` moved to `asyncio.to_thread` | It is a synchronous network call; it stalled every other handler while it ran. |
| `Com/uptime.py`, `Com/sysmon.py` | `psutil.cpu_percent(interval=0.5)` → `interval=None`, primed once at import | Blocked the event loop for 0.5 s per sample/command. Reading is now "since last call", semantically the same number. |
| `Com/sysmon.py` | Log capped at the newest 500 samples, atomic write | Unbounded at one sample per 2 s (~43k entries/day) on a Repl with very little disk. **Behaviour change**: `!sysmon export` returns the last 500 samples, not all history. |
| `main.py` | Graceful shutdown on `SIGINT`/`SIGTERM`; background tasks cancelled and awaited; `client.disconnect()` with a 10 s timeout | Replit stops a Repl with SIGTERM; previously the session was torn down mid-write. |
| `main.py` | Bounded exponential reconnect (5 s → 60 s cap), Telethon's own retries kept small (3) | Replit sleeps Repls and drops sockets. Previous code had no reconnect at all and no loop guard. |
| `main.py` | Bot task reference retained | `create_task()` results are only weakly referenced; an unreferenced task can be garbage-collected mid-flight. |
| `main.py` | Secrets read inside `build_client()`, validated with one-line messages; `SESSION_STRING` parsed with a readable error; non-numeric `API_ID` explained | Cold start determinism: import must not require secrets, and a bad secret must not look like a crash. |
| `main.py` | `sys.path` + working directory anchored to the project directory | State paths (`mode/`, `Logs/`) no longer depend on where the Repl was started. **Behaviour change**: process cwd is forced to the project root. |

### 3.3 Modernization / reproducibility

- Exact pins throughout (`==`), so a Replit Rebuild cannot silently pull a new major.
- `logging` instead of `print` for startup/connection lifecycle (timestamps in Replit logs).
- Commands still load deterministically in sorted order; the failure summary is kept.

No commands were removed, no handler was dropped, no flood protection or owner-only check
was touched. `flood_sleep_threshold` is left at Telethon's default (auto-sleep on
FLOOD_WAIT), and nothing raises request volume.

---

## 4. Validation

Run in this sandbox: CPython **3.12.3**, real packages installed from the new
`requirements.txt` into a fresh virtualenv. **Nothing was run against a live Repl or a
live Telegram account.**

| Check | Result |
| --- | --- |
| `py_compile` all 74 files with `-W error::SyntaxWarning` | **pass**, exit 0 |
| `pip install -r requirements.txt` (fresh venv) | **pass**, exit 0 |
| Import every declared package incl. `cryptg` | **pass**; `telethon 1.33.1`, `cryptg` importable |
| Wheel availability for Replit's **cp310 / manylinux2014** (`pip download --only-binary=:all:`) | 52 artifacts resolve, including native ones: `aiohttp-3.10.11-cp310`, `cryptg-0.4.0-cp310`, `Pillow-10.4.0-cp310`, `psutil-5.9.8-cp36-abi3`, `numpy-2.2.6-cp310` (transitive via `moviepy`). The only gap is **`pyaes`** (Telethon's dependency), published **only as a source distribution**: pure Python, no `.c`/`.pyx`/`.so` in the sdist, so it builds with setuptools and needs no compiler. |
| Handler smoke: load every `Com/*` module inside a running loop with a real client | **65/65 modules, 155 event handlers, 0 failures** |
| Port override | Requested 443, `ReplitConnection` used **5222** |
| Cold start, no secrets | `❌ SESSION_STRING is not set…`, exit 1, no traceback |
| Cold start, non-numeric `API_ID` | `❌ API_ID must be the numeric api_id…`, exit 1 |
| Cold start, malformed session | `❌ SESSION_STRING is not a valid Telethon StringSession (ValueError: Not a valid string)`, exit 1 |
| Reconnect policy (connection refused) | 3 Telethon attempts at 5 s, then `selftg: Connection error … retrying in 5s`, then a fresh attempt — no tight loop, no crash |
| Graceful shutdown (SIGTERM via `timeout`) | `Disconnection … complete!` then `Session closed.` |

### Requires Replit-side verification

1. **That the Repl actually installs** `requirements.txt` after the poetry removal, and that
   `pyaes` builds from sdist there.
2. **That port 5222 is the right port today** — i.e. whether 443 egress is still blocked.
3. `modules = ["python-3.10"]` + `channel = "stable-23_05"` — chosen from Replit's current
   docs, not tested against a live Repl build.
4. `cryptg` on Nix Python: the manylinux wheel may not match Nix's loader paths; it built
   and imported fine here, but Replit may need it built from source. If it fails, Telethon
   falls back automatically — removing the line is safe.
5. **`!videometa` needs an `ffmpeg` binary**, which is a Nix system dependency, not a Python
   package. I did not add `pkgs.ffmpeg` to `replit.nix` (no `replit.nix` exists, and adding
   packages to `.replit`'s `[nix]` block blind is riskier than useful). If that command
   matters, add it via Replit's Dependencies tool.
6. The **real login path** (`is_user_authorized` true, `get_me`, command dispatch) — needs
   real secrets and network.

---

## 5. Remaining risks and recommendations

**`Telethon-repl` is frozen at 1.33.1 (Dec 2023)** while upstream is 1.45.0. It works with
this code today, but it will eventually drift from Telegram's MTProto layer. Documented
escape hatch, requiring no code change in `main.py`:

1. `requirements.txt`: `Telethon-repl==1.33.1` → `telethon==1.41.2`
   (not 1.45.0 — see the `KeyboardButtonCallback` table in §1.1).
2. `TELEGRAM_DC_PORT=5222` stays the default in `Com/net.py`, and **with upstream telethon
   the env override actually works** (the fork is what ignores it).

**Replit platform limits you should plan around:** free/entry Repls sleep after
inactivity and resume cold — the bot will not be online while the Repl sleeps; Always-On is
paid. RAM is tight (~512 MB): the two TensorFlow modules remain in the tree as dead code
and will crash the Repl if anything ever imports them; I left them in place rather than
delete features, but deleting `ML/aiml_model.py` and `ML/lstm_model.py` is the cleanest
saving. Disk is small, which is why the sysmon log is now capped.

**Carried over from the previous audit, still true and still yours to decide:**

- The three `.session` files are deleted from the tree but **remain in git history**, and
  `main` is public. Revoke those sessions in Telegram → Devices, regenerate `BOT_TOKEN`,
  then purge history (`git filter-repo` + force-push) — destructive, so I have not done it.
- `dashboard.py` has **no authentication** and is not started by `main.py`. Do not expose
  it until it has a login.
- `mode/settings.json` toggles are still read by nothing.

**Deliberately not changed:** no architecture rewrite, no new abstraction over commands, no
async rewrite of the remaining synchronous file I/O (the JSON writes are small and atomic
now), no touching `Com/update.py`'s `os.execv` restart path, and no bumping unrelated
packages that happened to have newer versions.

---

## 6. Verdict

**Is SelfTG Replit-native now?** In the parts that decide whether it can run: **yes, as far
as is verifiable without a Repl.** It has a single pinned manifest, it uses the transport
port Replit needs for *both* clients, it starts deterministically from secrets, it survives
disconnects with bounded backoff, and it shuts down cleanly on SIGTERM. What remains
unproven is the Repl-side install and the live login (§4).

**Single highest-impact change:** the manifest fix — deleting `poetry.lock` /
`pyproject.toml` and rewriting `requirements.txt` with `Telethon-repl`. Before it, the
repository had no path to an installed Telethon on a cold Repl at all: poetry was
authoritative, and its Python constraint excluded the runtime. The 5222 transport is what
makes the connection work; the manifest is what makes it exist.

**Test manually, in this order:**
1. Fresh Rebuild on the Repl — confirm `requirements.txt` installs (watch for `pyaes`
   building) and `python3 main.py` appears as the Run command.
2. Real secrets → confirm the `✅ Connected as …` line, then that the helper bot logs
   `[BOT] Bot is running`.
3. `!sysinfo`, `!uptime`, `!qr`, `!translate`, `!videometa` (expect `ffmpeg` issues),
   `!sysmon start` → `!sysmon stop` → `!sysmon export`.
4. Stop the Repl from the UI and confirm the log ends with `Session closed.`
   (graceful shutdown) instead of a traceback.
5. Leave it idle long enough for the Repl to sleep, then interact — confirm reconnect
   without a manual restart.

Changes are staged in the working tree on `beta` and **not committed**; say the word and I
will commit (and push, if you want that too).
