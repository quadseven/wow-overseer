"""The tidy pass puts carried gear on its way, and reads it back (tidy order).

Measured on the dev realm on 2026-09-27: the level 38 warrior carried a
leather kilt made for the family rogue, an idol no member can use, five rings
nothing ever tried on, and a druid's relic, while every existing pass kept
them. Pinned here on the warrior's own bag rows: who each piece is for, which
rings he tries on, and what a finished row is reported as. The bridge pass is
loaded out of bridge.py and run on fakes; nothing touches a database.
"""

import asyncio
import unittest

from test_family_economy_parity import (  # noqa: F401 - also sets up the pymysql stub
    ALLIANCE,
    FAKE_ASYNCIO,
    HELPERS,
    _base,
    _load,
    _Log,
    _source,
)

import gear  # noqa: E402
import tidy  # noqa: E402

WARRIOR, PALADIN, ROGUE, PRIEST, MAGE, DRUID = 1, 2, 4, 5, 8, 11

# The first family as measured: class and level.
FAMILY = {
    "Grug": tidy.Member("Grug", WARRIOR, 38),
    "Grog": tidy.Member("Grog", PALADIN, 36),
    "Bork": tidy.Member("Bork", ROGUE, 35),
    "Ugga": tidy.Member("Ugga", PRIEST, 35),
    "Og": tidy.Member("Og", MAGE, 35),
}


def row(
    guid,
    name,
    item_class,
    subclass,
    invtype,
    required,
    holder="Grug",
    flags=0,
    allowable=-1,
    entry=None,
    quality=2,
):
    return {
        "holder": holder,
        "item_guid": guid,
        "entry": entry or guid,
        "name": name,
        "quality": quality,
        "item_level": required + 5,
        "required_level": required,
        "allowable_class": allowable,
        "inventory_type": invtype,
        "item_class": item_class,
        "item_subclass": subclass,
        "instance_flags": flags,
    }


# The warrior's own carried pieces, class/subclass/InventoryType/RequiredLevel
# as item_template has them.
KILT = row(101, "Jinxed Hoodoo Kilt", 4, 2, 7, 44)  # leather legs
HYDRALICK = row(102, "Hydralick Armor", 4, 4, 5, 49)  # plate chest
WINDRUNNER = row(103, "Windrunner Legguards", 4, 3, 7, 51)  # mail legs
IDOL = row(104, "Idol of the Moon", 4, 8, 28, 60, allowable=32767)
COWL = row(105, "Twilight Cultist Cowl", 4, 1, 1, 60, holder="Grog", allowable=32767)
BOUND_KILT = row(106, "Jinxed Hoodoo Kilt", 4, 2, 7, 44, flags=1, entry=9474)
MEADOW = row(201, "Meadow Ring", 4, 0, 11, 17, entry=12006)
BLOOD = row(202, "Blood Ring", 4, 0, 11, 19, entry=4998)
HEART = row(203, "Shriveled Heart", 4, 0, 2, 40, entry=9243)

NOBODY = {g: gear.NOBODY for g in (101, 102, 103, 105, 106)}
NOBODY[104] = gear.UNJUDGEABLE


class EachPieceIsForTheMemberItSuits(unittest.TestCase):
    def test_a_leather_kilt_goes_to_the_rogue_not_the_plate_warrior(self):
        owner, why = tidy.future_owner(KILT, FAMILY)
        self.assertEqual("Bork", owner)
        self.assertIn("level 44", why)

    def test_a_plate_chest_stays_with_the_warrior_who_wears_plate_at_49(self):
        self.assertEqual("Grug", tidy.future_owner(HYDRALICK, FAMILY)[0])

    def test_mail_nobody_wears_natively_stays_with_its_holder(self):
        # Warrior and paladin both wear plate by 51; neither is a better home.
        self.assertEqual("Grug", tidy.future_owner(WINDRUNNER, FAMILY)[0])

    def test_an_idol_with_no_druid_in_the_family_is_nobodys(self):
        self.assertEqual("", tidy.future_owner(IDOL, FAMILY)[0])

    def test_an_idol_is_the_druids_when_there_is_one(self):
        family = dict(FAMILY, Zork=tidy.Member("Zork", DRUID, 50))
        self.assertEqual("Zork", tidy.future_owner(IDOL, family)[0])

    def test_a_cloth_cowl_goes_to_a_cloth_wearer(self):
        self.assertIn(tidy.future_owner(COWL, FAMILY)[0], ("Og", "Ugga"))

    def test_a_piece_too_far_ahead_is_nobodys(self):
        self.assertEqual("", tidy.future_owner(COWL, FAMILY, horizon=10)[0])


