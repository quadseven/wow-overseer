"""The world-driving half must be able to run without a Discord gateway.

WHY THIS SUITE IS A CONTRACT OVER SOURCE TEXT rather than an import. This
directory's suites are stdlib-only and run with NO pip install (see
check.python-units.yml's own scope note), and bridge.py imports `discord` and
`pymysql` at module level. Importing it here would not test the headless path,
it would fail collection in CI. So this pins the ways headless could be shipped
and still do nothing - the same pattern tests/test_job_mode.py uses for C++ it
cannot compile.

WHAT IT IS GUARDING. wow-dev runs the overseer deployment scaled to zero,
because the process holds a Discord gateway session on a bot token and two
sessions on one token both answer the same real message. That is still true and
is not being changed. But the same process is also the questing brain: measured
on 2026-08-29, the live family was being aimed at quest 14 continuously while
the dev family - identical in every other way - stood in Elwynn for 39 minutes
with drive_quest = 0 for all five, because nothing was running to set it.

The safety property that makes headless allowed at all is that NO GATEWAY IS
EVER CONNECTED, so discord.Client.get_channel reads an empty connection state
and returns None for every id, and every send site in bridge.py is already
guarded on exactly that. A headless process cannot post to Discord because
there is nothing to post through - not because it promises not to.
"""

import ast
import asyncio
import pathlib
import re
import unittest

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


def _source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _block(signature: str) -> str:
    """One def's body, to the next def at the same or shallower indent."""
    src = _source()
    start = src.index(signature)
    indent = len(src[:start].split("\n")[-1])
    lines = src[start:].split("\n")
    out = [lines[0]]
    for line in lines[1:]:
        if line.strip() and not line.startswith(" " * (indent + 1)):
            break
        out.append(line)
    return "\n".join(out)


class TheHeadlessRuntimeExists(unittest.TestCase):
    def test_it_subclasses_the_bridge_rather_than_reimplementing_it(self):
        """A parallel implementation would drift: the drives would be fixed in
        one and not the other, silently, for exactly as long as nobody ran the
        dev world hard enough to notice."""
        self.assertIn("class HeadlessBridge(Bridge):", _source())

    def test_it_neutralises_the_two_gateway_waits(self):
        """Every loop opens with `await self.wait_until_ready()` and spins on
        `while not self.is_closed()`. Both wait on state only a gateway READY
        sets. Without overriding them the loops would not misbehave - they
        would never start, and nothing would say so."""
        src = _source()
        self.assertRegex(
            src, r"async def wait_until_ready\(self\)\s*->\s*None:\s*\n\s*return"
        )
        self.assertRegex(src, r"def is_closed\(self\)\s*->\s*bool:\s*\n\s*return False")


def _tree() -> ast.Module:
    return ast.parse(_source())


def _class(name: str) -> ast.ClassDef:
    return next(
        n for n in _tree().body if isinstance(n, ast.ClassDef) and n.name == name
    )


def _registry() -> list:
    """PASSES as written: (method name, runs headless) per entry, in order."""
    node = next(
        n
        for n in _tree().body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "PASSES" for t in n.targets)
    )
    out = []
    for call in node.value.elts:
        headless = True
        for kw in call.keywords:
            if kw.arg == "headless":
                headless = kw.value.value
        out.append((call.args[0].value, headless))
    return out


def _bridge_coroutines() -> set:
    return {
        n.name for n in _class("Bridge").body if isinstance(n, ast.AsyncFunctionDef)
    }


def _segment(lines: list, node: ast.AST) -> str:
    """A node's whole lines, decorators included, at their own indent."""
    first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    return "\n".join(lines[first - 1 : node.end_lineno]) + "\n"


def _start_harness():
    """The two start paths, run for real against recorders.

    bridge.py cannot be imported here (see the module docstring), so this
    execs its own source for the pass registry, the store setup and both start
    paths, with asyncio and every `_ensure_*_store` replaced by recorders.
    """
    import dataclasses
    import types

    src = _source()
    lines = src.split("\n")
    tree = ast.parse(src)
    module = [
        n
        for n in tree.body
        if (isinstance(n, ast.ClassDef) and n.name == "_Pass")
        or (
            isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "PASSES" for t in n.targets)
        )
    ]
    wanted = {
        "Bridge": ("setup_hook", "on_ready", "_pass_coroutines", "_ensure_stores"),
        "HeadlessBridge": ("run_headless",),
    }
    methods = [
        m
        for c in tree.body
        if isinstance(c, ast.ClassDef) and c.name in wanted
        for m in c.body
        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
        and m.name in wanted[c.name]
    ]
    code = "".join(_segment(lines, n) for n in module)
    code += "class Harness:\n" + "".join(_segment(lines, m) for m in methods)

    started: list = []
    ensured: list = []

    async def to_thread(fn, *args):
        return fn(*args)

    async def gather(*tasks):
        return None

    def create_task(coro):
        started.append(coro)
        return object()

    ns = {
        "dataclasses": dataclasses,
        "asyncio": types.SimpleNamespace(
            create_task=create_task, gather=gather, to_thread=to_thread
        ),
        "log": types.SimpleNamespace(info=lambda *a: None, error=lambda *a: None),
    }
    for store in set(re.findall(r"_ensure_\w+_store", src)):
        ns[store] = lambda store=store: ensured.append(store)
    exec(code, ns)  # noqa: S102 - bridge.py's own source

    def fake_pass(name):
        def coro():
            return name

        coro.__name__ = name
        return coro

    class Harness(ns["Harness"]):
        user = "the bridge"
        guilds = ("a guild",)

        def __getattr__(self, name):
            return fake_pass(name)

    return Harness(), started, ensured


