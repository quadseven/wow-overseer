"""Rank deposit grants are written without a walk to the vault (#2657 follow-up).

Measured on the dev realm on 2026-11-15: the second guild bought its second tab
two days earlier and no rank was ever opened to it, because the pass queues every
setup command only when the leader stands at the vault, and the leader could not
be aimed there (the town slot was held by another errand; the vault is a
continent away). The module's `bank grant-deposit` has no vault-range check, only
that the character is the guild master with a session, so it needs no arrival.
`buy-tab` and `name-tab` do check the vault and keep waiting for one.
"""

from __future__ import annotations

import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import guildbank  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

A = guildbank.SetupAction
ACTIONS = (
    A("Zug", "bank buy-tab tab:2"),
    A("Zug", "bank grant-deposit rank:1"),
    A("Zug", "bank grant-deposit rank:2"),
    A("Zug", "bank name-tab tab:1 icon:INV_Chest_Chain_05 Gear for Later"),
)


class TheSplit(unittest.TestCase):
    def test_grants_need_no_vault_and_the_rest_do(self):
        anywhere, at_vault = guildbank.split_remote(ACTIONS)
        self.assertEqual(
            [a.command for a in anywhere],
            ["bank grant-deposit rank:1", "bank grant-deposit rank:2"],
        )
        self.assertEqual(
            [a.command.split()[1] for a in at_vault], ["buy-tab", "name-tab"]
        )

    def test_nothing_is_lost_or_doubled(self):
        anywhere, at_vault = guildbank.split_remote(ACTIONS)
        self.assertEqual(set(anywhere) | set(at_vault), set(ACTIONS))
        self.assertEqual(len(anywhere) + len(at_vault), len(ACTIONS))

    def test_no_actions_split_to_nothing(self):
        self.assertEqual(guildbank.split_remote(()), ((), ()))


class TheBridgeWritesThemBeforeTheWalk(unittest.TestCase):
    def body(self, header):
        start = BRIDGE.index(header)
        end = re.compile(r"\n(?:async )?def ").search(BRIDGE, start + 10).start()
        inner = BRIDGE.find("\n    async def ", start + 10)
        return BRIDGE[start : min(end, inner) if inner != -1 else end]

    def test_grants_are_queued_before_the_vault_is_claimed(self):
        body = self.body("    async def _guild_bank_once(")
        wrote = body.index("_queue_remote_setup(")
        claimed = body.index('aimed = await self._claim_town_slot("guild bank"')
        self.assertLess(wrote, claimed)

    def test_the_writer_splits_dedupes_and_hands_back_the_vault_ones(self):
        body = self.body("async def _queue_remote_setup(")
        self.assertIn("guildbank.split_remote(", body)
        self.assertIn("_recent_guild_setup_keys", body)
        self.assertIn("return at_vault", body)


if __name__ == "__main__":
    unittest.main()
