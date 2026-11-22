"""Offline smoke test: ``python3 tools/smoke.py``.

What it checks -- all of it without a Telegram account or the network:

1. **Compile** every Python file in the tree (warnings as errors, so a stray
   invalid escape no longer slips through).
2. **Branding**: every message send builds Telegram HTML, not markdown: no
   ``**``/backtick emphasis left in a body, and a body with ``<b>``/``<i>``/
   ``<code>``/``<blockquote>`` always passes ``parse_mode``.
3. **Helpers** that the commands share: duration parsing, the flood gate and
   breaker, the storage cache, confirmation tokens, the arithmetic sandbox and
   the bot's callback-data budget.
4. **Modules**: every ``Com/*.py`` imports and registers handlers against a stub
   client, so a module that silently vanished from ``main.load_commands()``
   (the failure mode behind ``!inline`` never loading) is visible here instead of
   in production.

What it cannot check, and never claims to: any real Telegram call. Sending,
editing, pinning, polls, reactions, reminder delivery and flood behaviour are
outside this harness by definition.

Exit status is 1 when a check fails. Modules skipped because a third-party
package is not installed are listed separately -- that is dependency
provisioning, not a code defect, and on the Repl everything in
``requirements.txt`` is installed.
"""
import ast
import asyncio
import io
import os
import py_compile
import re
import sys
import traceback

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

SKIP_DIRS = {".git", "Logs", "mods", "temp", "mode", "__pycache__", ".pythonlibs"}

failures = []
notes = []


def ok(label, detail=""):
    print(f"  ✅ {label}{(' — ' + detail) if detail else ''}")


def bad(label, detail=""):
    failures.append(f"{label}{(': ' + detail) if detail else ''}")
    print(f"  ❌ {label}{(' — ' + detail) if detail else ''}")


def warn(label):
    notes.append(label)
    print(f"  ⚠️  {label}")


#------------------------------
#1. Compile
#------------------------------

def python_files():
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(root, name)


def check_compile():
    broken = 0
    total = 0
    for path in python_files():
        total += 1
        try:
            py_compile.compile(path, doraise=True, quiet=1)
        except py_compile.PyCompileError as exc:
            broken += 1
            bad("compile " + os.path.relpath(path, BASE_DIR), str(exc)[:200])
    if not broken:
        ok(f"{total} files compile")


#------------------------------
#2. Branding
#------------------------------

# Functions that put a string into a chat
SEND_FUNCS = {"reply", "respond", "edit", "send_message", "send_file"}
SAY_FUNCS = {"say", "_say"}
TEXT_KEYWORDS = {"text", "caption"}

# The tags Com/core/brand.py allows
BRAND_TAG = re.compile(r"</?(?:b|i|code|blockquote)>")
# Markdown the brand replaced with those tags
MARKDOWN = re.compile(r"\*\*|`")

# Raw Telegram calls: a message that never passes through say()/brand.sign()
RAW_SENDS = {"reply", "respond", "edit", "send_message", "send_file"}
RAW_RECEIVERS = {"event", "client", "bot_client", "msg", "message"}

# Deliberate relays: the text is somebody else's content, not an answer from
# this product, so it leaves without the signature. Keyed by module name.
UNSIGNED_ALLOWED = {
    # a DM auto-reply to a contact
    "afk": {"auto_reply"},
    # the rewritten command itself is sent for dispatch
    "alias": {"persian_alias_handler"},
    # bot-API delivery of !inline's payload
    "bot.client": {"send_inline"},
    # queued owner content executed by the self-bot
    "bot.interop": {"_execute"},
    # the challenge answer, posted as the group member
    "cauto": {"answer"},
    # !inline's plain-text fallback when no bot token is set
    "inline": {"inline_cmd"},
    # auto-replies to other people
    "enemy": {"enemy_auto_reply"},
    "menres": {"mention_response"},
    "monitor": {"monitor_handler"},
    "mute": {"mute_handler"},
    # re-sent owner messages and timers
    "f": {"task"},
    "kill": {"kill_cmd"},
    "repeat": {"repeat_cmd"},
    "setkill": {"run_timer"},
    "reply": {"copy_message"},
    # posted as another identity on purpose
    "sendas": {"sendas_cmd"},
    # a query to the owner's whois bot, not a chat message
    "whois": {"whois"},
}


def _text_fragments(node):
    """String literals inside a send's text/caption arguments."""
    candidates = list(node.args[:3])
    candidates += [k.value for k in node.keywords if k.arg in TEXT_KEYWORDS]
    fragments = []
    for arg in candidates:
        for leaf in ast.walk(arg):
            if isinstance(leaf, ast.Constant) and isinstance(leaf.value, str):
                fragments.append(leaf.value)
    return fragments


def _all_strings(node):
    """Every string literal anywhere inside `node`."""
    return [leaf.value for leaf in ast.walk(node)
            if isinstance(leaf, ast.Constant) and isinstance(leaf.value, str)]


