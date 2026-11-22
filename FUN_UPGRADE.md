# Fun and game surface — upgrade report

Date: 2026-11-22. Target: Telethon 1.44.0 self-bot on Replit free tier.
Scope: the fun/game commands, the sources they call, and the one state file the
new guessing game needs.

Every free source below was called from this workspace on the date above. The
Telegram rolls themselves could not be sent (no account in this workspace), so
the dice commands were exercised with a stub client and are listed as such in §9.

---

## 1. Current-state inventory

| Command | Module | What it actually did | Source | Verdict |
|---|---|---|---|---|
| `!trivia` | `Com/trivia.py` | Multiple-choice question, reveal after 20 s, session token | Open Trivia DB | Working, but category table was wrong and the shuffle was fake |
| `!dice`, `!dart`, `!football`, `!basketball`, `!slot` | `Com/casino.py` | Native `InputMediaDice`, but **forced** outcomes by sending and deleting up to 100 dice | Telegram | ToS/send-volume problem; rewritten |
| `!draw` | `Com/draw.py` | Text-to-image | Pollinations Classic API | Working and keyless; unchanged |
| `!poll` | `Com/poll.py` | Native polls/quizzes/results | Telegram | Already polished; not a game command, unchanged |
| `!love` | `Com/love.py` | Font-styled message art | local | Fun but not a game; unchanged |
| `!countdown` | `Com/countdown.py` | Live countdown message | local | Utility, unchanged |
| `!inline` | `Com/inline.py` | Message with inline buttons via the companion bot | Telegram bot API | Utility, unchanged |
| `!reaction`, `!mock`, `!chat`, `!aiml` | | Reactions, fake data, chatbot | local / APIs | Not game commands; unchanged |

There was no `!meme`, no local game, and no stateful chat game.

## 2. Source verification table

| Source / mechanism | Free | Keyless | Limits seen / terms | Live check | Decision |
|---|---|---|---|---|---|
| Open Trivia DB | yes | yes | ~1 request / 5 s per IP; session tokens free; 24 categories | 200, 304 B; token 200 | **Primary trivia** |
| The Trivia API (`the-trivia-api.com`) | yes | yes | `limit` 1 answered; category/difficulty filters; no key | 200, 550 B; categories 200 | **Trivia fallback** |
| memegen.link | yes | yes | stateless URL generator; no account, no documented rate limit | templates 200 (90 KB); PNG 200 (500 KB) | **Meme generation** |
| meme-api.com | yes | yes | random Reddit meme | 200, 606 B | Discarded: result size/content vary per post; memegen is deterministic and template-based |
| Pollinations | yes | yes | shared queue; per-IP best effort | 200 JPEG (11 KB at 256 px) | Keep for `!draw` (unchanged) |
| FreeToGame | yes | yes | listings only | 200, 164 KB | Not used (see §4) |
| Cat fact / random.dog / useless facts / JokeAPI / icanhazdadjoke | yes | yes | all answered | 200 each | Not used (see §4) |
| Telegram `InputMediaDice` | yes | n/a | six supported emoji; value decided server-side | types present in Telethon 1.44.0 | **Backbone of the dice commands** |

## 3. Upgrade decisions

* **`!casino.py` rewritten.** The old `force_dice()` sent a die, read its value
  and deleted it until the wanted value came up — up to 100 messages for
  `!dice 6`, and more for `!slot seven`. That is a detectable send pattern and
  it is gone. Every command now sends exactly one die and deletes the command
  message on success.
  * `!dice`, `!dart`, `!football`/`!soccer`, `!basketball`/`!basket`,
    `!bowl`/`!bowling`, `!slot`.
  * `!bowl`/`!bowling` are new names for the same server-side die; the rest
    already existed.
  * A value/symbol argument (`!dice 6`, `!slot seven`) now gets an explicit
    refusal explaining why, instead of a reroll loop. This is a deliberate
    removal and the largest behavioural change in this work.
  * The shared flood breaker (`Com/core/flood.py`) is now checked before a roll,
    and a FLOOD_WAIT is recorded so a burst pauses sending.
