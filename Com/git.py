"""!git: pull a branch onto the Repl, and the push stub.

`!git pull` is the Replit half of this repository's workflow: work lands on
`beta` from another machine and the Repl fast-forwards to it without a shell.
It hard-resets, so an edit made on the Repl is thrown away -- that is the point.
Untracked files (session files, mode/ state) are left alone.

`!git pull <branch>` does the same for any other branch, which is how a branch
that has not been merged to `beta` yet gets tested on the Repl. The name is
checked against git's own ref rules and never reaches a shell.

`!git push` is a placeholder: pushing needs credentials the Repl does not have.
"""
import asyncio
import logging
import os
import re

from telethon import events

from Com.core.reply import say

log = logging.getLogger("selftg.git")

__HELP__ = (
    "!git pull → Fetch origin/beta and reset the checkout to it "
    "(local edits to tracked files are discarded)\n"
    "!git pull <branch> → Same, for another branch (e.g. `!git pull new`)\n"
    "!git push → Placeholder; not implemented yet"
)
__CATEGORY__ = "Setup"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRANCH = "beta"
TIMEOUT = 90

# git-check-ref-format, minus the parts that cannot appear in a branch name
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,80}$")


async def _git(*args):
    """Run git in the project root; returns (ok, output)."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=BASE_DIR,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return False, "git is not installed here"
    except Exception as exc:  # noqa: BLE001 - report, never raise into the client
        return False, f"{type(exc).__name__}: {exc}"

    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        return False, f"`git {' '.join(args)}` timed out after {TIMEOUT}s"

    text = out.decode("utf-8", "replace").strip()
    return proc.returncode == 0, text


async def _head():
    ok, out = await _git("log", "-1", "--format=%h %s")
    return out if ok else "?"


async def pull(branch=BRANCH):
    """Fetch origin/<branch> and reset the tracked files to it.

    Returns (ok, text). `branch` is validated by the caller's handler; anything
    that is not a plain refname is refused here too, so a direct call cannot
    smuggle an option into git's argv.
    """
    if not BRANCH_RE.match(branch or ""):
        return False, f"❌ `{branch!r}` is not a branch name."

    before = await _head()

    ok, out = await _git("fetch", "--prune", "origin", branch)
    if not ok:
        log.warning("git: fetch failed: %s", out[:400])
        return False, (f"❌ `git fetch origin {branch}` failed:\n"
                       + (out or "no output"))

    ok, out = await _git("reset", "--hard", "FETCH_HEAD")
    if not ok:
        log.warning("git: reset failed: %s", out[:400])
        return False, "❌ Fetch worked but the reset failed:\n" + (out or "no output")

    after = await _head()
    tail = out.splitlines()[-1] if out else ""
    lines = [
        "✅ Pulled `origin/" + branch + "`.",
        "",
        "Before: `" + before + "`",
        "Now: `" + after + "`",
    ]
    if after == before:
        lines.append("_Already up to date._")
    if tail:
        lines.append("")
        lines.append("`" + tail + "`")
    lines.append("")
    lines.append("Send `!update` to restart on the new code.")
    return True, "\n".join(lines)


def setup(client, my_id):

    @client.on(events.NewMessage(
        from_users=my_id, pattern=r"^!git\s+pull(?:\s+(\S+))?\s*$"))
    async def git_pull(event):
        if not event.out or event.sender_id != my_id:
            return
        branch = (event.pattern_match.group(1) or BRANCH).strip()
        if not BRANCH_RE.match(branch):
            await say(event, f"❌ `{branch}` is not a branch name.", name="git")
            return
        await say(event, "⏳ Pulling `" + branch + "`…", name="git")
        ok, text = await pull(branch)
        if not ok:
            log.info("git: pull failed")
        await say(event, text, name="git")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!git\s+push\s*$"))
    async def git_push(event):
        if not event.out or event.sender_id != my_id:
            return
        await say(event,
                  "🚧 `!git push` is not wired up yet. The Repl has no push "
                  "credentials, so pushes stay manual for now.",
                  name="git")

    @client.on(events.NewMessage(from_users=my_id, pattern=r"^!git\s*$"))
    async def git_help(event):
        if not event.out or event.sender_id != my_id:
            return
        await say(event, "📖 **Git**\n" + __HELP__, name="git")
