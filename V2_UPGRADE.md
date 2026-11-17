# SelfTG v2 — ban family, `!chat`, four new commands, free-API rework

Scope: Replit **free (Starter) tier** only, credentials in Replit Secrets only, no
rewrite from scratch, every dependency change documented, no secrets printed.

Branch: `beta` (never `main`). Base commit: `ba9f870`.

---

## 1. `!ban` family

### 1.1 Syntax

| Command | Behaviour |
|---|---|
| `!ban <user> [reason]` | Permanent ban (`view_messages=False`, no `until_date`) |
| `!ban temp <user> <duration> [reason]` | Timed ban via `until_date`; also accepts reply form `!ban temp 10m spam` |
| `!ban unban <user> [reason]` | Lifts the restriction (all rights reset to default) |
| `!ban kick <user> [reason]` | Ban immediately followed by unban — they can rejoin via invite |
| `!ban list` | Bans **tracked by this bot** for this chat, with expiry |
| `!ban info <user>` | Live `get_permissions` state + tracked reason/expiry |

`<user>` = reply to their message, `@username`, or numeric ID.
Durations: `30m`, `2h`, `7d`, `1w`, `1d12h`. Minimum 60s, maximum 366 days.

### 1.2 Permission and owner model

* MTProto has no standalone "ban" request. Banning is
  `channels.editBanned` with `view_messages` forbidden, which is exactly what
  `client.edit_permissions(..., view_messages=False)` sends. Kicking is the
  documented Telethon pattern: ban, then `edit_permissions(...)` with no
  restrictions. No request type was invented.
