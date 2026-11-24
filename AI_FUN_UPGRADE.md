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
| `!aiml generate/train/status/reset` | `Com/aiml.py` | Existing command, rebuilt on an owner-supplied corpus; the only "it wrote that itself" moment in the set |

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

**Corpus:** `data/markov_corpus.txt` — *The Time Machine* (1895, public domain),
179,005 bytes, 32,319 words. Fetched from the GITenberg mirror of Project
Gutenberg #35 because `gutenberg.org` returned 503; header, footer, licence block
and illustration markers stripped, normalised to UTF-8/Unix. Provenance and
replacement instructions are in `data/README.md`.

**Replacement:** drop any UTF-8 prose into that path and run `!aiml train` (or
just `!aiml generate`; the model rebuilds when the file's mtime changes). Below
300 words the command refuses and says the word count; 100–500 KB is the
recommended range.

**Enforcement of the no-Telegram rule:**

* `Com/aiml.py` contains no `iter_messages`, no `get_messages`, no client
  reference in the training path — the only input is `open(CORPUS_FILE)`.
* The command takes a seed phrase, never a chat or a user as a corpus selector.
* The two committed models trained from real chats
  (`ML/models/markov_-1003421813254.json`, `…860.json`, 2.6 MB and 1.0 MB) are
  deleted from the working tree. `ML/models/` is now ignored, and the directory
  is not read by any code.
* `data/README.md` states the rule where the next person will look.
* The help text and `!aiml status` say "the local file only; Telegram messages
  are never read".

**Quality controls:** the corpus is split into sentence units, trained as a
bigram chain (order 2). Generation takes the longest of up to three walks (a
bigram can dead-end after two words), stops at the first sentence end after six
words, trims leading quotes, capitalises, and appends a full stop if missing.

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
| `!aiml` | bare command | help card |
| `!aiml generate` | corpus missing | `❌ No usable corpus.` + `corpus not found at data/markov_corpus.txt` + where to add text |
| `!aiml generate` | corpus too small | `corpus has N words; at least 300 are needed` |
| `!aiml generate` | walk produces nothing | `❌ Nothing came out.` + try without a seed |
| `!aiml train` | corpus unreadable/too small | `❌ Cannot train from the corpus.` + reason + path |
| `!aiml train 500` | numeric argument | works, plus `The message count in the old command is ignored: training reads the corpus file, never chat history.` |
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
| `Com/aiml.py` | Rewritten: corpus-only training, no `iter_messages`, no per-chat model files, in-memory bigram cache keyed on mtime, longest-of-three generation | The old command trained on Telegram messages, which the legal constraint forbids | `!aiml train N` no longer means "last N messages"; it rebuilds from the corpus and says so. Old model JSONs are ignored, not loaded |
| `Com/summarize.py` | `!summarize chat` is local-only; a replied message is local-only; only typed text may use Gemini. Gemini key moved from the query string to `x-goog-api-key` | Chat content must not be ingested by a remote model; keys in URLs leak into logs | `!summarize chat` is extractive now, never abstractive. The help text says so |
| `ML/models/*.json` | Deleted (2 tracked files, 3.6 MB total) | They were Markov models trained on real chat messages | Anyone who relied on the old `!aiml` per-chat models loses them; they are regenerable from the corpus, and were the legal problem |
| `.gitignore` | `mode/ask.json`, `ML/models/` | Runtime quota state; and to keep chat-derived models out of git | none |
| `data/markov_corpus.txt`, `data/README.md` | **new** — public-domain corpus + provenance/replacement rules | Makes `!aiml` work out of the box without touching Telegram data | none |

No shared helper was added: `Com/core/api.py` already has `post_json`, timeouts,
429 detection and `first_success`; `Com/core/reply.say` and `brand` already give
the house style.

## 7. Validation

**Actually run** (all in this workspace, with a stub Telegram client — no
account, no message left the process):

* `tools/smoke.py` — **passes**: 117 files compile, branding checks pass,
  82 modules load, 181 handlers register (was 113 / 78 / 168).
* Handler runs for all new commands with realistic arguments:
  * oracle: fortune, tarot with a question, predict with/without a question,
    mood positive, mood negative, mood empty;
  * social: roast with a target, roast without, compliment, wyr;
  * style: all four with text, plus the empty-usage path;
  * aiml: help, train, train with a numeric argument, generate with and without
    a seed, status, reset;
  * ask: no-key refusal, empty-question card, successful answer through the
    handler, cooldown, daily cap, all-providers-fail.
* Corpus model built from the shipped file: 32,276 trained words, 18,979
  states, 28,534 transitions, **0.039 s** to build; sample outputs inspected
  (e.g. *"The time I began to carry on a wonderful deepness of blue…"*).
* Corpus failure paths: missing file and a 10-word file both produce the exact
  messages in §5.
* Quota: first reserve succeeds; immediate second raises cooldown 8 s; a state
  with `used=30` raises the daily cap; a simulated `save_json` failure raises
  the store error.
* Provider chain with monkeypatched HTTP: Groq 429 → Gemini answer; all-500 →
  `APIError` containing both failures; no keys → empty provider list.
* Memory: RSS delta for the corpus model **8.4 MB** (measured with
  `ru_maxrss`), on top of the interpreter.
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

* Corpus file: 179 KB on disk.
* Model: 18,979 unique states / 28,534 transitions; measured **+8.4 MB RSS**
  when built, once per process, and only if `!aiml` is used.
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
* `!aiml` reuses the existing `ML/smart_markov.py` (itself only `json`, `re`,
  `random`, `collections`, `ast`).
* No pronunciation dictionary was added, which is exactly why `!haiku` was left
  out rather than faked.

## 10. Final verdict

**Try first:** `!fortune`, `!tarot will this deploy survive`, `!roast ali`, and
`!aiml generate the time`. Those need no setup and show the tone. Then add
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
  the voice entirely. Bigram chains dead-end, hence the three-walk retry.
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
