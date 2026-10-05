"""Raid seats by pre-raid readiness, not item level (#542, decision #532).

Every test fails without raidgear or the lineup's readiness ordering: the old
code sorted by level and read an item level average.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import armory  # noqa: E402
import gearscore  # noqa: E402
import raidgear  # noqa: E402
import raidlineup  # noqa: E402
from raidlineup import WARRIOR  # noqa: E402

SPEC = "warrior-fury"
STRENGTH = 4
BODY = ("head", "shoulders", "back", "chest", "wrist", "hands", "waist", "legs", "feet")
SLOT_OF = {"wrist": "wrists"}


def _row(entry, strength, **extra):
    out = {
        "entry": entry,
        "item_name": "Item %d" % entry,
        "stat_type1": STRENGTH,
        "stat_value1": strength,
    }
    out.update(extra)
    return out


def _lists():
    """item_template rows for every item the warrior list names, all strong."""
    rows = {}
    for item_id in {i for k in BODY for i in gearscore.slot_list(SPEC, "preraid", k)}:
        rows[item_id] = _row(item_id, 80)
    return rows


ITEM_ROWS = _lists()


def _worn(name, share_best):
    """Rows for `name`: the first `share_best` of the body slots in a listed
    pre-raid piece, the rest in an unlisted weak one."""
    out = []
    for index, key in enumerate(BODY):
        slot = armory.EQUIPPED_SLOTS.index(SLOT_OF.get(key, key))
        if index < share_best:
            entry = gearscore.slot_list(SPEC, "preraid", key)[0]
            stats = 80
        else:
            entry, stats = 900000 + index, 1
        out.append(dict(_row(entry, stats), name=name, slot=slot))
    return out


def _member(name, level=60):
    return {"name": name, "level": level, "class_id": WARRIOR}


class ReadinessIsTheShareOfSlotsAtPreRaidBest(unittest.TestCase):
    def test_a_member_in_pre_raid_best_is_fully_ready(self):
        got = raidgear.readiness_by_name(
            [_member("A")], _worn("A", len(BODY)), ITEM_ROWS
        )
        self.assertGreater(got["A"], 0.5)

    def test_weak_gear_scores_below_the_threshold(self):
        got = raidgear.readiness_by_name([_member("A")], _worn("A", 0), ITEM_ROWS)
        self.assertLess(got["A"], raidgear.READY_SHARE)

    def test_more_pre_raid_pieces_is_more_ready(self):
        few = raidgear.readiness_by_name([_member("A")], _worn("A", 2), ITEM_ROWS)
        many = raidgear.readiness_by_name([_member("A")], _worn("A", 7), ITEM_ROWS)
        self.assertLess(few["A"], many["A"])

    def test_nothing_read_is_none_not_zero(self):
        members = [_member("A"), _member("B")]
        got = raidgear.readiness_by_name(members, _worn("A", 3), {})
        self.assertIsNone(got["A"])
        got = raidgear.readiness_by_name(members, _worn("A", 3), ITEM_ROWS)
        self.assertIsNone(got["B"])

    def test_rows_without_an_entry_are_not_scored(self):
        thin = [{"name": "A", "slot": 0, "item_level": 60}]
        got = raidgear.readiness_by_name([_member("A")], thin, ITEM_ROWS)
        self.assertIsNone(got["A"])

    def test_the_reason_names_the_share_and_the_bar(self):
        self.assertIsNone(raidgear.short_reason(0.5))
        self.assertEqual("pre-raid gear 40%, needs 50%", raidgear.short_reason(0.4))
        self.assertEqual("pre-raid gear not read", raidgear.short_reason(None))


class SeatsFollowReadinessNotLevel(unittest.TestCase):
    def _lineup(self, members, guaranteed=()):
        return raidlineup.build_lineup(
            members,
            guaranteed=guaranteed,
            raiders=5,
            maintenance=0,
            summoners=0,
        )

    def _tank(self, lineup):
        return [
            m["name"]
            for g in lineup["groups"]
            for m in g["members"]
            if m["role"] == "tank"
        ]

    def test_the_readier_warrior_takes_the_one_tank_seat(self):
        # Names sort Aaa first and levels tie; only readiness separates them.
        members = [
            dict(_member("Aaa"), readiness=0.2),
            dict(_member("Bbb"), readiness=0.9),
            dict(_member("Ccc"), readiness=0.5),
        ]
        self.assertEqual(["Bbb"], self._tank(self._lineup(members)))

    def test_readiness_outranks_level(self):
        members = [
            dict(_member("Aaa", 60), readiness=0.1),
            dict(_member("Bbb", 58), readiness=0.8),
        ]
        self.assertEqual(["Bbb"], self._tank(self._lineup(members)))

    def test_the_family_is_still_guaranteed_first(self):
        members = [
            dict(_member("Aaa"), readiness=0.0),
            dict(_member("Bbb"), readiness=0.9),
        ]
        self.assertEqual(["Aaa"], self._tank(self._lineup(members, ["Aaa"])))

    def test_a_roster_nobody_read_orders_by_level_as_before(self):
        members = [_member("Aaa", 50), _member("Bbb", 60), _member("Ccc", 55)]
        self.assertEqual(["Bbb"], self._tank(self._lineup(members)))

    def test_attach_carries_readiness_into_the_placed_raider(self):
        members = raidgear.attach(
            [_member("Aaa"), _member("Bbb")],
            _worn("Aaa", 0) + _worn("Bbb", len(BODY)),
            ITEM_ROWS,
        )
        lineup = self._lineup(members)
        placed = [m for g in lineup["groups"] for m in g["members"]]
        self.assertEqual("Bbb", self._tank(lineup)[0])
        self.assertGreater(
            next(m for m in placed if m["name"] == "Bbb")["readiness"], 0.5
        )


class TheBridgeWritesTheSeatsTheTabsShow(unittest.TestCase):
    def test_both_seat_writers_attach_readiness_before_the_lineup(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "bridge.py"), encoding="utf-8") as fh:
            text = fh.read()
        for name in ("def _write_raid_specs(", "def _drive_raid("):
            body = text[text.index(name) :]
            call = body.index("lineup = raidlineup.build_lineup(members")
            self.assertIn("_with_readiness(", body[:call], name)


if __name__ == "__main__":
    unittest.main()
