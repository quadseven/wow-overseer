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


class TheChatRelayIsTheOnlyThingLeftOut(unittest.TestCase):
    """Its whole job is carrying in-world chat TO Discord. Headless it can only
    warn that the channel is invisible, once every RELAY_SECONDS, forever -
    which buries the lines that matter. Everything else drives the world."""

    def test_the_relay_is_skipped(self):
        self.assertIn("_relay_chat", _block("HEADLESS_SKIP"))

    def test_nothing_else_is_skipped(self):
        skip = _block("HEADLESS_SKIP = ")
        for drive in (
            "_supervise_goals",
            "_hold_council",
            "_share_quests_loop",
            "_restore_lost_lives",
            "_protect_characters",
        ):
            with self.subTest(drive=drive):
                self.assertNotIn(drive, skip)

    def test_the_quest_brain_is_actually_run(self):
        """_supervise_goals is what aims the party at a quest at all. If it is
        not in the headless loop list, dev gets a process that starts, logs
        cheerfully, and still never gives anybody something to do."""
        body = _block("async def run_headless(self)")
        for drive in ("_supervise_goals", "_hold_council", "_share_quests_loop"):
            with self.subTest(drive=drive):
                self.assertIn(drive, body)


class TheSetupOnReadyDoesIsNotSkipped(unittest.TestCase):
    """on_ready creates four tables before any loop queries them. A headless
    run that skipped it would fail on the first query of every loop."""

    def test_every_store_on_ready_ensures_is_ensured_here(self):
        on_ready = _block("async def on_ready(self)")
        headless = _block("async def run_headless(self)")
        stores = set(re.findall(r"_ensure_\w+_store", on_ready))
        self.assertTrue(
            stores, "on_ready no longer ensures any store - update this test"
        )
        for store in sorted(stores):
            with self.subTest(store=store):
                self.assertIn(store, headless)


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
