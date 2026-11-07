"""Member and column claim decisions share the claims boundary."""

import unittest
from types import SimpleNamespace

import claims
import townslot
import classquest


class ClaimsTests(unittest.TestCase):
    def test_member_holds_report_all_reasons_and_stranded_member_can_be_freed(self):
        holds = claims.member_holds(
            guild_runs={"Knight"}, handover_runs={"Knight", "Mage"}
        )
        self.assertEqual(
            {"Knight": ("guild run", "hand-over run"), "Mage": ("hand-over run",)},
            holds,
        )
        members = [
            SimpleNamespace(
                name="Knight",
                online=True,
                class_id=classquest.DEATH_KNIGHT,
                map_id=classquest.DEATH_KNIGHT_START_MAP,
            )
        ]
        self.assertEqual({"Knight"}, claims.stranded_knights(members, holds))
        self.assertEqual(
            set(), claims.stranded_knights(members, holds, job_steps={"Knight"})
        )

    def test_column_slot_surface_is_the_existing_townslot_decider(self):
        self.assertIs(claims.Slot, townslot.Slot)


if __name__ == "__main__":
    unittest.main()