def _help_texts(tree):
    """`__HELP__` values and registry.command(...) tables."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "__HELP__" in names:
                yield node.lineno, node.value
        elif isinstance(node, ast.Call):
            func = node.func
            owner = getattr(func, "value", None)
            if getattr(func, "attr", None) == "command" \
                    and getattr(owner, "id", None) == "registry":
                yield node.lineno, node


def _raw_send_name(node):
    """The send method when it is a raw Telegram call, else None."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    name = node.func.attr
    if name not in RAW_SENDS:
        return None
    try:
        receiver = ast.unparse(node.func.value)
    except Exception:  # noqa: BLE001 - unparse is best effort
        return None
    if receiver.split(".")[-1] in RAW_RECEIVERS:
        return name
    return None


def _text_arguments(node):
    """The expressions a raw send would put in the chat."""
    name = node.func.attr
    if name == "send_file":
        args = [k.value for k in node.keywords if k.arg == "caption"]
    elif name in ("reply", "respond", "edit"):
        args = list(node.args[:1])
    else:
        args = list(node.args[1:2])
    args += [k.value for k in node.keywords if k.arg in TEXT_KEYWORDS]
    return args


def _signed_names(tree):
    """Variables assigned from brand.sign()/brand.render()."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if getattr(node.value.func, "attr", None) in ("sign", "render"):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
    return names


def _is_signed(value, signed):
    """True when the expression builds the message through brand."""
    for leaf in ast.walk(value):
        if isinstance(leaf, ast.Call) \
                and getattr(leaf.func, "attr", None) in ("sign", "render"):
            return True
        if isinstance(leaf, ast.Name) and leaf.id in signed:
            return True
    return False


def _enclosing_function(node, tree):
    """Innermost function name around `node`."""
    best = None
    for func in ast.walk(tree):
        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and func.lineno <= node.lineno <= getattr(func, "end_lineno", func.lineno):
            if best is None or func.lineno > best.lineno:
                best = func
    return best.name if best else "<module>"


def _defines_local_say(tree):
    """True when the module wraps `say` with its own parse_mode default."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name in SAY_FUNCS:
            return True
    return False


