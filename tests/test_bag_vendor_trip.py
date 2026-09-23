"""The family walks to the nearest vendor that stocks a bag (#206).

Measured on the dev realm 2026-09-22: the second family stood in Ratchet at
vendor 8307, which sells no bags, and logged "no vendor in reach stocks a bag"
every cycle. Jazzik (creature 3498), forty yards away, sells the Small Brown
Pouch (6 slots, 500c) and the Brown Leather Satchel (8 slots, 2500c). The
dungeon coordinator would not open a run while any member had three or fewer
free slots, so the family's first dungeon waited on a pouch nobody went to buy.

Pinned here: the pure trip planner (nearest stocking vendor within the cap that
a buyer can afford, never over combat, a run or a pending campaign bind, and
not repeated once nobody who can afford a bag lacks one), the rows it is read
from, and the bridge wiring (purchase first, then one aim through the town
slot, from npc_vendor and never a hand-written list).
"""

import pathlib
import re
import unittest

import bag_pressure
import jobs

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

RATCHET = (1, -1000.0, -3690.0)
RATCHET_INN = (1, -1046.4, -3664.9)
RAZOR_HILL = (1, -618.5, -4251.7)

# One row per (vendor, bag), shaped like bridge._BAG_VENDOR_SQL's answer from
# where the family stood in Ratchet. Vendor 8307 has no bag rows at all, which
# is the whole of the bug: the counter the family stood at is not in this list.
JAZZIK_ROWS = [
    dict(
        entry=3498,
        name="Jazzik",
        faction=69,
        map_id=1,
        yards=39.0,
        item=4496,
        item_name="Small Brown Pouch",
        slots=6,
        price=500,
    ),
    dict(
        entry=3498,
        name="Jazzik",
        faction=69,
        map_id=1,
        yards=39.0,
        item=4498,
        item_name="Brown Leather Satchel",
        slots=8,
        price=2500,
    ),
]
CROSSROADS_ROWS = [
    dict(
        entry=3487,
        name="Kalyimah Stormcloud",
        faction=126,
        map_id=1,
        yards=309.0,
        item=4496,
        item_name="Small Brown Pouch",
        slots=6,
        price=500,
    ),
]


def buyer(name="Uzza", level=17, money=10913, open_positions=4, free_slots=3):
    """A member standing at vendor 8307: its reach stocks no bag."""
    return bag_pressure.BagBuyer(
        name=name,
        level=level,
        money=money,
        open_positions=open_positions,
        free_slots=free_slots,
        stocks=frozenset({159, 4540}),
    )


def standing(name, at=RATCHET, home=RAZOR_HILL, job="quest", in_combat=False):
    return bag_pressure.Standing(
        name=name,
        map_id=at[0],
        x=at[1],
        y=at[2],
        in_combat=in_combat,
        job=job,
        home_map=home[0] if home else None,
        home_x=home[1] if home else 0.0,
        home_y=home[2] if home else 0.0,
    )


FAMILY = ("Oz", "Uzza", "Zork", "Zrog", "Zug")


def family(**overrides):
    return {n: overrides.get(n, standing(n)) for n in FAMILY}


def trip(buyers=None, rows=None, **kwargs):
    vendors = bag_pressure.bag_vendors_from_rows(JAZZIK_ROWS if rows is None else rows)
    kwargs.setdefault("standing", family())
    kwargs.setdefault("leader", "Zug")
    return bag_pressure.bag_vendor_trip(
        [buyer()] if buyers is None else buyers, vendors, **kwargs
    )


class TheRatchetCase(unittest.TestCase):
    def test_the_family_is_sent_to_jazzik(self):
        got = trip()
        self.assertEqual(got.target, "3498")
        self.assertEqual(got.vendor.name, "Jazzik")
        self.assertEqual(got.buyers, ("Uzza",))
        self.assertEqual(got.why_not, "")

    def test_the_cheapest_bag_there_is_what_the_price_is_judged_on(self):
        got = trip()
        self.assertEqual(got.vendor.offers[0].entry, 4496)
        self.assertIn("Small Brown Pouch", bag_pressure.bag_trip_report(got, "Zug"))
        self.assertIn("creature 3498", bag_pressure.bag_trip_report(got, "Zug"))

    def test_the_nearest_stocking_vendor_wins(self):
        got = trip(rows=CROSSROADS_ROWS + JAZZIK_ROWS)
        self.assertEqual(got.target, "3498")

    def test_the_aim_is_a_travel_target_the_module_reads(self):
        import travel

        self.assertTrue(travel.is_target(trip().target))


