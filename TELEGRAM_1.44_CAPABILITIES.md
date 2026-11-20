# Telethon 1.44 capabilities: what was added and what was left out

Branch `new` (from `beta` 6489e09). Everything below was checked against the
installed `telethon==1.44.0` in a clean venv — signatures read with
`inspect.signature`, TL objects constructed and serialised — not against a
changelog.

The delta is real but smaller than the brief suggests: three items do not exist
in the form described, and two of the named ones are Bot API concepts that
never reach MTProto. Those are listed first, because a wrong "yes" is worse
than a "no".

---
#1. Delta verification
---

| # | Claim in the brief | Verdict on 1.44.0 |
|---|---|---|
| 1 | `send_as` on `send_message` / `send_file` | **Confirmed.** `send_as: hints.EntityLike = None` on both. |
| 2 | `effect` on `send_message` / `send_file` | **Different name.** The parameter is `message_effect_id: Optional[int]`; the TL field is `effect`. There is no `effect=` keyword. |
| 3 | `mime_type` on `send_file` | **Confirmed.** `mime_type: str = None`. |
| 4 | `tg-emoji` in HTML parse mode | **Confirmed.** `extensions/html.py` handles `<tg-emoji emoji-id="…">` and round-trips `MessageEntityCustomEmoji`. |
| 5 | Expandable blockquote | **Confirmed.** `MessageEntityBlockquote(offset, length, collapsed)`. |
| 6 | Styles on inline buttons | **Confirmed.** `KeyboardButtonStyle(bg_primary, bg_danger, bg_success, icon)`; every `KeyboardButton*` constructor takes `style`. |
| 7 | Persistent / placeholder inline buttons | **Half wrong.** `persistent` and `placeholder` exist, but only on `ReplyKeyboardMarkup` — reply keyboards, not inline. The bot sends `ReplyInlineMarkup` exclusively. |
| 8 | Button click chooses whether to open the browser | **Not present.** No `KeyboardButton*` type or parameter in this layer selects browser vs in-app; that is a client setting. |
| 9 | `FloodWaitPremium` | **Different name, and a trap.** The class is `FloodPremiumWaitError` (FLOOD_PREMIUM_WAIT). It subclasses `FloodError`, **not** `FloodWaitError`, so every existing `except FloodWaitError` misses it. |
| 10 | `drop_author` on `forward_messages` | **Confirmed.** `drop_author: bool = None`. |
| 11 | `drop_media_captions` on `forward_messages` | **Confirmed.** `drop_media_captions: bool = None`. |
| 12 | `reply_to_chat` / `reply_to_sender` on `Message` | **Confirmed.** Properties backed by `_reply_to_chat` / `_reply_to_sender`. |
| 13 | `MessageMediaGeoLive` auto-input conversion | **Confirmed.** `utils.py:506` converts it to `InputMediaGeoLive`. |
| 14 | `KeyboardButtonCopy` | **Confirmed**, and documented as *inline keyboards only* — which suits this bot. |
| 15 | Session path as `pathlib.Path` or `None` | **Not in 1.44.0.** `SQLiteSession(pathlib.Path(...))` raises `AttributeError: 'PosixPath' object has no attribute 'endswith'`. |
| 16 | CDN downloads re-enabled | **Confirmed** (`cdn_redirect` path in `client/downloads.py`). Automatic; no project code involved. |
| 17 | `range` accepted for ID parameters | **Not confirmed.** Nothing in `get_messages` handles `range` specially in this version. |
| 18 | Update-state fixes | **Confirmed and unobstructed.** `catch_up()` exists; the project contains no custom update loop, no `getDifference`, no `updates.*` handling that could bypass it. |
| 19 | `isal` optional compression | **Confirmed optional.** Imported only inside `tl/core/gzippacked.py` behind `try/except`. Not installed here and not required. |
| 20 | 1.44 hardening (salt timeout, lazy `_disconnected`) | **Confirmed in source** (lazy `_disconnected` future, `await self._auth_key_callback`). The salt-timeout claim could not be matched to a hunk in `mtprotosender.py`, so it is not claimed as measured. |

No v2 API patterns were found in the project: `TelegramClient`, `FloodWaitError.seconds`
and `await client.disconnect()` are used throughout and remain correct on 1.x.

---
#2. Adoption decisions
---

## Adopted — reliability (highest value in the delta)

