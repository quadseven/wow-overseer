"""Role gear swap planning (#540)."""

from __future__ import annotations

import pathlib
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import setswap  # noqa: E402


class SetSwapTest(unittest.TestCase):
    def piece(self, guid, entry, slot, scored):
        return SimpleNamespace(
            holder="Member",
            guid=guid,
            entry=entry,
            slot=slot,
            scored=tuple(sorted(scored.items())),
        )

    def test_healer_seat_withdraws_and_equips_better_healing_chest(self):
        worn = self.piece(1, 100, 4, {"spell_power": 40, "intellect": 15})
        banked = self.piece(2, 200, 4, {"spell_power": 60, "intellect": 20})
        plan = setswap.plan("Member", "healer", 2, 60, [worn], [banked])
        self.assertEqual(("withdraw guid:2",), plan.withdraw)
        self.assertEqual(("e Hitem:200",), plan.equip)

    def test_weaker_bank_piece_stays_and_restore_rows_reverse_the_swap(self):
        worn = self.piece(1, 100, 4, {"spell_power": 40, "intellect": 15})
        weak = self.piece(2, 200, 4, {"spell_power": 1})
        plan = setswap.plan("Member", "healer", 2, 60, [worn], [weak])
        self.assertEqual((), plan.withdraw)
        better = self.piece(3, 300, 4, {"spell_power": 60, "intellect": 20})
        plan = setswap.plan("Member", "healer", 2, 60, [worn], [better])
        self.assertEqual(("e Hitem:100",), plan.restore_equip)
        self.assertEqual(("deposit guid:3",), plan.restore_bank)


if __name__ == "__main__":
    unittest.main()
