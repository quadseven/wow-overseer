"""A share across parties is never asked for (mod-overseer#969).

DoShare refuses a share whose holder and taker are not in one Group
("holder and taker are not in the same party"). Live, that refusal was 7452
of 7824 kind='share' errors in a day, offered hourly per pair: about ten
errors for every delivery. The planner now knows each member's party and
names a holder in the taker's party, or refuses the pair as not-grouped and
asks the worldserver nothing.
"""

import unittest
from unittest import mock

import questbook
import questshare
from test_guildsocial_bridge import bridge
from test_questshare import CATALOG, FAMILY, _ids_for, _reasons_for

# Two parties: Grug leads Grug and Grog, Og leads Og and Ugga, and Bork is
# in no party. The keys are leader guids, as overseer_snapshot writes them.
SPLIT = {"Grug": 11, "Grog": 11, "Og": 22, "Ugga": 22, "Bork": 0}
ONE_PARTY = {name: 11 for name in SPLIT}


class NoShareAcrossParties(unittest.TestCase):
    def test_no_grant_names_a_holder_outside_the_takers_party(self):
        plan = questshare.plan(FAMILY, CATALOG, SPLIT)
        self.assertTrue(plan.grants)
        for g in plan.grants:
            self.assertTrue(questshare.grouped(g.holder, g.taker, SPLIT), g)

    def test_the_holder_is_picked_from_the_takers_party(self):
        # Grug and Og both carry 35. Lowest name would pick Grug, who is not
        # in Ugga's party; Og is, so Og hands it over.
        plan = questshare.plan(FAMILY, CATALOG, SPLIT)
        (grant,) = [g for g in plan.grants if g.taker == "Ugga" and g.quest_id == 35]
        self.assertEqual(grant.holder, "Og")

    def test_a_quest_nobody_in_the_party_carries_is_refused_not_granted(self):
        # 37 is carried by Grug alone; Ugga is in Og's party.
        plan = questshare.plan(FAMILY, CATALOG, SPLIT)
        self.assertNotIn(37, _ids_for("Ugga", plan))
        self.assertIn(questshare.NOT_GROUPED, _reasons_for("Ugga", 37, plan))

    def test_a_member_in_no_party_is_neither_given_nor_asked_to_give(self):
        plan = questshare.plan(FAMILY, CATALOG, SPLIT)
        self.assertEqual(_ids_for("Bork", plan), [])
        self.assertFalse([g for g in plan.grants if g.holder == "Bork"])

    def test_a_member_with_no_fresh_snapshot_is_in_no_party(self):
        parties = {k: v for k, v in ONE_PARTY.items() if k != "Grog"}
        plan = questshare.plan(FAMILY, CATALOG, parties)
        self.assertEqual(_ids_for("Grog", plan), [])
        self.assertIn(questshare.NOT_GROUPED, _reasons_for("Grog", 35, plan))

    def test_the_refusal_is_said(self):
        plan = questshare.plan(FAMILY, CATALOG, SPLIT)
        self.assertIn(questshare.NOT_GROUPED, questshare.say(plan))

    def test_one_party_plans_as_before(self):
        self.assertEqual(
            questshare.plan(FAMILY, CATALOG, ONE_PARTY),
            questshare.plan(FAMILY, CATALOG),
        )

    def test_an_ungrouped_pair_takes_no_log_slot(self):
        # A taker one slot short of full: the one share that can land must
        # get the slot, not a share across parties ordered before it.
        quests = {
            q: questbook.Quest(id=q, flags=questshare.QUEST_FLAGS_SHARABLE)
            for q in (1, 2)
        }
        filler = frozenset(range(1000, 1000 + questshare.MAX_QUEST_LOG_SIZE - 1))
        members = [
            questbook.Member(
                name="A", class_id=1, race_id=1, level=10, held=frozenset({1})
            ),
            questbook.Member(
                name="B", class_id=1, race_id=1, level=10, held=frozenset({2})
            ),
            questbook.Member(name="T", class_id=1, race_id=1, level=10, held=filler),
        ]
        plan = questshare.plan(members, quests, {"A": 5, "B": 6, "T": 6})
        self.assertEqual(
            [(g.holder, g.quest_id) for g in plan.grants if g.taker == "T"], [("B", 2)]
        )


class TheBridgeAsksOnlyWithinAParty(unittest.TestCase):
    """_share_family_quests, driven with the reads stubbed: it inserts no
    share the snapshot says crosses parties."""

    def run_pass(self, parties):
        inserted = []
        with mock.patch.multiple(
            bridge,
            _fetch_family_quests=lambda names: (FAMILY, CATALOG),
            _fetch_parties=lambda names: parties,
            _recent_share_keys=lambda minutes: set(),
            _answered_share_rows=lambda days, depth: [],
            _insert_share=lambda grant: inserted.append(grant) or 1,
        ):
            bridge._share_family_quests([m.name for m in FAMILY])
        return inserted

    def test_no_row_is_written_for_a_pair_in_different_parties(self):
        inserted = self.run_pass(SPLIT)
        self.assertTrue(inserted)
        for g in inserted:
            self.assertTrue(questshare.grouped(g.holder, g.taker, SPLIT), g)

    def test_a_world_without_party_facts_shares_as_before(self):
        self.assertEqual(
            self.run_pass(None), list(questshare.plan(FAMILY, CATALOG).grants)
        )


if __name__ == "__main__":
    unittest.main()