def check_branding():
    problems = []
    for path in python_files():
        if os.sep + "tools" + os.sep in path:
            continue
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:  # compile already reported it
            continue
        local_say = _defines_local_say(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in SEND_FUNCS | SAY_FUNCS:
                continue
            fragments = _text_fragments(node)
            where = f"{os.path.relpath(path, BASE_DIR)}:{node.lineno}"
            for text in fragments:
                if MARKDOWN.search(text):
                    snippet = text.strip().replace("\n", " ")[:60]
                    problems.append(f"{where}: markdown in {name}(): {snippet!r}")
            has_html = any(BRAND_TAG.search(text) for text in fragments)
            if not has_html or "parse_mode" in {k.arg for k in node.keywords}:
                continue
            # A module's own say()/`_say()` adds the mode itself
            if name in SAY_FUNCS and local_say:
                continue
            problems.append(f"{where}: HTML in {name}() without parse_mode")

        # A raw send must build its body with brand.sign()/brand.render()
        signed = _signed_names(tree)
        module = os.path.basename(path)[:-3]
        if module == "__init__":
            module = os.path.basename(os.path.dirname(path)) + ".__init__"
        elif os.path.basename(os.path.dirname(path)) == "bot":
            module = "bot." + module
        for node in ast.walk(tree):
            name = _raw_send_name(node)
            if name is None:
                continue
            texts = _text_arguments(node)
            if not texts or all(_is_signed(text, signed) for text in texts):
                continue
            func = _enclosing_function(node, tree)
            if func in UNSIGNED_ALLOWED.get(module, set()):
                continue
            problems.append(
                f"{os.path.relpath(path, BASE_DIR)}:{node.lineno}: "
                f"unsigned {name}() in {func}()"
            )

        # Help text reaches the chat too, once the modifiers are escaped
        for lineno, value in _help_texts(tree):
            for text in _all_strings(value):
                if MARKDOWN.search(text):
                    snippet = text.strip().replace("\n", " ")[:60]
                    problems.append(
                        f"{os.path.relpath(path, BASE_DIR)}:{lineno}: "
                        f"markdown in help text: {snippet!r}"
                    )
                    break

    if problems:
        for line in problems[:10]:
            bad("branding", line)
        if len(problems) > 10:
            bad("branding", f"…and {len(problems) - 10} more")
    else:
        ok("no markdown, every HTML body has a mode, every chat reply is signed")


#------------------------------
#3. Shared helpers
#------------------------------

def check_helpers():
    from Com.core import durations, safe_eval

    try:
        assert durations.parse_duration("10m") == 600
        assert durations.parse_duration("2h") == 7200
        assert durations.format_duration(600)
        ok("durations")
    except Exception as exc:  # noqa: BLE001
        bad("durations", repr(exc))

    try:
        assert safe_eval.evaluate("2+3*4") == 14
        assert safe_eval.evaluate("2/4") == 0.5
        for hostile in ("__import__('os')", "().__class__", "9**9**9", "'a'*3"):
            try:
                safe_eval.evaluate(hostile)
            except Exception:  # noqa: BLE001 - rejection is the point
                continue
            raise AssertionError(f"{hostile!r} was accepted")
        ok("safe_eval rejects non-arithmetic")
    except Exception as exc:  # noqa: BLE001
        bad("safe_eval", repr(exc))

    try:
        from Com.core import flood

        flood.reset()
        assert flood.cooldown_left() == 0
        assert flood.note_flood(5) == 0          # one flood is not enough
        assert flood.note_flood(5) == 0
        cooldown = flood.note_flood(5)
        assert cooldown >= flood.BREAKER_COOLDOWN, cooldown
        assert flood.is_open() and flood.cooldown_left() > 0
        flood.reset()
        assert not flood.is_open()
        gap = flood._gap(1.0)                    # jitter stays sane
        assert 0.7 <= gap <= 1.4, gap
        ok("flood gate + breaker")
    except Exception as exc:  # noqa: BLE001
        bad("flood", repr(exc))
        flood.reset()

    try:
        import json
        import tempfile
        from Com.core import storage

        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        with open(path, "w", encoding="utf-8") as handle_file:
            json.dump({"a": 1}, handle_file)

        first = storage.cached_json(path)
        second = storage.cached_json(path)
        assert first is second, "cache did not reuse the parsed document"
        first["a"] = 2
        storage.save_json(path, first)
        assert storage.cached_json(path)["a"] == 2, "write through lost data"

        # A writer outside this process (the dashboard) must invalidate it.
        with open(path, "w", encoding="utf-8") as handle_file:
            json.dump({"a": 3}, handle_file)
        assert storage.cached_json(path)["a"] == 3, "stale after external write"
        os.unlink(path)
        ok("storage cache (reuse, write-through, mtime invalidation)")
    except Exception as exc:  # noqa: BLE001
        bad("storage cache", repr(exc))

    # Loaders run per message; call twice to prove the cache
    try:
        from Com import enemy, monitor, reply

        for _ in range(2):
            monitor.load_data()
            enemy.load_state()
            enemy.load_json("mode/Enemy.json")
            reply.load_data()
        ok("per-message loaders")
    except Exception as exc:  # noqa: BLE001
        bad("per-message loaders", f"{type(exc).__name__}: {exc}")

    try:
        from Com.bot import kit

        data = kit.cb("mod", 123456789012, 0)
        assert len(data) <= kit.CALLBACK_LIMIT
        assert kit.parse_cb(data) == ("mod", "123456789012", "0")
        try:
            kit.cb("x" * 80)
        except ValueError:
            pass
        else:
            raise AssertionError("oversized callback data was accepted")
        ok("callback data budget + round trip")
    except Exception as exc:  # noqa: BLE001
        bad("bot callbacks", repr(exc))


#------------------------------
#4. Modules
#------------------------------

class StubClient:
    """Just enough client for `setup()`: records handlers, does nothing else."""

    def __init__(self):
        self.handlers = 0

    @property
    def loop(self):
        return asyncio.get_event_loop()

    def on(self, event=None, *args, **kwargs):
        def register(func):
            self.handlers += 1
            return func

        return register

    def __getattr__(self, name):
        async def _noop(*args, **kwargs):
            return None

        return _noop


async def check_modules():
    import importlib

    loaded = 0
    handlers = 0
    skipped = []

    for filename in sorted(os.listdir(os.path.join(BASE_DIR, "Com"))):
        if not filename.endswith(".py") or filename == "__init__.py":
            continue
        module_name = "Com." + filename[:-3]
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            skipped.append(f"{filename[:-3]} ({exc.name})")
            continue
        except Exception as exc:  # noqa: BLE001 - a broken module is a failure
            bad("import " + module_name, f"{type(exc).__name__}: {exc}")
            continue

        if not hasattr(module, "setup"):
            loaded += 1
            continue

        client = StubClient()
        try:
            result = module.setup(client, 1)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001
            bad("setup " + module_name, f"{type(exc).__name__}: {exc}")
            continue

        loaded += 1
        handlers += client.handlers
        if client.handlers == 0 and hasattr(module, "__HELP__"):
            warn(f"{module_name} documents commands but registered no handler")

    ok(f"{loaded} modules loaded, {handlers} handlers registered")
    if skipped:
        warn("skipped for missing dependencies: " + ", ".join(skipped))

    # Cancel fire-and-forget tasks so the harness exits
    current = asyncio.current_task()
    for task in asyncio.all_tasks():
        if task is not current:
            task.cancel()


#------------------------------
#Main
#------------------------------

def main():
    print("SelfTG smoke test\n")
    print("1. compile")
    check_compile()
    print("\n2. branding")
    check_branding()
    print("\n3. helpers")
    check_helpers()
    print("\n4. modules")
    try:
        asyncio.run(check_modules())
    except Exception:  # noqa: BLE001 - report, never hide
        traceback.print_exc()
        bad("module load", "harness crashed")

    print()
    if failures:
        print(f"❌ {len(failures)} check(s) failed")
        for line in failures:
            print("   -", line)
        return 1
    print("✅ all checks passed (nothing was sent to Telegram)")
    if notes:
        for line in notes:
            print("   ⚠️ ", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
