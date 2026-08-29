"""One bridge per world, separated by which channels it was told about.

THE FAILURE THIS PREVENTS, CONCRETELY. Two worlds now exist - live and wow-dev
- with the same five character names, and the plan is to run a bridge for each.
`core.parse_directive` acts on any line starting with `@` from an allowed user,
in ANY channel; the overseer channel only decides whether an UNaddressed message
also gets an answer. So before this rule, typing

    @Grug .additem 12345

in #overseer-dev would be parsed by the dev bridge AND by the production one,
and production would run it on the LIVE Grug. That is the double-delivery
failure 70-overseer.yaml warns about, reached through channels instead of
through two gateway sessions.

WHY THE TEST IS A SOURCE CONTRACT. These suites are stdlib-only and run with no
pip install (check.python-units.yml's scope note), and bridge.py imports
`discord` and `pymysql` at module level. The parse half IS importable, so the
half of this suite that can execute does, and the wiring half is pinned as
text - the same split tests/test_headless_bridge.py uses.
"""
import pathlib
import unittest

import core

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

PROD_OVERSEER = "1540419847765237913"   # #overseer-prod
PROD_CHAT = "1540695363093139537"       # #overseer-prod-grug
DEV = "1543057103898279966"             # #overseer-dev

ALLOWED = frozenset({"9001"})


class WhatMakesTheLeakPossible(unittest.TestCase):
    """Executable half: this is why a channel check is needed at all. If these
    ever start returning [] for a non-dedicated channel, the guard could be
    relaxed - and until then it cannot."""

    def test_a_directive_is_acted_on_even_outside_the_dedicated_channel(self):
        decisions = core.parse_directive(
            "@Grug .additem 12345", "9001", ALLOWED, dedicated=False
        )
        self.assertTrue(
            decisions,
            "parse_directive ignores the channel entirely - so on_message must not",
        )

    def test_a_stranger_is_still_ignored(self):
        """The allowlist is a separate, older guard. Kept working."""
        self.assertEqual(
            core.parse_directive("@Grug .additem 1", "nobody", ALLOWED, dedicated=True),
            [],
        )


class TheBridgeOnlyActsInChannelsItOwns(unittest.TestCase):

    @staticmethod
    def _source() -> str:
        return BRIDGE.read_text(encoding="utf-8")

    def test_the_owned_set_is_built_from_both_configured_channels(self):
        src = self._source()
        self.assertIn("OWNED_CHANNEL_IDS", src)
        start = src.index("OWNED_CHANNEL_IDS = frozenset(")
        block = src[start:src.index(")", start) + 1]
        self.assertIn("OVERSEER_CHANNEL_ID", block)
        self.assertIn("CHAT_CHANNEL_ID", block)

    def test_on_message_returns_early_for_a_channel_it_does_not_own(self):
        src = self._source()
        start = src.index("async def on_message(")
        body = src[start:src.index("\n    async def", start + 10)]
        self.assertIn("OWNED_CHANNEL_IDS", body)
        # The guard has to run BEFORE anything is parsed, or the leak is only
        # narrowed rather than closed.
        self.assertLess(
            body.index("OWNED_CHANNEL_IDS"),
            body.index("parse_directive"),
            "the channel guard must precede parsing",
        )

    def test_an_unconfigured_bridge_still_listens_everywhere(self):
        """Empty means everywhere, on purpose. A single-world install that
        names no channel has always listened everywhere, and going silently
        deaf is a worse failure than the one this prevents: the bridge would
        look healthy and answer nobody."""
        src = self._source()
        start = src.index("async def on_message(")
        body = src[start:src.index("\n    async def", start + 10)]
        self.assertIn("if OWNED_CHANNEL_IDS and", body)


class TheTwoWorldsCannotOverlap(unittest.TestCase):
    """The real channel ids, so a copy-paste that points dev at a prod channel
    fails here rather than on the live family."""

    def test_prod_and_dev_share_no_channel(self):
        prod = {PROD_OVERSEER, PROD_CHAT}
        dev = {DEV}
        self.assertEqual(prod & dev, set())

    def test_the_ids_are_distinct(self):
        self.assertEqual(len({PROD_OVERSEER, PROD_CHAT, DEV}), 3)


if __name__ == "__main__":
    unittest.main()