* **`!trivia.py` upgraded.**
  * Category table corrected against `api_category.php`: the old map pointed
    `video-games` at 32 (Cartoon & Animations); the real id is 15. Added anime,
    comics, gadgets, vehicles, mythology and cartoons.
  * `!trivia <category> <difficulty>` — easy/medium/hard, in either order.
  * Real `SystemRandom().shuffle()` for options. The old
    `sort(key=hash(...))` was biased, stable within one process and different
    after every restart.
  * The Trivia API is a fallback when OpenTDB is rate limited (its code 5), its
    token is exhausted twice, or it is unreachable. The fallback ignores a
    category it does not have and the card says so.
  * The 5 s gate stays global because OpenTDB limits per client IP.
* **`!draw.py`** verified against Pollinations (200, JPEG) and left unchanged;
  it already has rate-limit, refusal, non-image and send-failure paths.
* **No merges or removals of command names.** `!dice`/`!slot` still answer, just
  truthfully about what Telegram will roll.

## 4. New commands

| Command | Why it earned its place | Source | Failure path |
|---|---|---|---|
| `!meme [template] <top> \| <bottom>` | The one fun thing the project lacked: a captioned image from a known template, rendered locally from a URL. Distinct from `!draw` (AI prompt → image) | memegen.link | no text, service down/404, non-image body, oversized image, send failure |
| `!8ball <question>` | Zero-cost chat game; no state, no API, instant | local | missing question |
| `!coinflip [heads\|tails]` | Same; also usable as a decision tool | local, `SystemRandom` | invalid call |
| `!rps <rock\|paper\|scissors>` | Same; the opponent is local logic | local | invalid choice |
| `!roll <notation>` | Dice notation for tabletop use (`2d6+3`); complements the native dice commands rather than duplicating them (Telegram dice cannot express 3d8) | local | bad notation, count/sides/modifier caps |
| `!guess` | The one stateful game: a per-chat 1–100 round with 8 tries | local, `mode/games.json` | no game, out-of-range, non-numeric, state-write failure, out of tries |

Deliberately **not** built:

* `!freegame` / `!randomgame` — a store listing is a web search result, not a
  chat game, and its API returns 160 KB for data the owner will not read in
  Telegram.
* Cat facts, dog pictures, jokes, advice — each is one novelty endpoint with the
  same answer shape ("here is a sentence"). They would add four API dependencies
  without a game. `!meme` and `!draw` already cover "send something amusing".
* Truth-or-dare / would-you-rather — content moderation burden on a self-bot
  whose owner is the only sender; no safe local deck worth maintaining.
* Emoji roulette — Telegram has no server-side emoji die beyond the six
  supported ones, and "bot posts a random emoji" is not a game.
* Scores, leaderboards, cross-chat economy — the project is owner-only with no
  shared-admin policy; persisted scores would be a single-user vanity file.
* Any betting/wager game — encourages a gambling-shaped feature with no economy
  and no value.

## 5. Shared HTTP layer decision

No new HTTP helper was needed. `Com/core/api.py` already provides the shared
session, TTL cache, timeout, `RateLimited` on 429, bounded retry and provider
fallback; `!meme` and the trivia upgrade use it directly.

* `!meme` fetches a bounded-by-check image body (rejects > 5 MB, validates the
  PNG/JPEG/GIF/WebP magic before sending).
* `!trivia` uses `fetch_json` for both providers and keeps its own 5 s gate,
  because that gate is the provider's per-IP rule rather than an HTTP detail.
* Native dice and the local games make no HTTP calls at all; they share the
  output and error style through `Com/core/reply.say` and `Com/core/brand.py`.
* `!draw` keeps using the same layer.

## 6. Game-state design

Only `!guess` has state.

* **Where:** `mode/games.json`, shaped
  `{"chats": {"<chat_id>": {"secret", "attempts", "low", "high", "started"}}}`.
* **Survival:** written with `Com/core/storage.save_json()` (temp file + fsync +
  atomic replace), so a restart or a killed Repl leaves either the old or the new
  round, never half a file. A round resumes after a restart.
* **Expiry:** entries older than 24 h are pruned on the next guess command, so an
  abandoned round does not accumulate forever.
* **Corruption:** a malformed entry is dropped and the command starts a fresh
  round rather than raising. A secret outside 1–100 is treated as malformed.
* **Store unavailable:** if `save_json` raises (full disk, permissions), the
  round still plays from memory and the start/hint message says
  "State could not be saved; this round ends on restart." It does not fail the
  game and does not fail silently.
* **Scope:** per chat, one round per chat; `!guess new` replaces it, `!guess
  stop` reveals and removes it.