**`FloodPremiumWaitError` handled everywhere.** Thirteen catch sites in eleven
modules only named `FloodWaitError`. Because the two are siblings, a premium
flood would have escaped every handler: no breaker, no visible pause, and in the
looping commands (`!f`, `!kill`, `!repeat`, `!setkill`) it would surface as a
generic error and stop the series without recording the flood. This is the one
item in the delta that was an actual bug, not a missing feature.

## Adopted — self-bot

* **`!fw`** (`Com/fw.py`, new) — forward the replied message with `drop_author`
  and/or `drop_media_captions`, to this chat or to a named one. Reposting
  without the "Forwarded from" header is the everyday use for an account that
  manages channels; the flags are server-side, so it is still one request.
* **`!sendas`** (`Com/sendas.py`, new) — one message posted as a channel the
  account administers. Stateless by design: it cannot be left switched on.
* **`!chat collapse`** (`Com/chat.py`) — the expandable blockquote as a style,
  combinable (`bold+collapse`).
* **`!git pull <branch>`** (`Com/git.py`) — the requested addition; `beta`
  stays the default, the branch name is validated against git's ref rules and
  never reaches a shell.

## Adopted — bot

* **Button styles** (`Com/bot/kit.py`, `ui.py`) — Confirm is green, Cancel and
  queue-discard are red, retry is blue.
* **Copy buttons** (`Com/bot/kit.py`, `ui.py`, `client.py`) — `KeyboardButtonCopy`
  on the moderation screen and `/id`, so a chat id is copied instead of retyped
  into `/add_enemy`.

## Adopted — incidental

* **`!info` on a cross-chat reply** (`Com/info.py`) — `get_reply_message()`
  returns `None` when the replied-to message lives in another chat, and the old
  code then dereferenced it. It now falls back to `event.reply_to_sender` and
  names the origin chat from `event.reply_to_chat`.

## Not adopted, and why