class OnlyTheUnclaimedMove(unittest.TestCase):
    def grants(self, rows, claims=None):
        return tidy.hand_ons(rows, FAMILY, NOBODY if claims is None else claims)

    def test_the_warriors_bags_hand_on_exactly_the_kilt(self):
        grants = self.grants([KILT, HYDRALICK, WINDRUNNER, IDOL, MEADOW])
        self.assertEqual(
            [(101, "Grug", "Bork")], [(g.guid, g.holder, g.taker) for g in grants]
        )
        self.assertEqual("guid:101", grants[0].command)

    def test_a_piece_somebody_wears_now_is_the_gear_pass_s(self):
        self.assertEqual([], self.grants([KILT], {101: "Bork"}))

    def test_a_soulbound_piece_never_moves(self):
        self.assertEqual([], self.grants([BOUND_KILT]))

    def test_the_cowl_leaves_the_paladin(self):
        grants = self.grants([COWL])
        self.assertEqual(1, len(grants))
        self.assertEqual("Grog", grants[0].holder)


class ATunicTheBotDeclinedGoesToItsWearer(unittest.TestCase):
    TUNIC = row(107, "Dervish Tunic", 4, 2, 5, 25, entry=6603)
    HISTORY = [
        {"target_name": "Grug", "command": "e Hitem:6603:0", "status": "delivered"}
    ] * 3

    def test_three_declines_hand_the_leather_tunic_to_the_rogue(self):
        declined = tidy.declined_equips(self.HISTORY)
        self.assertEqual(frozenset({("Grug", 6603)}), declined)
        grants = tidy.hand_ons([self.TUNIC], FAMILY, {107: "Grug"}, declined=declined)
        self.assertEqual([("Grug", "Bork")], [(g.holder, g.taker) for g in grants])

    def test_without_the_declines_the_holder_keeps_its_claim(self):
        self.assertEqual([], tidy.hand_ons([self.TUNIC], FAMILY, {107: "Grug"}))

    def test_pending_rows_are_not_declines(self):
        history = [dict(r, status="pending") for r in self.HISTORY]
        self.assertEqual(frozenset(), tidy.declined_equips(history))


class RingsAreTriedOn(unittest.TestCase):
    WORN = {"Grug": {10: 1076, 11: 4998}}

    def test_a_ring_he_does_not_wear_is_tried_on_by_entry(self):
        tries = tidy.try_ons([MEADOW, BLOOD], FAMILY, self.WORN)
        self.assertEqual(["e Hitem:12006:0"], [t.command for t in tries])

    def test_a_copy_of_a_worn_ring_is_not_tried(self):
        self.assertEqual([], tidy.try_ons([BLOOD], FAMILY, self.WORN))

    def test_a_necklace_above_his_level_is_not_tried(self):
        self.assertEqual([], tidy.try_ons([HEART], FAMILY, self.WORN))

    def test_a_necklace_goes_only_into_an_empty_neck(self):
        low = dict(HEART, required_level=30)
        self.assertEqual(1, len(tidy.try_ons([low], FAMILY, self.WORN)))
        worn = {"Grug": {1: 9999}}
        self.assertEqual([], tidy.try_ons([low], FAMILY, worn))

    def test_two_copies_are_one_try(self):
        again = dict(MEADOW, item_guid=299)
        self.assertEqual(1, len(tidy.try_ons([MEADOW, again], FAMILY, self.WORN)))


class AFinishedRowIsReadBack(unittest.TestCase):
    HAND = {
        "source": tidy.SOURCE_HANDON,
        "target_name": "Grug",
        "target_arg": "Bork",
        "status": "delivered",
        "name": "Kilt",
    }
    TRY = {
        "source": tidy.SOURCE_TRYON,
        "target_name": "Grug",
        "status": "delivered",
        "name": "Meadow Ring",
    }

    def test_delivered_is_not_moved_until_the_receiver_holds_it(self):
        self.assertEqual(tidy.WAITING, tidy.settle(self.HAND, {"owner": "Grug"})[0])
        self.assertEqual(tidy.MOVED, tidy.settle(self.HAND, {"owner": "Bork"})[0])

    def test_a_letter_counts_once_it_is_the_receivers(self):
        outcome, said = tidy.settle(self.HAND, {"owner": "Bork", "mail": True})
        self.assertEqual(tidy.MOVED, outcome)
        self.assertIn("mailbox", said)

    def test_a_pending_row_waits(self):
        self.assertEqual(
            tidy.WAITING, tidy.settle(dict(self.HAND, status="pending"), None)[0]
        )

    def test_an_error_is_reported_as_refused(self):
        outcome, said = tidy.settle(
            dict(self.HAND, status="error", detail="receiver bags are full"), None
        )
        self.assertEqual(tidy.REFUSED, outcome)
        self.assertIn("receiver bags are full", said)

    def test_a_try_on_is_worn_or_kept(self):
        self.assertEqual(
            tidy.WORN, tidy.settle(self.TRY, {"owner": "Grug", "worn": True})[0]
        )
        self.assertEqual(
            tidy.KEPT, tidy.settle(self.TRY, {"owner": "Grug", "worn": False})[0]
        )

    def test_guid_of_reads_both_verbs(self):
        self.assertEqual(101, tidy.guid_of("guid:101"))
        self.assertEqual(101, tidy.guid_of("send item:101 subject:Kilt"))
        self.assertEqual(0, tidy.guid_of("e Hitem:12006:0"))