* The file is now in `.gitignore` with the trivia session token, both runtime
  state (the token file was already being written and was not ignored).

`!trivia` keeps its OpenTDB session token in `mode/trivia_token.json` — an
anti-repetition token, not a game score; it is re-requested automatically when
the provider invalidates it.

## 7. Failure matrix

| Command | Scenario | User-facing answer |
|---|---|---|
| `!trivia` | unknown filter | `❌ Unknown filter. unknown filter 'x'. Categories: …; difficulty: easy, medium, hard` |
| | local 5 s gate | `⏳ Trivia is cooling down — try again in Ns.` |
| | both sources down | `❌ Could not fetch a question. OpenTDB: …; Trivia API: … . Try again shortly.` (provider text is escaped) |
| | category missing on fallback | the question card ends with `source: The Trivia API · <category> is not a category on the fallback` |
| | reveal edit fails | logged only; the question and answer stay readable in the message |
| `!dice` / `!slot` | value/symbol argument | `❌ Choosing a value is not possible` + the send-volume explanation and `!dice` (or `!slot`) |
| `!dice` etc. | flood breaker open | `⏳ Sending is paused · Ns left after repeated flood waits.` (no roll sent) |
| | Telegram FLOOD_WAIT | `⏳ Telegram rate limit · wait Ns.` (+ pause line when the breaker opens) |
| | cannot write | `❌ The account cannot post in this chat.` |
| | media forbidden | `❌ Media is not allowed in this chat.` |
| | other RPC failure | `❌ Telegram refused the roll (<ErrorName>).` |
| | unexpected error | `❌ <ErrorName> · <message>` |
| `!meme` | no text / template without text | `❌ No caption text.` + example |
| | memegen 404/unreachable | `❌ Meme service unavailable. memegen · request rejected (404) · HTTP 404` |
| | non-image body | `❌ The meme service returned something that is not an image.` + escaped snippet |
| | > 5 MB | `❌ The generated image was too large to send.` |
| | send failed | `❌ Generated the meme but could not send it. <reason>` |
| `!8ball` | no question | usage line |
| `!coinflip` | invalid call | `❌ Call it heads or tails.` |
| `!rps` | invalid choice | `❌ Pick rock, paper or scissors.` |
| `!roll` | missing / bad notation | usage line, or `❌ Bad dice notation. 1–20 dice per roll` / `a die needs 2–1000 sides` / `modifier must be within ±1000` |
| `!guess` | no round, numeric guess | `❌ No game running. Start one with !guess.` |
| | out of range | `❌ Pick a number between 1 and 100.` |
| | non-numeric | `❌ Guess with a number: !guess 42, or stop with !guess stop.` |
| | out of tries | `❌ Out of tries.` + the hint and the number |
| | stop with no round | `❌ No guessing game is running here.` |
| | state store down | the round continues; message ends with `State could not be saved; this round ends on restart.` |

## 8. Changes applied

**Upgrades**

| File | Change | Why | Could break |
|---|---|---|---|
| `Com/casino.py` | removed `force_dice` reroll loop; one native send per command; added `!bowl`/`!bowling`, `!basket`, `!soccer` aliases; flood breaker + Telegram error handling | 100 sends per roll is a ToS and send-volume hazard; the six emoji are the only native dice | `!dice 6` and `!slot seven` now refuse instead of forcing; any workflow that relied on a chosen value is gone by design |
| `Com/trivia.py` | corrected category ids, added difficulty and fallback, real shuffle, source footer | wrong category mapping, biased "shuffle", single point of failure | a category name that was silently wrong before (`video-games`) now returns actual video-game questions |
| `.gitignore` | ignore `mode/trivia_token.json`, `mode/games.json` | runtime state, one of them newly written by `!guess`; the token was already being written unignored | nothing |

**New commands**

| File | Change | Why | Could break |
|---|---|---|---|
| `Com/meme.py` | `!meme`, `!meme list` | captioned memes from a keyless generator | nothing |
| `Com/games.py` | `!8ball`, `!coinflip`, `!rps`, `!roll`, `!guess` | local games with no API | nothing |

**Incidental**

* `!draw` verified against Pollinations and left as is.
* No command names were removed; all are still owner-only (`from_users=my_id`).

## 9. Validation

Run in this workspace on 2026-11-22 with a stub Telegram client (handlers invoked
directly; no account, no message left the process) plus live HTTP:

* `tools/smoke.py` — **passes**: 113 files compile, branding checks pass,
  78 modules load, 168 handlers register. Optional dependencies still skipped as
  before.
* Trivia live: OpenTDB returned `video-games` → "Entertainment: Video Games",
  `science` + `hard` → hard Science & Nature, `anime` → Anime & Manga; The Trivia
  API returned a Film & TV hard question. Option counts were 4 in each.
* `!trivia bogus` (filter error) and the 5 s cooldown path.
* Meme live: `!meme list`, a captioned `drake` PNG (501,281 B sent), a random
  template (`success`, 141,898 B), and the "template needs text" path.
* Casino with the stub client: `!dice`, `!dart`, `!soccer`, `!bowl`, `!slot`
  each produced exactly one `InputMediaDice` send and deleted the command;
  `!dice 6` and `!slot seven` refused; a forced-open flood breaker refused the
  send (`Sending is paused`).
* Games: `!8ball` with and without a question, `!coinflip` valid/invalid,
  `!rps` win and invalid, `!roll 2d6+3`, `!roll d20`, `!roll 99d6`, `!roll`;
  `!guess` start / play / status / out-of-range / non-numeric / stop /
  no-round, the win path with a forced secret (state cleared afterwards), and a
  simulated `save_json` failure (the restart note appeared).
* Revealed trivia card rendered with the correct answer marker.
* Meme non-image path exercised through an invalid template (memegen 404).

Not tested, and not claimed:

* anything sent to a real Telegram chat, including whether the dice animations
  land and the command message is removed in the chat;
* the 20 s trivia reveal edit on a real message (only the rendered text and the
  edit call shape were checked);
* live OpenTDB 429 / token-exhaustion handling (the local gate was tested; the
  provider did not throttle during the run);
* memegen 429 or downtime, and Pollinations through `!draw` this turn (the
  endpoint was checked with curl earlier in the session);
* the companion bot (`Com/bot/`) — none of these commands go through it.

## 10. Free-tier impact

| Command | Upstream cost | Cache | Exhaustion behaviour |
|---|---|---|---|
| `!trivia` | 1 question call (+1 token when missing) | none for questions; token persisted | local gate refuses for the remaining seconds; then the fallback provider answers; if both fail, the error names both |
| `!meme` | 1 image fetch, ~140–500 KB | none (each caption is unique) | service error card; no retry loop |
| `!draw` | 1 image fetch at 768² | none | existing rate-limit/refusal paths |
| Native dice | 1 Telegram message | n/a | flood breaker pauses sending; nothing retries |
| `!8ball`, `!coinflip`, `!rps`, `!roll` | none | n/a | no quota |
| `!guess` | none (one JSON write per guess) | file is read per command, tiny | game continues and says state is not being saved |

Memory: no response body larger than 5 MB is accepted by `!meme`; trivia
responses are ~1 KB; the guess file holds one small record per chat.

## 11. Dependency changelog

**None.** No package was added, removed or upgraded.

* Native dice use `telethon.tl.types.InputMediaDice`, already present in the
  pinned Telethon 1.44.0.
* Meme images and trivia use the existing `aiohttp` through `Com/core/api.py`.
* Randomness is `random.SystemRandom` from the standard library.
* State uses the existing `Com/core/storage.py`.

## 12. Remaining risks

* **Open Trivia DB** is the most fragile piece: ~1 request per 5 s per IP, and
  its session tokens can exhaust a category. The fallback covers an outage but
  has fewer categories, so a niche category becomes a random question (the card
  says so).
* **The Trivia API** has its own category names and question mix; some OpenTDB
  categories map to a broader fallback category (`animals` → `science`).
* **memegen.link** is a single free service with no SLA. If it changes URL
  escaping or goes down, `!meme` fails cleanly but stops being fun. The image is
  fetched once per command, so a slow day costs time, not quota.
* **Telegram dice** are server-side and can themselves hit FLOOD_WAIT if spammed.
  The command checks the breaker first and records flood waits, but the owner
  should still not loop `!dice` in a busy chat.
* **`!guess` state** is per chat and survives restarts, but it is one JSON file
  shared with nothing else; deleting `mode/games.json` simply ends live rounds.

Manual checks worth doing on the Repl: one `!trivia science hard`, one
`!meme drake test | works`, each dice command once in a test chat, and a full
`!guess` round including a restart in the middle.