| Capability | Why not |
|---|---|
| Message effects (`message_effect_id`) | No effect catalogue is exposed by MTProto or Telethon; ids are client constants. A wrong id is not a clean error, and a self-bot that animates messages is the "spectacle" this brief rules out. Failing to fail clearly is the deciding reason. |
| `send_file(mime_type=…)` | Every send in the project is a temp file with a correct extension (`.mp3`, `.ogg`, `.zip`, `.txt`, image), and Telethon already infers the type from it. Adding a parameter that changes nothing is noise. |
| `tg-emoji` in HTML | The project formats with `MessageEntity*` lists, never `parse_mode`, precisely so text is never mangled. Custom emoji also need Premium to render as the custom glyph and a document id the account can use. Nothing to gain. |
| Persistent / placeholder buttons | Reply-keyboard concepts; this bot only ever sends `ReplyInlineMarkup`. Adopting them would mean a second keyboard model for no screen. |
| Browser-vs-app button choice | Does not exist in this layer (see #8). |
| Session as `pathlib.Path` / `None` | `SQLiteSession` still requires a string path in 1.44.0, and the project uses `StringSession` from a secret anyway. |
| CDN downloads | Already on by default; nothing to wire. Left as inherited behaviour, and no Replit-specific gain was measured. |
| `range` for ID parameters | Not confirmed in this version, and no command wants a numeric range of ids. |
| `isal` | A new dependency for gzip speed on a workload with no gzip-heavy path. Would need a `requirements.txt` entry and justify itself on 512 MB — it does not. |
| `MessageMediaGeoLive` input conversion | The project never sends locations. |
| `KeyboardButtonRequestPeer` / `WebView` / `UrlAuth` | No screen needs them; the bot's job is state, not account hand-off. |

---
#3. Changes applied
---

## Shared / reliability

`Com/core/flood.py` — added `FLOOD_ERRORS`, a tuple of `FloodWaitError` plus
`FloodPremiumWaitError` when the installed version has it:

```python
FLOOD_ERRORS = (errors.FloodWaitError,)
if hasattr(errors, "FloodPremiumWaitError"):
    FLOOD_ERRORS += (errors.FloodPremiumWaitError,)
```

`Com/{afk,poll,ban,chat,pin,reaction,cauto,setkill,kill,repeat,f}.py` — every
`except errors.FloodWaitError` became `except flood.FLOOD_ERRORS` (13 sites), and
`ban.py`'s `isinstance(exc, errors.FloodWaitError)` became
`isinstance(exc, flood.FLOOD_ERRORS)`. Four modules needed the `flood` import
added. Behaviour with a plain FLOOD_WAIT is byte-for-byte the same; the only
change is that the premium variant now lands in the same handler.

Could break: nothing that a plain FLOOD_WAIT exercised. `flood.FLOOD_ERRORS` is
a tuple, so it is only valid inside `except`/`isinstance` — it is not used as a
value anywhere else.

## Self-bot

`Com/chat.py` — `COLLAPSED_STYLES = {"collapse", "collapsed", "expandable", "fold"}`
and a branch in `build_entities` that emits `MessageEntityBlockquote(collapsed=True)`.
The style list in the error message now includes them, and `__HELP__` mentions
`collapse`. Could break: a style literally named `collapse` that someone meant
as text — but the first token is always a style, so that was already true.

`Com/fw.py` — new. Reply-based source, flags `-a` / `-c` / `-ac`, optional
target chat. Could break: a reply to a message that was deleted between the
event and the forward (mapped to `MessageIdInvalidError`), or a target the
account cannot write to (each mapped separately).

`Com/sendas.py` — new. `!sendas <channel> <text>`, or reply for the text.
Could break: a channel that is not an admin of the chat, which Telegram answers
with `SEND_AS_PEER_INVALID` and which is reported as exactly that.

`Com/git.py` — `pull(branch=BRANCH)` plus `BRANCH_RE = ^[A-Za-z0-9][A-Za-z0-9._/-]{0,80}$`,
validated both in the handler and inside `pull()`. `!git pull` alone still pulls
`beta`. Note: pulling another branch leaves the checkout detached at
`FETCH_HEAD`, and the next `!git pull` still works because it resets to the
newly fetched `FETCH_HEAD`.

## Bot

`Com/bot/kit.py` — `Copy` dataclass, `BUTTON_STYLES`, `btn(..., style=)`,
`copy_btn`, `url_btn(..., style=)`, and `markup` now accepts 2- or 3-tuples and
`Copy` data. Existing 2-tuple rows keep working untouched.

`Com/bot/ui.py` — styles on the confirm screen and the queue retry/discard row;
a copy-chat-id button on the moderation screen.

`Com/bot/client.py` — `/id` answers with a copy-chat-id button.

Could break: a client that does not render styles ignores them (no error), and
`keyboardButtonCopy` is documented as inline-only, which is what we send. The
one real risk is a server-side button rejection, which would fail the message —
that needs one live send to confirm.

## Incidental

`Com/info.py` — cross-chat reply handling described in #2.

---
#4. Failure behaviour
---

| Capability | Prerequisite missing | What the owner sees |
|---|---|---|
| `!sendas` | channel not admin / not permitted | `❌ Telegram will not accept @x as the sender here. The channel has to be an admin of this chat.` |
| `!sendas` | account cannot post | `❌ The account cannot post in this chat.` |
| `!sendas` | unknown username / id | `❌ Could not resolve @x: …` |
| `!sendas` | nothing to send | `❌ Nothing to send. Add text, or reply to a text message.` |
| `!fw` | no reply | `❌ Reply to the message you want to forward…` |
| `!fw` | no write right | `❌ The account cannot post in the target chat.` / `…needs an admin right…` |
| `!fw` | source gone | `❌ The message being forwarded no longer exists.` |
| `!fw` | target unresolvable | `❌ Could not resolve \`x\`: …` |
| `!chat collapse` | none — local entities | Works, or the edit handler reports the RPC error |
| `!git pull x` | branch missing / no network | `❌ \`git fetch origin x\` failed:` + git's own output |
| `!git pull --flag` | invalid refname | `❌ \`--flag\` is not a branch name.` |
| premium flood | — | Same path as a normal FLOOD_WAIT: "wait Ns", breaker may open, series stops |
| styled / copy buttons | old client | Rendered unstyled; no callback, no error |
| `!info` cross-chat reply | no sender in the event | `❌ That reply points at a message this account cannot read…` |

Nothing falls back silently to a different identity or a different chat: a
failure is always a message in the chat where the command was typed.

---
#5. No-regression check
---

* `tools/smoke.py`: **exit 0 — 78 modules, 174 handlers** (was 76 / 172; the two
  new command modules). Compile pass covers every file, so no module lost its
  import.
* Flood paths: every one of the 13 sites still catches `FloodWaitError`, since
  it is the first element of `FLOOD_ERRORS`. The breaker tests in `smoke.py`
  (`note_flood`, cooldown, `_gap`) still pass unchanged.
* `!chat`: `build_entities` was re-read after editing — the style branch order is
  plain → collapsed → known style → error, and `bold+collapse` returns both
  entities. Plain `quote` still produces `collapsed=None`, i.e. the old
  non-expandable blockquote.
* Bot keyboards: `markup` was checked with old 2-tuple rows (`pager_row`, every
  existing screen) and with 3-tuple rows; old rows serialise with `style=None`.
  `kit.cb` / `parse_cb` / the 64-byte budget are untouched.
* `!git pull` with no argument still resolves `BRANCH = "beta"`, and the guard
  runs before any git call is made.
* `!f`, `!inline`, `!poll`, `!reaction`, `!pin` go through the same edit as
  before; nothing in their handler patterns overlaps `^!fw\b` or
  `^!sendas\b` (`\b` keeps `!f` from matching `!fw`).

---
#6. Validation matrix
---

| Capability | Verified against a real chat / account | Import- or construct-checked only | Assumed |
|---|---|---|---|
| `FLOOD_ERRORS` | — | ✅ class hierarchy and tuple contents inspected on 1.44.0 | Runtime behaviour of FLOOD_PREMIUM_WAIT not observed |
| `!fw` | — | ✅ argument parser, signature binding, module registration | Server-side effect of `drop_author` / `drop_media_captions` not observed |
| `!sendas` | — | ✅ parser, `send_as=` signature, module registration | That Telegram accepts a given channel as sender in a given chat |
| `!chat collapse` | — | ✅ entity built and serialised (`MessageEntityBlockquote(collapsed=True)`) | That the client renders it expandable |
| `!git pull <branch>` | — | ✅ refname validation, refusal path, default branch | A real fetch of another branch (no network here) |
| Button styles | — | ✅ `KeyboardButtonStyle` built and serialised | Client rendering |
| Copy buttons | — | ✅ `KeyboardButtonCopy` built and serialised; inline-only per docs | Server acceptance of an inline copy button |
| `!info` cross-chat | — | ✅ properties exist on `Message`; code path read | A real cross-chat reply event |
| Update-state fixes | — | ✅ no custom update handling in the repo | That the Repl benefits in practice |

**No message was sent, no RPC was made.** Nothing in this change has been
exercised against a live account.

---
#7. Free-tier impact
---

* **Memory:** two additional command modules, imported once at startup, plus one
  `KeyboardButtonStyle` object per style name. Well under a megabyte. No new
  package, no new thread, no new client.
* **CPU:** nothing periodic was added. `!fw` and `!sendas` are one request each.
  The `FLOOD_ERRORS` tuple is built once at import.
* **Send volume:** unchanged. `!fw` is a forward (a `messages.forwardMessages`
  the user explicitly asked for), `!sendas` is a single `sendMessage`. Neither
  loops, neither retries, both obey the breaker through `flood.FLOOD_ERRORS`.
* **Sleep/resume:** no state is kept in memory for the new commands, so a
  Replit sleep cannot leave them half-configured. `!git pull` remains the only
  command that changes files on disk, and it is unchanged apart from the branch
  argument.
* **Disk:** nothing new is written under `mode/`.

---
#8. Remaining risks
---

1. **Copy buttons on the moderation screen and `/id` are unverified live.** If
   the server rejects `keyboardButtonCopy` in an inline markup, the whole message
   fails with `BUTTON_TYPE_INVALID`. Check `/id` first: it is one message and a
   failure is obvious.
2. **`!sendas` depends on Telegram's admin rule**, which differs between a
   linked discussion group and an ordinary supergroup. Test with a channel that
   is already an admin of the target chat.
3. **`drop_author` is only meaningful where Telegram allows it**; forwarding
   from a channel that hides its authors is unaffected either way.
4. **`!chat collapse` rendering** depends on the client version; older clients
   show a plain quote.
5. **`!git pull <branch>` leaves a detached HEAD.** Correct for this workflow
   (the next pull resets to `FETCH_HEAD`), but anyone typing git commands in a
   shell on the Repl should expect it.
6. **The 1.44 salt-timeout fix is unmeasured** here — it is in the release notes,
   not matched to a hunk in the sender diff.

---
#9. Verdict
---

What the project now uses that it did not before: premium flood waits
(`FLOOD_ERRORS`), `forward_messages` forward modifiers, `send_as`, the
expandable blockquote entity, inline button styles, and `KeyboardButtonCopy`.
Plus the requested `!git pull <branch>`.

Safe to rely on today: the flood handling (it only widens an existing `except`),
`!chat collapse` (client-side rendering of a documented entity), and
`!git pull <branch>` (guarded, and the failure path is visible).

Needs one live check before being trusted: `!sendas` end to end, `!fw -a` on a
real forwarded channel post, and the copy/styled buttons on a client that
supports them. Until then they are import-checked and constructed, not proven.