# --- the bridge pass, on fakes --------------------------------------------


class _Self:
    async def _tidy_settle(self, names):
        return None


def _run_pass(world, standing_together=True):
    log = _Log()
    ns = _base(world)
    worn_rows = [
        {"name": m.name, "class_id": m.class_id, "level": m.level}
        for m in FAMILY.values()
    ]
    ns.update(
        {
            "log": log,
            "tidy": tidy,
            "bag_pressure": type(
                "BP",
                (),
                {"family_claimants": staticmethod(lambda g, w, n: dict(NOBODY))},
            ),
            "gear": gear,
            "TIDY_MAX_ROWS": 3,
            "TIDY_FUTURE_LEVELS": 25,
            "TIDY_RETRY_HOURS": 24,
            "_fetch_surplus_gear": lambda names: [KILT, HYDRALICK, IDOL, MEADOW],
            "_fetch_family_equipped": lambda names: worn_rows,
            "_fetch_worn_entries": lambda names: {"Grug": {10: 1076, 11: 4998}},
            "_equip_history": lambda hours, minutes: [],
            "EQUIP_MEMORY_HOURS": 24,
            "EQUIP_RETRY_MINUTES": 30,
            "_recent_tidy_keys": lambda hours: world.get("seen", set()),
            "_fetch_positions": lambda names: {
                n: {
                    "map_id": 0,
                    "pos_x": 0.0 if standing_together else i * 500.0,
                    "pos_y": 0.0,
                    "pos_z": 0.0,
                }
                for i, n in enumerate(names)
            },
            "_fetch_free_slots": lambda names: {n: 10 for n in names},
            "_holders_at_mailbox": lambda holders, positions: set(),
            "_insert_tidy_try_on": lambda t: (
                world.setdefault("tries", []).append(t.command) or 1
            ),
            "_insert_gear_handoff": lambda g, source: (
                world.setdefault("hands", []).append(
                    (g.holder, g.taker, g.verb, g.command, source)
                )
                or 1
            ),
        }
    )
    _load(HELPERS + ["_tidy_once"], ns)
    asyncio.run(ns["_tidy_once"](_Self()))
    return world, log


class ThePassWritesWhatTidyDecides(unittest.TestCase):
    def test_the_warrior_tries_on_a_ring_and_hands_the_kilt_to_the_rogue(self):
        world, log = _run_pass({})
        self.assertEqual(["e Hitem:12006:0"], world["tries"])
        self.assertEqual(1, len(world["hands"]))
        holder, taker, verb, command, source = world["hands"][0]
        self.assertEqual(
            ("Grug", "Bork", "guid:101", tidy.SOURCE_HANDON),
            (holder, taker, command, source),
        )
        self.assertIn(verb, ("trade", "give"))

    def test_a_row_asked_inside_the_window_is_not_asked_again(self):
        seen = {("Grug", "", "e Hitem:12006:0"), ("Grug", "Bork", "guid:101")}
        world, _ = _run_pass({"seen": seen})
        self.assertNotIn("tries", world)
        self.assertNotIn("hands", world)

    def test_apart_and_not_at_a_mailbox_the_kilt_waits(self):
        world, log = _run_pass({}, standing_together=False)
        self.assertNotIn("hands", world)
        self.assertTrue(any("waiting" in line for line in log.lines))


class TheLoopServesEveryFamily(unittest.TestCase):
    def test_the_loop_runs_for_this_family_and_every_other(self):
        body = _source("_tidy_loop")
        self.assertIn("await self._tidy_once()", body)
        self.assertIn('await self._for_other_families("tidy", self._tidy_once)', body)

    def test_the_loop_is_started(self):
        import pathlib

        text = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(2, text.count("                self._tidy_loop,\n"))

    def test_the_image_ships_the_module(self):
        import pathlib

        docker = (
            pathlib.Path(__file__).resolve().parent.parent / "Dockerfile"
        ).read_text(encoding="utf-8")
        self.assertIn(" tidy.py ", docker)


if __name__ == "__main__":
    unittest.main()