class TheCapAndTheMap(unittest.TestCase):
    def test_a_vendor_past_the_cap_is_not_walked_to(self):
        far = [
            dict(r, yards=bag_pressure.BAG_VENDOR_MAX_YARDS + 1) for r in JAZZIK_ROWS
        ]
        got = trip(rows=far)
        self.assertEqual(got.target, "")
        self.assertIn("no vendor within", got.why_not)

    def test_a_vendor_on_another_map_is_not_walked_to(self):
        got = trip(rows=[dict(r, map_id=0) for r in JAZZIK_ROWS])
        self.assertEqual(got.target, "")

    def test_no_vendor_rows_is_no_trip(self):
        got = trip(rows=[])
        self.assertEqual(got.target, "")

    def test_a_leader_already_at_the_vendor_is_not_re_aimed(self):
        got = trip(rows=[dict(r, yards=4.0) for r in JAZZIK_ROWS])
        self.assertEqual(got.target, "")
        self.assertIn("already stands at Jazzik", got.why_not)


class NotRepeatedOnceEveryoneWhoCanAffordOneHasOne(unittest.TestCase):
    def test_nobody_wanting_a_bag_is_no_trip(self):
        self.assertEqual(trip(buyers=[]).target, "")

    def test_a_buyer_who_cannot_keep_the_reserve_is_no_trip(self):
        """Zug, level 20 with 2149 copper, keeps 2000 back: a 500c pouch
        would take him under the floor."""
        got = trip(buyers=[buyer(name="Zug", level=20, money=2149)])
        self.assertEqual(got.target, "")
        self.assertIn("can spare", got.why_not)

    def test_only_the_buyers_who_can_afford_it_are_served(self):
        got = trip(buyers=[buyer(name="Zug", level=20, money=2149), buyer()])
        self.assertEqual(got.buyers, ("Uzza",))

    def test_a_full_backpack_has_nowhere_to_put_the_bag(self):
        self.assertEqual(trip(buyers=[buyer(free_slots=0)]).target, "")

    def test_no_empty_position_is_no_trip(self):
        self.assertEqual(trip(buyers=[buyer(open_positions=0)]).target, "")

    def test_a_buyer_on_another_map_cannot_follow(self):
        got = trip(standing=family(Uzza=standing("Uzza", at=(0, 0.0, 0.0))))
        self.assertEqual(got.target, "")


class NeverOverSomethingMoreImportant(unittest.TestCase):
    def test_not_during_a_dungeon_run(self):
        got = trip(in_run=True)
        self.assertEqual(got.target, "")
        self.assertIn("dungeon run", got.why_not)

    def test_not_while_anybody_is_fighting(self):
        got = trip(standing=family(Oz=standing("Oz", in_combat=True)))
        self.assertEqual(got.target, "")
        self.assertIn("Oz in combat", got.why_not)

    def test_not_while_a_campaign_bind_may_be_pending(self):
        """mod-overseer#583: the leader was walked to the Ratchet inn to bind
        and a vendor aim cancelled the hold. Homes still in Durotar."""
        dungeon = jobs.dungeon_job("wailing")
        got = trip(
            standing={n: standing(n, job=dungeon) for n in FAMILY},
        )
        self.assertEqual(got.target, "")
        self.assertIn("mod-overseer#583", got.why_not)

    def test_once_the_bind_has_landed_here_the_trip_goes(self):
        dungeon = jobs.dungeon_job("wailing")
        got = trip(
            standing={n: standing(n, job=dungeon, home=RATCHET_INN) for n in FAMILY},
        )
        self.assertEqual(got.target, "3498")

    def test_an_unknown_home_on_a_dungeon_job_waits(self):
        got = trip(standing=family(Oz=standing("Oz", job="dungeon", home=None)))
        self.assertEqual(got.target, "")

    def test_a_quest_job_is_not_held_for_a_bind(self):
        self.assertEqual(bag_pressure.bind_pending(family(), "Zug"), ())

    def test_nobody_leads_is_no_trip(self):
        self.assertEqual(trip(leader="").target, "")

    def test_an_unseen_leader_is_no_trip(self):
        got = trip(standing=family(Zug=bag_pressure.Standing(name="Zug")))
        self.assertEqual(got.target, "")