* **Owner-only, twice.** Every handler is registered with `from_users=my_id`
  (the project's existing convention) *and* re-checks
  `event.out and event.sender_id == my_id` inside the handler. There is no
  "other admins may ban" path in this repository and none was added.
* **Basic groups are refused, not faked.** Telethon raises
  `ValueError('You must pass either a channel or a supergroup')` for a `Chat`,
  because Telegram's API only exposes chat-wide default permissions there. The
  command says so and tells the owner to convert to a supergroup. This was read
  from the installed `telethon/client/chats.py`, not assumed.
* Errors are translated to one actionable line each: `ChatAdminRequiredError`,
  `UserAdminInvalidError`, `ChannelInvalidError`, `UserIdInvalidError`,
  `PeerIdInvalidError`, `UserNotParticipantError`, `ChatWriteForbiddenError`,
  `ChannelPrivateError`, `FloodWaitError` (with `.seconds`), and `ValueError`
  for the basic-group case. Nothing is swallowed silently.

### 1.3 Tempban persistence and restart behaviour

* The ban itself is enforced **by Telegram** through `until_date`, so it keeps
  working while the Repl sleeps, restarts, or is redeployed. No in-memory timer
  is involved anywhere.
* `mode/bans.json` (atomic write via `Com.storage.save_json`) is only the bot's
  ledger for `!ban list` / `!ban info`. It is deliberately **not** replayed on
  boot: re-applying stored bans would resurrect bans the owner had lifted
  through the Telegram UI.
* `load_bans()` drops entries whose expiry has passed; `!ban info` additionally
  asks Telegram for the live state and says so if the ledger disagrees.
* Telethon's own docs warn that an `until_date` **shorter than 30s or longer than
  366 days becomes permanent** — hence the 60s floor and 366-day ceiling in
  `parse_duration()`.
* `!ban list` shows only tracked entries and labels them as such; it never
  invents a ban it did not record, and caps output at 40 lines.

### 1.4 Flood behaviour

One user per invocation, so there is no ban loop to throttle. `FloodWaitError`
is reported with the remaining seconds and the message states the ban was **not**
applied; nothing is retried automatically.

---

## 2. `!chat` formatting family

### 2.1 Styles

| Style | Entity | Composes (`+`) | Notes |
|---|---|---|---|
| `bold` | `MessageEntityBold` | yes | |
| `italic` | `MessageEntityItalic` | yes | |
| `underline` | `MessageEntityUnderline` | yes | |
| `strike` | `MessageEntityStrike` | yes | `strikethrough` alias |
| `spoiler` | `MessageEntitySpoiler` | yes | Present in the resolved Telethon 1.33.1 — verified by import, no fallback needed |
| `code` | `MessageEntityCode` | yes | inline monospace |
| `mono` | `MessageEntityPre(language="")` | yes | preformatted block; `pre` alias |
| `quote` | `MessageEntityBlockquote` | yes | present in 1.33.1; `blockquote` alias |
| `plain` / `unformat` | none (`formatting_entities=[]`) | — | strips formatting |

Combination: `!chat bold+italic <text>` produces two entities at the same
offset, which Telegram renders as bold italic.

### 2.2 Behaviour

* Edits **in place**: `client.edit_message(chat, command_message_id, text,
  formatting_entities=...)`, so the `!chat …` prefix disappears and the message
  becomes the formatted text.
* Entities only, never `parse_mode` — text containing `*`, `_`, `<`, `>` or
  backticks is sent byte-for-byte.
* `!chat <style> all <text>` is an explicit alias for the basic form.
* `!chat <style> on|off`, `!chat off`, `!chat status` control per-chat
  auto-format, persisted in `mode/chat_format.json` (atomic write). Unreadable
  store → auto-format off, never a crash ("fail open").
* Empty text (`!chat bold`): edits the command message to a usage hint.
* Reply form: the **command message** is rewritten with the replied text; the
  replied message is never modified.
* Media: auto-format explicitly **skips** messages that carry media and logs the
  skip. Editing a caption through `messages.editMessage` risks the attachment,
  and a self-bot must not gamble with the owner's files. The command form never
  touches a media message, because it only edits its own text command.
* Loop prevention: the auto-formatter listens to `NewMessage` only (`MessageEdited`
  is never handled), skips anything starting with `!`, and keeps a 120s LRU of
  `(chat_id, message_id)` it has already edited (`MessageNotModifiedError` and
  `MessageEditTimeExpiredError` are treated as no-ops).
* Owner-only: `out=True` plus `sender_id == client.get_me().id` (`my_id`).

---

## 3. Four new commands

| Command | What it does | Free API | Failure behaviour | Why it fits a self-bot |
|---|---|---|---|---|
| `!weather <city>` | Current conditions + 3-day outlook | **Open-Meteo** (keyless, no signup) → **wttr.in** fallback | Both providers failing gives one readable line; 10s/12s timeouts; geocode cached 24h, forecast 10min | Used in groups constantly, saves the owner opening a weather site, and costs one request per 10 minutes per city |
| `!wiki [lang] <term>` | Wikipedia summary, any language | **Wikipedia REST** (keyless) → **DuckDuckGo Instant Answer** fallback | Empty article and outage are distinguished from "not found"; 1h cache | Fast fact-checking mid-conversation; the language prefix makes it useful in Persian/English groups |
| `!trivia [category]` | Multiple-choice question, answer revealed after 20s by editing the message | **Open Trivia DB** (keyless) | Local 5s gate before any call, `response_code` 1/5 mapped to clear messages, session token auto-refreshed | Group-useful without being spammy: one message per invocation, no bot API required, no key |
| `!remind <duration> <text>` | One-shot reminder to the current chat; `list` / `del <id>` | **none** — pure local scheduling | No network at all; a full store reports "too many pending"; deliver failures are logged and the entry dropped | The clearest time-saver: absolute due timestamps in `mode/reminders.json` mean a reminder set before Replit sleeps still fires after it wakes |

`!remind` is the only one of the four with no external dependency, which is why
it is also the one that cannot be rate limited.

---

## 4. API audit and rework

Everything now goes through `Com/api.py`: one shared `aiohttp` session, TTL
cache, `APIError`/`RateLimited` with `Retry-After`, one retry on 5xx/timeout,
**no** retry on 429, and `first_success()` for fallback chains.

| Feature | Old provider | New provider | Free-tier limits | Key required | Fallback |
|---|---|---|---|---|---|
| Crypto price | CoinPaprika only, no cache | CoinGecko `simple/price` | ~5–15 req/min/IP | no | CoinPaprika |
| IP geolocation | `ip-api.com` (HTTP), no timeout policy | `ip-api.com` | 45 req/min | no | `ipwho.is` (HTTPS) |
| Image generation | Hugging Face `api-inference` + `HF_API_TOKEN`, model `runwayml/stable-diffusion-v1-5` | **Pollinations** `image.pollinations.ai/prompt/…` | rate-limited per IP, 768×768, best effort | **no** | none (single keyless provider) |
| Summarization (LLM) | Gemini `v1beta2/text-bison-001` with `Bearer` auth — **retired endpoint, never worked** | Gemini `v1beta/models/{model}:generateContent?key=` | Flash-Lite 10 RPM / 500 RPD, Flash 5 RPM / 20 RPD | yes (`GEMINI_API_KEY`) | model chain, then the existing local extractive summarizer |
| Translation | `googletrans` (broken: `translate()` is async, result read as sync) | Google `translate_a/single` (`client=gtx`) | undocumented, per-IP | no | MyMemory (`autodetect|dest`) |
| TTS | gTTS (blocking call on the event loop) | gTTS, now in a worker thread with a 45s timeout | free, throttled | no | none (reports the throttle) |
| OCR | OCR.space demo key, 502-only retries | OCR.space, `OCR_SPACE_API_KEY` optional (defaults to the documented free key) | 25k/month free tier | optional | local Tesseract first |
| QR decode | qrserver, fresh session per call | qrserver via `Com.api` | light, keyless | no | none |
| URL shortener | TinyURL (+ Bitly token path) | TinyURL | keyless | no | is.gd; Bitly only if `BITLY_TOKEN` is set |
| Subdomain enum | crt.sh, silent `except` | crt.sh via `Com.api` | keyless, often 502 under load | no | none — outage now reported |
| Reverse image | catbox.moe upload + public search links | unchanged (keyless) | best effort | no | unchanged |

Caching TTLs: crypto 60s, weather forecast 10min / geocode 24h, wiki 1h,
geolocation 24h, DuckDuckGo 30min. No endpoint is called per message; all calls
are command-triggered.

---

## 5. Dependency changelog

| Package | Old state | New state | Reason | Free-tier impact | Risk |
|---|---|---|---|---|---|
| `googletrans` | `==4.0.2` | **removed** | `Translator.translate()` is a coroutine in 4.x; the old `to_thread()` wrapper could never return a result, so `!translate` always failed. Its endpoint is now called directly. | Drops ~2 transitive packages; less install time on Rebuild | The Google endpoint is undocumented and can throttle; MyMemory fallback added |
| `httpx` | `==0.28.1` | **removed** | Only existed because `googletrans` required it | Smaller install | None; nothing imports it (verified after uninstall) |
| `aiohttp` | `==3.10.11` | unchanged, now the single shared HTTP client | Already present; no new HTTP library added | One session instead of one per call | None |
| everything else | unchanged pins | unchanged | — | — | — |

No packages were added.

---

## 6. Changes applied

### Ban family
* `Com/ban.py` (new) — router, subcommands, duration parsing, ledger, error map.
  Could break: nothing else imports it; it writes only `mode/bans.json`.

### Chat family
* `Com/chat.py` (new) — styles, entity builder, auto-mode, loop guards.
  Could break: auto-mode holds a process-wide dict of edited ids (bounded to 512).

### Creative commands
* `Com/weather.py`, `Com/wiki.py`, `Com/trivia.py`, `Com/remind.py` (new).
  Could break: `Com/remind.py` starts one background task; it is named
  `selftg-reminders` and swallows its own tick errors.

### API rework
* `Com/api.py` (new) — shared session, cache, errors, fallback helper.
* `Com/crypto.py` — CoinGecko primary, CoinPaprika fallback, 60s cache.
* `Com/ip.py` — geolocation via the shared layer, ipwho.is fallback, 24h cache;
  `aiohttp`/`HAS_AIOHTTP` import removed.
* `Com/draw.py` — Pollinations instead of Hugging Face; token no longer needed.
* `Com/summarize.py` — real Gemini endpoint, model chain, no more `Bearer` header.
* `Com/translate.py` — direct keyless endpoints, MyMemory fallback.
* `Com/shorturl.py` — TinyURL → is.gd, atomic log, optional Bitly only.
* `Com/ocr.py` — shared layer, quota errors distinguished from bad images.
* `Com/decodeqr.py` — shared layer, explicit 429 message.
* `Com/tts.py` — gTTS moved off the event loop with a timeout.
* `Com/subenum.py` — crt.sh outage is reported instead of looking like an empty result.
* `requirements.txt` — `googletrans`, `httpx` removed with an inline explanation.

### Incidental
* `Com/alias.py` — Persian aliases for `ban`, `chat`, `weather`, `wiki`,
  `remind`, `trivia`.
* `V2_UPGRADE.md` — this document.

`!chat` did not exist before this change, so nothing was renamed or shadowed.

---

## 7. Validation results

Environment: this cloud VM, a `/tmp/run` venv (Python **3.12.3**) with
`requirements.txt` installed; the Replit interpreter is **3.10** per `.replit`.
Network probes therefore ran from this VM, **not** from Replit.

| Check | Result |
|---|---|
| `compileall` over `Com/` + `main.py` | pass |
| `compileall` with `SyntaxWarning` as error | pass |
| Import + `setup()` for every command module with a stub client | **71 modules, 162 handlers, 0 failures** (was 65/155) |
| Pure-function unit checks (durations, entities, cache TTL, trivia render, formatters) | **31/31 pass** |
| Live provider probes from this VM | Open-Meteo ✔, wttr.in ✔, Wikipedia ✔, DuckDuckGo ✔, CoinGecko ✔, CoinPaprika ✔, ip-api ✔, ipwho.is ✔, OpenTDB ✔, TinyURL ✔, is.gd ✔, Google translate ✔, MyMemory ✔, Pollinations (returned JPEG) ✔ |
| `!translate` after removing `googletrans`/`httpx` from the venv | `hello world → سلام دنیا`; `good morning → صبح بخیر` |
| Gemini path without `GEMINI_API_KEY` | returns `None` → local summarizer, no exception |
| Lingva as a fallback | **rejected** — `lingva.ml` answered 5xx; MyMemory used instead |

### What was *not* validated

* **The ban family was never executed against a real Telegram chat.** No account
  or test group is reachable from this environment. It is syntax-checked,
  import-tested and unit-tested (duration parsing, ledger pruning), and the
  Telethon call shapes were read from the installed library source — but a
  real `edit_permissions` round trip, admin-rights errors and the basic-group
  refusal are **unverified**.
* Same for `!chat` editing, auto-format, `!remind` delivery and every new
  command's Telegram-side output. Only the provider calls and pure logic ran here.
* The venv differed from the pins in one place: it had `googletrans 3.4.0`
  installed rather than 4.0.2. That package was removed entirely, so it no longer
  matters.
* Pollinations' keyless endpoint is documented as best-effort and returned a
  watermark-free JPEG in this test; whether it still does so from Replit's egress
  IP is unverified.

---

## 8. Free-tier fitness

* **Handlers/memory:** +7 handlers and +6 modules. No new process, no new
  dependency, one shared `aiohttp` session capped at 256 cache entries (values
  are small JSON blobs; a full cache is well under a megabyte).
* **CPU:** every new command is one request per invocation with a timeout.
  `!remind`'s scheduler wakes every 15s and does one small file read.
  `!ban`'s ledger is read/written only on ban actions.
* **Sleep:** tempbans, auto-format settings and reminders all live on disk or in
  Telegram itself, so a sleeping Repl does not lose them. A reminder whose time
  passed while the Repl slept fires on the next tick after wake.
* **Rate limits:** caches (60s crypto, 10min weather, 1h wiki, 24h geo) plus the
  OpenTDB 5s gate keep the bot far below every documented free quota.
* **Most fragile dependencies, in order:**
  1. **Pollinations** (`!draw`) — single keyless provider, no fallback, can
     refuse prompts or rate limit; also the slowest call (up to 60s).
  2. **crt.sh** (`!subenum`) — frequently 5xx under load; now reported, not fixed.
  3. **OCR.space** (`!ocr`) — the shared `helloworld` key is throttled globally;
     set `OCR_SPACE_API_KEY` for a private free key, or rely on local Tesseract.
  4. **Google translate endpoint** (`!translate`) — undocumented and per-IP
     throttled; MyMemory is the safety net but has a ~5k chars/day anonymous cap.
  5. **ip-api.com** (`!ip geo`) — free tier is HTTP-only, so the lookup is not
     encrypted (only an IP and public metadata travel).
  6. **Gemini free tier** (`!summarize`) — 20–500 requests/day depending on
     model; the local summarizer is the intended normal path when it refuses.
  Open-Meteo, Wikipedia, CoinGecko and OpenTDB were the most reliable in testing.

---

## 9. Final verdict

**Test manually before trusting `!ban` in a real group**, in this order:

1. In a **supergroup** where the account is admin: `!ban @someone test` →
   confirm they are removed and `!ban info @someone` reports "banned".
2. `!ban unban @someone` → confirm they can speak again (if still a member).
3. `!ban temp @someone 2m test` → confirm Telegram itself lifts it after 2
   minutes with the bot untouched.
4. Restart the Repl during a tempban → the ban must still be active (Telegram
   enforces it) and `!ban list` must still show it.
5. In a **basic group**: `!ban @someone` must refuse with the supergroup
   explanation, not silently fail or ban everyone.
6. From a non-admin account context (if you ever run one): `!ban` must not
   execute — handlers are `from_users=me` only.
7. `!ban kick @someone` → they leave, can rejoin via invite.

Then `!chat bold hello`, `!chat bold on` + normal messages, `!chat off`;
`!remind 1m test` followed by a Repl restart before it fires; `!weather`,
`!wiki`, `!trivia`, `!crypto btc`, `!translate fa hello`, `!draw a red cube`.

**Remaining risks:** the ban family is unexercised against real Telegram admin
rights; `!draw` depends on one best-effort provider; the Gemini free quota is
small enough that the local summarizer will often be what you see; and Replit's
free tier still sleeps the Repl, so the bot is offline until woken — no code
change can alter that.