class EveryPassIsDeclaredOnce(unittest.TestCase):
    """setup_hook and run_headless used to hold two hand-kept lists, and they
    drifted: _loot_council_loop was started with a gateway and not without
    one, so a headless world never answered a loot council. Both now start
    the one registry, PASSES."""

    def test_every_loop_method_is_in_the_registry(self):
        """So a new pass cannot be written and never started."""
        declared = {name for name, _ in _registry()}
        loops = {n for n in _bridge_coroutines() if n.endswith("_loop")}
        self.assertGreater(len(loops), 30)
        self.assertEqual(set(), loops - declared)

    def test_every_entry_names_a_bridge_coroutine_once(self):
        names = [name for name, _ in _registry()]
        self.assertEqual(len(names), len(set(names)), "a pass is declared twice")
        self.assertEqual(set(), set(names) - _bridge_coroutines())

    def test_loot_councils_are_answered_headless(self):
        self.assertIn(("_loot_council_loop", True), _registry())

    def test_the_council_loop_waits_for_ready_like_its_siblings(self):
        """Headless the wait returns at once; with a gateway it holds the loop
        until READY, as every other pass does."""
        body = _block("async def _loot_council_loop(self)")
        self.assertIn("await self.wait_until_ready()", body)


class TheChatRelayIsTheOnlyThingLeftOut(unittest.TestCase):
    """Its whole job is carrying in-world chat TO Discord. Headless it can only
    warn that the channel is invisible, once every RELAY_SECONDS, forever -
    which buries the lines that matter. Everything else drives the world."""

    def test_only_the_relay_is_discord_only(self):
        self.assertEqual(
            ["_relay_chat"], [name for name, headless in _registry() if not headless]
        )

    def test_the_quest_brain_is_declared_for_both_paths(self):
        """_supervise_goals is what aims the party at a quest at all. If it
        does not run headless, dev gets a process that starts, logs
        cheerfully, and still never gives anybody something to do."""
        for drive in ("_supervise_goals", "_hold_council", "_share_quests_loop"):
            with self.subTest(drive=drive):
                self.assertIn((drive, True), _registry())


class BothStartPathsRunTheRegistry(unittest.TestCase):
    def test_the_gateway_path_starts_every_pass_in_order(self):
        bridge, started, _ = _start_harness()
        asyncio.run(bridge.setup_hook())
        self.assertEqual([name for name, _ in _registry()], started)

    def test_the_headless_path_starts_exactly_the_headless_passes(self):
        bridge, started, _ = _start_harness()
        asyncio.run(bridge.run_headless())
        self.assertEqual([name for name, headless in _registry() if headless], started)
        self.assertIn("_loot_council_loop", started)
        self.assertNotIn("_relay_chat", started)


class TheStoreSetupIsListedOnce(unittest.TestCase):
    """on_ready creates the tables before any loop queries them. A headless
    run that skipped one would fail on the first query of every loop that
    reads it."""

    def test_both_paths_ensure_the_same_stores(self):
        bridge, _, on_ready = _start_harness()
        asyncio.run(bridge.on_ready())
        bridge, _, headless = _start_harness()
        asyncio.run(bridge.run_headless())
        self.assertGreaterEqual(len(on_ready), 10)
        self.assertEqual(on_ready, headless)

    def test_neither_path_lists_a_store_itself(self):
        for sig in ("async def on_ready(self)", "async def run_headless(self)"):
            with self.subTest(path=sig):
                body = _block(sig)
                self.assertEqual([], re.findall(r"_ensure_\w+_store", body))
                self.assertIn("await self._ensure_stores()", body)


class HeadlessIsChosenNeverFallenInto(unittest.TestCase):
    def test_it_requires_an_explicit_opt_in(self):
        """An absent token could mean 'this is dev' or 'the secret failed to
        mount in production'. Guessing the first would turn a broken live
        deploy into a bridge that looks healthy and answers nobody."""
        body = _block("def main() -> None:")
        self.assertIn("OVERSEER_HEADLESS", body)
        opt_in = body.index("OVERSEER_HEADLESS")
        token = body.index('os.environ["DISCORD_BOT_TOKEN"]')
        self.assertLess(
            opt_in,
            token,
            "the headless branch must be taken before the token is required",
        )

    def test_the_gateway_path_still_requires_its_token(self):
        """The live path must keep failing loudly on a missing secret."""
        self.assertIn('os.environ["DISCORD_BOT_TOKEN"]', _block("def main() -> None:"))

    def test_headless_passes_no_token_anywhere(self):
        """The headless branch returns before the token is ever read, so a dev
        world cannot authenticate as the live bot even by accident."""
        body = _block("def main() -> None:")
        headless = body[
            body.index("OVERSEER_HEADLESS") : body.index("    token = os.environ")
        ]
        self.assertNotIn("token", headless.lower())
        self.assertIn("return", headless)


if __name__ == "__main__":
    unittest.main()
