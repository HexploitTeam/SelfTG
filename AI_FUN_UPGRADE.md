# AI-flavoured fun — report

Date: 2026-11-22. Target: Telethon 1.44.0 self-bot, Replit free tier.
Branch: `new`. The work is in the working tree, uncommitted.

The short version: twelve new commands, eleven of them local with no model and
no network, one (`!ask`) on two free provider tiers. While reading the repo I
found the existing `!aiml train` building its model from `client.iter_messages`
and two such models committed to git; that path is removed because it is the
exact thing the legal constraint forbids. `!summarize` no longer sends chat text
to Gemini either.

---

## 1. Command list

### Local — no network, no model, no quota

| Command | Module | Why it earned its place |
|---|---|---|
| `!fortune` | `Com/oracle.py` | Zero input, one line, instantly shareable; the classic reason people type at a fun bot |
| `!tarot [question]` | `Com/oracle.py` | Three cards from the 22 major arcana with upright/reversed readings; feels personal without pretending to know the future |
| `!predict <question>` | `Com/oracle.py` | Weighted verdict + confidence; gives the question back, so it reads as an answer to *that* question |
| `!mood <text>` | `Com/oracle.py` | Keyword lexicon with intensifiers and negation (`not bad` scores positive); labelled "for fun" in the output |
| `!roast [target]` | `Com/social.py` | Harmless, absurd roasts; works on a name or with no name |
| `!compliment [target]` | `Com/social.py` | The counterweight; the one people actually screenshot |
| `!wyr` | `Com/social.py` | Would-you-rather from a 25-pair local bank; starts a conversation rather than ending one |
| `!pirate`, `!shakespeare`, `!uwu`, `!leet` | `Com/style.py` | Four substitution tables; handing a message back in a hat is the cheapest illusion of understanding, and it is genuinely funny in a chat |
| `!aiml gen/say/para/next/corpus/status/config/set/train/reset` | `Com/aiml.py` | Existing command, rebuilt on an owner-supplied corpus and upgraded to an interpolated 1–3-gram sampler with continuation, paragraphs, next-word odds and saved settings; the only "it wrote that itself" moment in the set |

### API-backed — exactly one

| Command | Module | Why an API is justified |
|---|---|---|
| `!ask <question>` | `Com/ask.py` | The point is an answer to an arbitrary question. No table or template can do that, and the brief allows one open-ended command. Groq → Gemini fallback, persisted cooldown and daily cap |

Everything is owner-gated (`from_users=my_id`), because the self-bot only
receives its own messages; open-to-everyone commands would need the companion
bot and a different surface.

## 2. Not built

| Considered | Left out because |
|---|---|
| `!markov` as a new command | It would duplicate `!aiml generate`. The honest move was to fix the existing command's corpus, not add a second Markov command beside a non-compliant one |
| `!haiku` | A syllable-accurate generator needs a pronunciation dictionary (CMUdict and friends). Without one the "5-7-5" claim is false, and a curated bank of fixed poems is not generation. Shipping a lying counter is worse than not shipping the command |
| `!pickup` | Overlaps `!compliment`; the line between charming and harassing is exactly where a template bank gets uncomfortable |
| `!story` | `!ask` already covers "write me something"; a local mad-libs story was the weaker version of both `!ask` and `!aiml` |
| `!caesar`, `!reverse` | `!encode rot13`, `!encode atbash` and `!decodecheck` already exist; a second shift/reverse command would be surface without capability |
| Cerebras as a third provider | Its current free offer is described as trial credit with a card in at least one November 2026 source, which conflicts with "no card-required tiers". Two no-card providers satisfy the brief; adding a card-gated one would violate it |
| Sentiment API, "AI detector", image generation | Paid or card-gated, or duplicates `!draw` and `!meme` |
| A local neural model / tiny LLM | Explicitly out: CPU inference latency on this host would make the bot feel broken, and it would need hundreds of MB. The brief says not to, and the arithmetic agrees |
| Vector search, embeddings for "memory" | Would require either a model or storage full of chat text; both violate the no-Telegram-data rule or the memory budget |
| Training on the chat at all | Forbidden. See §3 |