class TheRowsAreReadNotAuthored(unittest.TestCase):
    def test_rows_group_into_one_vendor_with_its_bags_cheapest_first(self):
        got = bag_pressure.bag_vendors_from_rows(list(reversed(JAZZIK_ROWS)))
        self.assertEqual(len(got), 1)
        self.assertEqual([o.entry for o in got[0].offers], [4496, 4498])

    def test_a_broken_row_is_dropped(self):
        got = bag_pressure.bag_vendors_from_rows([dict(entry=3498)] + CROSSROADS_ROWS)
        self.assertEqual([v.entry for v in got], [3487])

    def test_standing_reads_the_snapshot_and_the_homebind(self):
        got = bag_pressure.standing_from_rows(
            [
                dict(
                    name="Zug",
                    map_id=1,
                    pos_x=-535.0,
                    pos_y=-2982.2,
                    in_combat=0,
                    job="quest",
                    home_map=1,
                    home_x=-618.5,
                    home_y=-4251.7,
                ),
                dict(name="Oz", map_id=None, in_combat=None, home_map=None),
            ]
        )
        self.assertEqual(got["Zug"].map_id, 1)
        self.assertFalse(got["Zug"].in_combat)
        self.assertIsNone(got["Oz"].map_id)
        self.assertIsNone(got["Oz"].home_map)

    def test_is_dungeon_job(self):
        self.assertTrue(jobs.is_dungeon_job("dungeon"))
        self.assertTrue(jobs.is_dungeon_job("dungeon:wailing"))
        self.assertFalse(jobs.is_dungeon_job("quest"))
        self.assertFalse(jobs.is_dungeon_job(""))
        self.assertFalse(jobs.is_dungeon_job(None))


def _source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _statements(signature: str) -> str:
    src = _source()
    start = src.index(signature)
    rest = src[start:]
    match = re.search(r"\n {0,4}(async def |def |class )", rest[1:])
    body = rest[: match.start() + 1] if match else rest
    if body.count('"""') >= 2:
        body = body.split('"""', 2)[2]
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )


class TheBridgeWiring(unittest.TestCase):
    def test_purchase_runs_before_the_trip(self):
        body = _statements("    async def _bag_purchase_and_trip(")
        self.assertLess(
            body.index("await self._buy_bags_once(names, auction_too=cohort is None)"),
            body.index("await self._aim_at_bag_vendor(needy, names, cohort)"),
        )

    def test_the_purchase_hands_back_who_still_needs_a_vendor(self):
        body = _statements("    async def _buy_bags_once(")
        self.assertIn(
            "needy = tuple(b for b in everyone if not (b.stocks & bagged))", body
        )
        self.assertIn("return needy", body)

    def test_the_trip_goes_through_the_town_slot_on_the_leader(self):
        body = _statements("    async def _aim_at_bag_vendor(")
        self.assertIn("bag_pressure.bag_vendor_trip(", body)
        self.assertIn("BAGS_CLAIMANT, leader, trip.target", body)
        self.assertIn("self._claim_town_slot(", body)
        self.assertIn("in_run = await self._mid_run(names)", body)
        self.assertNotIn("_write_trade_errand", body)

    def test_the_vendors_come_from_npc_vendor(self):
        src = _source()
        sql = src[src.index("_BAG_VENDOR_SQL = (") :]
        sql = sql[: sql.index("def _fetch_bag_vendors(")]
        self.assertIn("acore_world.npc_vendor", sql)
        self.assertIn("it.class = 1 AND it.subclass = 0", sql)
        self.assertIn("HAVING yards <= %s", sql)

    def test_the_bind_is_read_from_character_homebind(self):
        src = _source()
        sql = src[src.index("_BAG_TRIP_PLACES_SQL = (") :]
        sql = sql[: sql.index("def _fetch_bag_trip_facts(")]
        self.assertIn("character_homebind", sql)
        self.assertIn("in_combat", sql)


if __name__ == "__main__":
    unittest.main()
