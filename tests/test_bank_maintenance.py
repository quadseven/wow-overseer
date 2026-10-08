"""Bank maintenance (2026-10-08): spare copies, the free-slot reserve, and
shared stock that moves on to the guild bank once its tab has room.

Written from the dev family's Watch tab: a level-42 warrior with a 28 of 28
personal bank holding four copies of one kilt, a mage with seven copies of one
cowl, and materials the guild's Materials tab would have taken.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bank  # noqa: E402
import bankpolicy  # noqa: E402
import disposition  # noqa: E402
from test_bank import REAL, row  # noqa: E402
from test_bankpolicy import PALADIN, piece, reach  # noqa: E402

GUILD = {
    "purchased_tabs": 1,
    "deposit_rank_ids": [0],
    "member_ranks": {"Grug": 0},
    "tab_items": {0: 50},
}


def kilts(count, holder="Grog", bound=False):
    return [
        piece(
            n,
            "Jinxed Hoodoo Kilt",
            holder=holder,
            entry=7000,
            quality=3,
            required_level=44,
            bound=bound,
        )
        for n in range(1, count + 1)
    ]


def facts_for(pieces, later=(), family=None, **kw):
    return bankpolicy.Facts(
        pieces=tuple(pieces),
        family=tuple(family or (bankpolicy.Keeper("Grog", PALADIN, 40, "damage"),)),
        reach={
            p.guid: reach(bucket="legs", guild=later, **kw.get("reach", {}))
            for p in pieces
        },
        reserved=tuple(kw.get("reserved", ())),
    )


class TheSameItemIsOneStepOnTheLadder(unittest.TestCase):
    def test_four_copies_of_a_kilt_keep_one_in_the_bank(self):
        placed = bankpolicy.place(facts_for(kilts(4)))
        self.assertEqual(1, len(placed))

    def test_the_three_other_copies_are_spare(self):
        facts = facts_for(kilts(4))
        spare = bankpolicy.redundant(facts)
        self.assertEqual(3, len(spare))
        self.assertFalse(spare & set(bankpolicy.place(facts)))

    def test_a_member_who_will_wear_it_keeps_a_copy_too(self):
        spare = bankpolicy.redundant(facts_for(kilts(4), later=("Ugga",)))
        self.assertEqual(2, len(spare))

    def test_a_soulbound_copy_cannot_go_to_another_member(self):
        spare = bankpolicy.redundant(facts_for(kilts(4, bound=True), later=("Ugga",)))
        self.assertEqual(3, len(spare))

    def test_one_copy_is_never_spare(self):
        self.assertEqual(frozenset(), bankpolicy.redundant(facts_for(kilts(1))))

    def test_an_epic_is_never_named(self):
        epics = [
            piece(n, "Epic", entry=8000, quality=4, required_level=44) for n in (1, 2)
        ]
        self.assertEqual(frozenset(), bankpolicy.redundant(facts_for(epics)))

    def test_a_piece_the_operator_reserved_is_never_named(self):
        held = bankpolicy.Reservation("Grog", 7000, 52, "operator")
        spare = bankpolicy.redundant(facts_for(kilts(3), reserved=(held,)))
        self.assertEqual(frozenset(), spare)

    def test_a_copy_nobody_could_judge_names_nothing(self):
        facts = facts_for(kilts(3))
        facts = bankpolicy.Facts(
            pieces=facts.pieces, family=facts.family, reach={1: facts.reach[1]}
        )
        self.assertEqual(frozenset(), bankpolicy.redundant(facts))


class ASpareCopyIsSold(unittest.TestCase):
    def item(self, **kw):
        base = dict(
            name="Jinxed Hoodoo Kilt",
            known=True,
            quest_item=False,
            equipment=True,
            quality=3,
            required_level=44,
            sell_price=900,
            binding=disposition.BIND_ON_EQUIP,
        )
        base.update(kw)
        return disposition.Item(**base)

    def decide(self, **kw):
        return disposition.decide(
            self.item(),
            disposition.Family(vendor_reachable=True),
            character_level=42,
            available=frozenset({disposition.VENDOR, disposition.KEEP}),
            **kw,
        )

    def test_without_the_word_it_is_kept_for_its_level(self):
        self.assertEqual(disposition.KEEP, self.decide().route)

    def test_a_spare_copy_goes_to_the_vendor(self):
        self.assertEqual(disposition.VENDOR, self.decide(spare=True).route)

    def test_a_sibling_who_would_wear_it_gets_the_hand_off_first(self):
        verdict = self.decide(spare=True, family_fit=disposition.FIT_SIBLING)
        self.assertNotEqual(disposition.VENDOR, verdict.route)

    def test_a_quest_item_is_never_spare(self):
        verdict = disposition.decide(
            self.item(quest_item=True),
            disposition.Family(vendor_reachable=True),
            character_level=42,
            spare=True,
        )
        self.assertEqual(disposition.KEEP, verdict.route)


def storage(**kw):
    return bank.storage_from({"Grug": {}}, guild=kw.pop("guild", GUILD), **kw)


class ASpareCopyComesOutOfTheBank(unittest.TestCase):
    def rows(self):
        return [
            row(
                item_guid=10,
                name="Jinxed Hoodoo Kilt",
                item_class=4,
                quality=3,
                required_level=44,
                slot=39,
                bonding=2,
            ),
            row(
                item_guid=11,
                name="Jinxed Hoodoo Kilt",
                item_class=4,
                quality=3,
                required_level=44,
                slot=40,
                bonding=2,
            ),
        ]

    KEPT = bankpolicy.Placement(
        10,
        "Grug",
        "Jinxed Hoodoo Kilt",
        bankpolicy.PERSONAL,
        None,
        bankpolicy.GROWS_INTO,
        "Grug keeps it until level 44",
    )

    def test_the_spare_is_withdrawn_and_the_kept_one_stays(self):
        members = bank.members_from_rows(self.rows(), ["Grug"])
        plan = bank.plan(
            members,
            REAL,
            storage=storage(spare=frozenset({11}), policy={10: self.KEPT}),
        )
        self.assertEqual([(bank.WITHDRAW, 11)], [(m.verb, m.guid) for m in plan.moves])

    def test_without_a_spare_nothing_comes_out(self):
        members = bank.members_from_rows(self.rows(), ["Grug"])
        both = {10: self.KEPT, 11: self.KEPT}
        self.assertEqual(
            (), bank.plan(members, REAL, storage=storage(policy=both)).moves
        )


class ABankKeepsRoomForTheNextThing(unittest.TestCase):
    def rows(self, filled):
        out = [
            row(item_guid=1000 + n, name="Rough Stone", slot=slot)
            for n, slot in zip(range(filled), bank.BANK_ITEM_SLOTS)
        ]
        out += [
            row(item_guid=11, name="Malachite", count=9, slot=23),
            row(item_guid=12, name="Malachite", count=9, slot=24),
        ]
        return out

    def plan(self, filled):
        members = bank.members_from_rows(self.rows(filled), ["Grug"])
        return bank.plan(members, REAL)

    def test_a_deposit_that_would_leave_under_two_free_slots_waits(self):
        plan = self.plan(bank.BANK_SIZE - 3)
        self.assertEqual(1, len(plan.moves))
        self.assertTrue(any("keeps 2" in note for note in plan.notes))

    def test_with_two_free_nothing_goes_down(self):
        self.assertEqual((), self.plan(bank.BANK_SIZE - 2).moves)

    def test_an_empty_bank_banks_everything(self):
        self.assertEqual(2, len(self.plan(0).moves))

    def test_the_operators_reserved_stack_may_use_the_last_slots(self):
        placed = bankpolicy.Placement(
            11,
            "Grug",
            "Malachite",
            bankpolicy.PERSONAL,
            None,
            bankpolicy.RESERVED,
            "Grug keeps it",
        )
        members = bank.members_from_rows(self.rows(bank.BANK_SIZE - 1), ["Grug"])
        plan = bank.plan(members, REAL, storage=storage(policy={11: placed}))
        self.assertEqual([11], [m.guid for m in plan.moves])


class SharedStockMovesOnWhenTheGuildHasRoom(unittest.TestCase):
    def rows(self):
        return [
            row(
                item_guid=21,
                name="Moss Agate",
                item_class=3,
                quality=2,
                slot=39,
                count=5,
            )
        ]

    def plan(self, guild):
        members = bank.members_from_rows(self.rows(), ["Grug"])
        return bank.plan(members, REAL, storage=storage(guild=guild))

    def test_a_banked_gem_comes_out_for_the_guild_bank(self):
        plan = self.plan(GUILD)
        self.assertEqual([(bank.WITHDRAW, 21)], [(m.verb, m.guid) for m in plan.moves])
        self.assertIn("guild bank", plan.moves[0].why)

    def test_a_full_tab_leaves_it_where_it_is(self):
        self.assertEqual((), self.plan(dict(GUILD, tab_items={0: 98})).moves)

    def test_no_tab_leaves_it_where_it_is(self):
        self.assertEqual((), self.plan(dict(GUILD, purchased_tabs=0)).moves)

    def test_a_member_who_may_not_deposit_keeps_it(self):
        self.assertEqual((), self.plan(dict(GUILD, member_ranks={"Grug": 3})).moves)

    def test_the_last_free_slot_is_spoken_for_once(self):
        rows = self.rows() + [
            row(item_guid=22, name="Citrine", item_class=3, quality=2, slot=40)
        ]
        members = bank.members_from_rows(rows, ["Grug"])
        plan = bank.plan(
            members, REAL, storage=storage(guild=dict(GUILD, tab_items={0: 97}))
        )
        self.assertEqual(1, len(plan.moves))

    def test_what_the_holders_own_trade_uses_stays(self):
        rows = [
            row(
                item_guid=31,
                name="Silver Ore",
                item_class=7,
                quality=2,
                slot=39,
                count=3,
            )
        ]
        members = bank.members_from_rows(rows, ["Grug"])
        held = {"Grug": {"blacksmithing": 40}}
        plan = bank.plan(
            members,
            bank.family_from_skills(held),
            storage=bank.storage_from(held, guild=GUILD),
        )
        self.assertFalse(any("guild bank" in m.why for m in plan.moves))


class TheBridgeCarriesTheWordToTheSale(unittest.TestCase):
    SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()

    def test_the_bank_plan_is_handed_the_spare_copies(self):
        self.assertIn("spare=_bank_spare(names)", self.SOURCE)

    def test_the_sale_is_handed_the_spare_copies(self):
        self.assertIn(
            "spare=await asyncio.to_thread(_bank_spare, names, True)", self.SOURCE
        )


if __name__ == "__main__":
    unittest.main()