## 3. Local generator design (the Markov chain)

**Corpus:** `data/corpus/` — one UTF-8 `.txt` file per source, all trained
together. It ships with `the-time-machine.txt`: *The Time Machine* (1895, public
domain), 179,005 bytes, 32,319 words. Fetched from the GITenberg mirror of
Project Gutenberg #35 because `gutenberg.org` returned 503; header, footer,
licence block and illustration markers stripped, normalised to UTF-8/Unix.
Provenance and replacement instructions are in `data/README.md`.

**Adding text:** drop another `.txt` file into `data/corpus/`. No command is
needed — the model cache key is (order, every source's name/mtime/size), so a
new, edited, removed or renamed file rebuilds on the next `!aiml gen/say/para/
next`. `!aiml train` forces the rebuild and reports per source; `!aiml corpus`
lists what is loaded. Up to 12 files are accepted (more is refused with the
count), the minimum is 300 words in total, and `data/README.md` recommends
keeping the folder near 1 MB because the model grows with it.

**Enforcement of the no-Telegram rule:**

* `Com/aiml.py` contains no `iter_messages`, no `get_messages`, no client
  reference in the training path — the only input is `open()` over the `.txt`
  files in `data/corpus/`.
* The command takes a seed phrase, never a chat or a user as a corpus selector.
* The two committed models trained from real chats
  (`ML/models/markov_-1003421813254.json`, `…860.json`, 2.6 MB and 1.0 MB) are
  deleted from the working tree. `ML/models/` is now ignored, and the directory
  is not read by any code.
* `data/README.md` states the rule where the next person will look.
* The help text, `!aiml status`, `!aiml corpus` and `!aiml train` all say the
  text comes from local files only; Telegram messages are never read.

**Engine:** `ML/smart_markov.py` keeps counts for every order from 1 to
`order` (default 3, range 1–4) and blends them at sampling time: the longest
matching state leads, shorter states refine the tail, and counts are weights
rather than a uniform pick. States are keyed in lowercase so `the time` finds
`the Time`; the words that come back keep the corpus's capitalisation. A
`temp` setting reshapes the weights (0.2–2.0; below 1 is safer, above 1 is
stranger). Prompt continuation matches the seed's longest known *suffix* and
retries shorter suffixes when a walk dead-ends instead of returning the prompt
alone. `!aiml next` merges punctuation variants and shows blended odds.

**Quality controls:** the corpus is split into sentence units; a walk stops at
the first sentence end once it has enough words, avoids repeating the previous
word, trims leading quotes, capitalises, appends a full stop when missing, and
caps a generated sentence at 1,000 characters (a paragraph is never cut). Settings (`order`, `temp`, `length`,
`sentences`) live in `mode/aiml.json`, are validated against ranges on write and
clamped on read; the model cache is keyed on (every source's name, mtime and
size, plus order) so a setting or file change rebuilds on the next command.
The cache check only `stat`s the sources: cached commands do not reread the
prose.

## 4. API-backed design (`!ask`)

| Item | Value |
|---|---|
| Provider 1 | Groq, `https://api.groq.com/openai/v1/chat/completions`, default model `openai/gpt-oss-120b` (free tier, no card; `llama-3.3-70b-versatile` was retired for free tiers in August 2026) |
| Provider 2 | Gemini, `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`, default `gemini-3.5-flash-lite` with header `x-goog-api-key` |
| Secrets | `GROQ_API_KEY`, `GEMINI_API_KEY`; optional `GROQ_MODEL`, `ASK_GEMINI_MODEL` to follow model churn without a code change |
| Missing key | Command answers with the exact secret names to add. Import logs one warning; nothing crashes, so one optional key cannot take the self-bot down |
| Cooldown | 8 s between questions, persisted in `mode/ask.json` |
| Daily cap | 30 questions per local day, counted before the request so a double-tap cannot spend twice |
| Cache | None. Identical questions should not get the identical cached answer; the cooldown is the spam control |
| Store failure | Refuses rather than spending unmetered quota, and says which file to check |
| Prompt | One system instruction (short, plain text, no claimed chat memory) plus the typed question only |
| Not sent | Replies, chat history, usernames, prior answers |
| Rendering | `💬 Ask` card, question in a blockquote, answer escaped, provider + model in italics |

Endpoint check performed without keys: Groq answered **401** and Gemini
**403** — DNS/TLS/routing are correct and both reject an unauthenticated call.
No authenticated request was made, because no keys exist in this workspace.

Policy note: Groq's terms say API inputs are not used to train their models.
Google's free tier may use inputs to improve its products. That is why `!ask`
sends only the typed question, and why chat summarisation no longer goes to
Gemini.

## 5. Failure matrix

| Command | Situation | Exact answer |
|---|---|---|
| `!fortune` | none (no input, no I/O) | always answers; if delivery fails only the log records it |
| `!tarot` | no question | still draws three cards, no question line |
| `!predict` | no question | `❌ Ask something first.` + usage |
| `!mood` | no text / empty reply | `❌ Give me something to read.` + usage |
| `!mood` | no known words | `🌫 Unreadable` + "No familiar mood words in that one." |
| `!roast` / `!compliment` | no target | answers without a vocative |
| `!wyr` | none | always answers |
| `!pirate` etc. | no text / empty reply | `❌ Nothing to transform.` + usage |
| `!pirate` etc. | > 800 chars | transforms the first 800 + `Trimmed to the first 800 characters.` |
| `!pirate` etc. | empty result | `❌ That came out empty. Try a longer line.` |
| `!aiml` | bare command | help card + the settings in force |
| `!aiml gen/say/para/next/corpus/status/train` | corpus missing | `❌ No usable corpus.` + `no .txt files in data/corpus/` + where to add text |
| same | corpus too small | `N source(s) hold N words; at least 300 are needed` |
| same | more than 12 sources | `N sources in data/corpus/; at most 12 are trained. Remove some or merge them into one file.` |
| `!aiml gen` | walk produces nothing | `❌ Nothing came out.` + try without a prompt |
| `!aiml gen 400` / `!aiml para 9` | argument out of range | `❌ Length out of range.` / `❌ Too many sentences.` + the range and an example |
| `!aiml say` | no prompt | `❌ Give me a starting point.` + usage |
| `!aiml say zzzz` / `!aiml gen zzzz` | prompt has no continuation | `❌ That prompt goes nowhere.` + `The corpus never continues …` + try a shorter phrase |
| `!aiml next` | no phrase | `❌ Give me a phrase.` + usage |
| `!aiml next zzzz` | phrase unknown | `❌ No continuation for that.` + the phrase + try the last word or two |
| `!aiml set` | unknown/missing key or value | `❌ Unknown setting.` + `Keys · order, temp, length, sentences`, or `❌ Missing value.` |
| `!aiml set order x` / `order 9` | not a number / out of range | `❌ Not a number.` / `❌ Out of range.` + the accepted range |
| `!aiml set …` | `mode/aiml.json` unwritable | `❌ Could not save the setting.` + reason + `Nothing was changed.` |
| `!aiml set …` | success | `✅ Setting saved` + the note for that key + `Now · order/temp/length` |
| `!aiml train` | corpus unreadable/too small | `❌ Cannot train from the corpus.` + reason + path |
| `!aiml train` | success | `✅ Model rebuilt` + words, sentences, states, transitions, build time |
| `!aiml reset` | always | `✅ Model cache cleared.` + which file it rebuilds from; settings kept |
| `!ask` | no question | usage card explaining only typed text is sent |
| `!ask` | no keys | `❌ !ask has no provider configured.` + `GROQ_API_KEY` / `GEMINI_API_KEY`, free/no card |
| `!ask` | within 8 s | `⏳ Ask is cooling down · try again in Ns.` |
| `!ask` | 30 used today | `⏳ Daily limit reached.` + reset note |
| `!ask` | quota file unwritable | `❌ Could not record the request.` + check `mode/ask.json`; refuses to spend unmetered |
| `!ask` | all providers failed | `❌ No provider answered.` + blockquote of `provider · reason · HTTP n` + `The quota bucket was still charged` |
| `!ask` | provider blocks content | recorded as `blocked by provider (SAFETY)` and the next provider is tried |
| `!ask` | provider returns empty/shape error | `empty answer` / `unexpected response (...)` in the failure blockquote, next provider tried |

## 6. Changes applied

### Local commands

| File | Change | Why | Could break |
|---|---|---|---|
| `Com/oracle.py` | **new** — `!fortune`, `!tarot`, `!predict`, `!mood`; tables, weighted choices, keyword scoring with negation, HTML cards | Instant, free, no failure mode; the "clever" readout people ask for | nothing existing |
| `Com/social.py` | **new** — `!roast`, `!compliment`, `!wyr`; second-person templates, optional escaped target | Chat banter without an API or a moderation surface | nothing existing |
| `Com/style.py` | **new** — `!pirate`, `!shakespeare`, `!uwu`, `!leet`; word-boundary substitution, case preservation, 800-char cap, reply support | Four one-second tricks that make the bot feel responsive | nothing existing |

### API command

| File | Change | Why | Could break |
|---|---|---|---|
| `Com/ask.py` | **new** — two-provider chain, quota bucket, shape checks, block/safety handling, styled card | The one genuinely open-ended command | without keys it only explains; with keys, provider model ids can change — env overrides exist |

### Incidental / compliance

| File | Change | Why | Could break |
|---|---|---|---|
| `Com/aiml.py` | Rewritten: corpus-only training, no `iter_messages`, no per-chat model files, in-memory cache keyed on (mtime, size, order), then upgraded to ten subcommands (`gen`, `say`, `para`, `next`, `corpus`, `status`, `config`, `set`, `train`, `reset`) with validated settings in `mode/aiml.json` | The old command trained on Telegram messages, which the legal constraint forbids; the upgrade turns one thin generator into a usable local text tool | `!aiml train N` no longer means "last N messages"; `!aiml generate <seed>` still works and now continues via suffix matching. Old model JSONs are ignored, not loaded |
| `ML/smart_markov.py` | Rewritten: interpolated orders 1–3 (configurable 1–4), count-weighted temperature sampling, lowercase state keys, suffix continuation with fallback, `paragraph()`, `next_words()`, richer stats; `save`/`load` and the `ML/models` directory side effect removed | The old single-order uniform pick dead-ended constantly and ignored how often a continuation actually occurred; nothing can rebuild model files any more | Any hidden caller of `save`/`load` would break — none exists; `Com/aiml.py` was the only importer |
| `Com/summarize.py` | `!summarize chat` is local-only; a replied message is local-only; only typed text may use Gemini. Gemini key moved from the query string to `x-goog-api-key` | Chat content must not be ingested by a remote model; keys in URLs leak into logs | `!summarize chat` is extractive now, never abstractive. The help text says so |
| `ML/models/*.json` | Deleted (2 tracked files, 3.6 MB total) | They were Markov models trained on real chat messages | Anyone who relied on the old `!aiml` per-chat models loses them; they are regenerable from the corpus, and were the legal problem |
| `.gitignore` | `mode/ask.json`, `mode/aiml.json`, `ML/models/` | Runtime quota and sampler state; and to keep chat-derived models out of git | none |
| `data/corpus/the-time-machine.txt`, `data/README.md` | **new** — public-domain corpus folder + provenance/multi-file rules | Makes `!aiml` work out of the box without touching Telegram data, and lets the owner grow the training set one file at a time | the single `data/markov_corpus.txt` from the first pass moved into the folder, so there is exactly one input path |

No shared helper was added: `Com/core/api.py` already has `post_json`, timeouts,
429 detection and `first_success`; `Com/core/reply.say` and `brand` already give
the house style.

### Simplifications after review

A second read of the `!aiml` change removed paths that only existed because of
how it was built, without changing what any command does:

* `!aiml` and `!aiml help`/`?` were two handlers with identical bodies, and
  `gen <prompt>` duplicated `say <prompt>` line for line. Now one help handler
  and one continuation handler serve both; `gen 50` still sets the length and
  `say 50` still continues from "50", which a test pins down.
* The legacy `data/markov_corpus.txt` fallback is gone. The file is renamed into
  `data/corpus/` by this same change, so no checkout can reach the old path;
  the readiness error and `data/README.md` lost the parenthetical with it.
* The cache check now only `stat`s the sources. Previously every `gen`, `say`,
  `para`, `next` and `status` reread 180 KB and re-split every sentence just to
  decide the model was already warm; the text is read only on a real rebuild.
* `_totals()` stopped counting sentences nobody read, documents stopped carrying
  their path, and `get_stats()` stopped returning `order`/`start_states`; the
  engine's `transitions` property went with the one caller that used it.
* `!aiml para` ran the paragraph through the 1,000-character sentence cap, so an
  extreme `para 6` at `length 120` was cut mid-sentence. A paragraph is now
  whitespace-normalised and never truncated; single sentences are still capped.
* `_blend()` lowercased the whole sentence on every step of a walk; it now takes
  the last `order` words only. The arbitrary "stop blending after three orders"
  break went too, so `order 4` uses all four. Order-3 output is unchanged: the
  rebuilt model still reports 48,724 states / 85,602 transitions (5,532 / 18,573
  / 24,619 by order) and `!aiml next the time` still gives Traveller 47.8% /
  Machine 30.4%.

## 7. Validation

**Actually run** (all in this workspace, with a stub Telegram client — no
account, no message left the process):

* `tools/smoke.py` — **passes**: 117 files compile, branding checks pass,
  88 modules load, 199 handlers register (was 113 / 78 / 168 before this work,
  and 194 between the first pass and the `!aiml` upgrade; the two duplicate
  help handlers and the duplicated continuation path were merged).
* Handler runs for all new commands with realistic arguments:
  * oracle: fortune, tarot with a question, predict with/without a question,
    mood positive, mood negative, mood empty;
  * social: roast with a target, roast without, compliment, wyr;
  * style: all four with text, plus the empty-usage path;
  * aiml train pipeline: one source loads; adding a second file rebuilds the
    model on its own (33,000 words, 2 sources) and removing it rebuilds back to
    one; 13 sources are refused with the count; a 4-word source is refused with
    its word count; `!aiml corpus`, `!aiml train` and `!aiml status` cards were
    rendered and read;
  * aiml: help, gen (default/explicit length/out of range/with prompt/unknown
    prompt), generate alias, say (missing prompt, continuation, dead end), para
    (default/count/out of range), next (missing phrase, known, unknown), corpus,
    status, train, config, set (unknown key, missing value, non-number, out of
    range, valid order, valid temp), reset, and status again after the order
    change — 29 command runs, each delivering a signed HTML card;
  * ask: no-key refusal, empty-question card, successful answer through the
    handler, cooldown, daily cap, all-providers-fail.
* Corpus model built from the shipped file at the default order 3: 32,276
  trained words, 1,871 sentences, 48,724 states, 85,602 transitions,
  **0.16–0.21 s** to build; sample outputs inspected at temp 0.3/1.0/1.8 and at orders 1 and 4
  (e.g. *"The forest seemed full of my only experience of mountaineering…"*).
* Settings: written, read back, and confirmed that an out-of-range order, a
  non-numeric temp and an out-of-range length fall back to their defaults on
  read; `mode/aiml.json` is git-ignored and was removed after the test.
* Corpus failure paths: missing file and a 10-word file both produce the exact
  messages in §5.
* Quota: first reserve succeeds; immediate second raises cooldown 8 s; a state
  with `used=30` raises the daily cap; a simulated `save_json` failure raises
  the store error.
* Provider chain with monkeypatched HTTP: Groq 429 → Gemini answer; all-500 →
  `APIError` containing both failures; no keys → empty provider list.
* Memory: RSS delta for the order-3 corpus model **16 MB** (measured with
  `ru_maxrss`), on top of the interpreter; order 2 is roughly 8 MB.
* Endpoint reachability without credentials: Groq 401, Gemini 403.

**Not tested, and not claimed:**

* Any command delivered to a real Telegram chat. No account is connected here,
  so edit-in-place, HTML rendering and flood behaviour were not observed.
* A real authenticated Groq or Gemini answer. No keys exist in this workspace;
  both provider request/response shapes were implemented from their documented
  APIs and exercised only against the stub. Real model ids, real 429s and real
  safety blocks remain unverified.
* `!summarize` chat summarisation against a live chat (the local summariser
  itself was already covered by the existing smoke/import checks; its branch was
  reviewed, not executed end to end here).
* Long-run quota rollover at local midnight (date comparison is unit-shaped, not
  clock-advanced).
* CPU behaviour under concurrent commands; the generator is a single 40 ms
  build and a short walk, but it was not load-tested.

## 8. Memory and CPU statement

* Shipped corpus: 179 KB on disk, one source; the folder accepts up to 12
  sources, and the model grows with the text they hold.
* Model at the default order 3: 48,724 states / 85,602 transitions; measured
  **+16 MB RSS** when built, ~0.2 s, once per process, and only if `!aiml` is
  used. Order 2 is about half that; order 4 is larger and only built if asked
  for with `!aiml set order 4`.
* `!ask`: one HTTP request, max 300 output tokens, 30 s timeout, no model in
  process.
* Everything else: lookup tables of a few kilobytes.
* **No local neural model, no TensorFlow import in any command path, no
  embedding index, no training loop at request time.** The standalone
  `ML/aiml_model.py` and `ML/lstm_model.py` remain unused by `Com/`, as before;
  they are not imported by the new code.

## 9. Dependency changelog

**None.** No package added, removed or upgraded.

* Local commands use `random`, `re`, `logging` and the standard library.
* `!ask` uses the existing `aiohttp` through `Com/core/api.py`.
* `!aiml` reuses `ML/smart_markov.py`, now standard library only (`random`,
  `collections`) — its old `json`, `ast` and `os` imports went away with the
  model-file save/load path.
* No pronunciation dictionary was added, which is exactly why `!haiku` was left
  out rather than faked.

## 10. Final verdict

**Try first:** `!fortune`, `!tarot will this deploy survive`, `!roast ali`,
`!aiml say the time traveller`, `!aiml next the time` and `!aiml para`. Those
need no setup and show the tone. Then add
`GROQ_API_KEY` (console.groq.com/keys) and try `!ask why is the sky blue?`; add
`GEMINI_API_KEY` as the fallback.

**Still risky / best-effort:**

* **Model ids drift.** Groq retired its old free default in 2026; Gemini renames
  Flash models regularly. Both are env-overridable (`GROQ_MODEL`,
  `ASK_GEMINI_MODEL`) and a bad id falls through to the next provider, but the
  default may need updating after a provider change.
* **Gemini free-tier data policy.** Google may use free-tier inputs to improve
  products; Groq says it does not train on API inputs. The command sends only
  the typed question, but the choice of provider is a privacy decision the owner
  should make knowingly.
* **Markov quality is corpus quality.** The shipped novel gives Victorian
  sentences that are funny and sometimes nonsensical; a different corpus changes
  the voice entirely. Interpolation keeps walks alive far longer than the old
  bigram, but a 32k-word corpus still produces the occasional dead end, hence
  the suffix retry and the explicit "goes nowhere" message.
* **`!aiml` semantics changed.** The old "train on the last N messages" no
  longer exists by design. If the owner wanted that, the answer is that it is
  the one feature the ToS rule forbids.
* **Old models in git history.** Deleting the files stops them being used, but
  the two `ML/models/*.json` blobs still exist in earlier commits and may hold
  fragments of real messages. If the repository is or becomes public, rewrite
  that history (or re-create the repo) rather than only deleting the files in a
  new commit. I did not rewrite history without being asked.
* **`!summarize` is weaker for chat.** `!summarize chat` is now extractive only.
  That is the cost of keeping platform text out of a remote model.
