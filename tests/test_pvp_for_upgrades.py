"""PvP for upgrades (#589): a member whose next upgrade is PvP gear queues the
battleground that earns it, grinds honor, and buys the item at the vendor.

Decided in #530: PvP is for gear, mainly at 60; below 60 only for a strong
upgrade; honor goes on the highest-scoring PvP item for the member's spec. These
pin the pure decisions in pvpgear.py (who queues, which battleground, when to
stop and buy), the guild job steps they become, and the bridge wiring as source.
"""

import math
import pathlib
import unittest

import guildjobs
import guildrun
import guildsocial
import pvpgear

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")

ROGUE, HUMAN, ORC = 4, 1, 2
# The rogue's pre-raid list names this ring (data/bis/rogue-dps.json).
LIST_RING = 18500
DON_JULIOS_BAND = 19325
STORMPIKE, FROSTWOLF, LEGACY_ALLIANCE = 13216, 13218, 12785


def ring(entry, agility, name="Ring", required=0):
    return {
        "Item": entry,
        "item_name": name,
        "item_level": 60,
        "required_level": required,
        "allowable_class": -1,
        "class": 4,
        "subclass": 0,
        "inventory_type": 11,
        "stat_type1": 3,
        "stat_value1": agility,
    }


def member_row(name="Auren", level=60, honor=0, race=HUMAN, guild="Cave"):
    return {
        "name": name,
        "guild_name": guild,
        "level": level,
        "class_id": ROGUE,
        "race": race,
        "honor": honor,
        "talent_spells": None,
    }


def worn_rings(name, agility):
    return [
        dict(
            ring(1000 + slot, agility, "Worn ring"),
            name=name,
            slot=slot,
            entry=1000 + slot,
        )
        for slot in (10, 11)
    ]


def offer(entry=DON_JULIOS_BAND, agility=15, vendor=STORMPIKE, honor=5000, required=60):
    return pvpgear.Offer(
        entry, vendor, honor, ring(entry, agility, "Don Julio's Band", required)
    )


def seekers(rows, worn_agility, list_agility, offers):
    worn = [w for r in rows for w in worn_rings(r["name"], worn_agility)]
    gear = guildsocial.gear_by_name(rows, worn, [])
    lists = {LIST_RING: ring(LIST_RING, list_agility, "Listed ring")}
    return pvpgear.seekers_from_rows(rows, gear, lists, offers)


class WhoQueues(unittest.TestCase):
    """A member queues only when its next upgrade by the gear scorer is PvP."""

    def test_a_pvp_ring_that_beats_the_list_is_the_next_upgrade(self):
        (s,) = seekers([member_row()], 5, 8, [offer()])
        self.assertTrue(s.upgrade.pvp)
        self.assertEqual(DON_JULIOS_BAND, s.upgrade.entry)
        self.assertIn("Auren", pvpgear.plan_aims([s]))

    def test_a_listed_ring_that_beats_it_is_not_pvp(self):
        (s,) = seekers([member_row()], 5, 30, [offer()])
        self.assertEqual(LIST_RING, s.upgrade.entry)
        self.assertFalse(s.upgrade.pvp)
        self.assertEqual({}, pvpgear.plan_aims([s]))

    def test_nothing_better_than_what_is_worn_sends_nobody(self):
        (s,) = seekers([member_row()], 40, 8, [offer()])
        self.assertIsNone(s.upgrade)
        self.assertEqual({}, pvpgear.plan_aims([s]))

    def test_the_other_sides_vendor_is_never_its_upgrade(self):
        (s,) = seekers([member_row(race=HUMAN)], 5, 8, [offer(vendor=FROSTWOLF)])
        self.assertFalse(s.upgrade.pvp)

    def test_at_sixty_a_modest_gain_is_enough(self):
        (s,) = seekers([member_row(level=60)], 12, 8, [offer(agility=15)])
        self.assertLess(s.upgrade.share, pvpgear.STRONG_BELOW_CAP)
        self.assertIn("Auren", pvpgear.plan_aims([s]))

    def test_below_sixty_only_a_strong_upgrade_queues(self):
        weak = offer(agility=15, required=55)
        (s,) = seekers([member_row(level=58)], 12, 8, [weak])
        self.assertTrue(s.upgrade.pvp)
        self.assertEqual({}, pvpgear.plan_aims([s]))
        strong = offer(agility=30, required=55)
        (s,) = seekers([member_row(level=58)], 12, 8, [strong])
        self.assertGreaterEqual(s.upgrade.share, pvpgear.STRONG_BELOW_CAP)
        self.assertIn("Auren", pvpgear.plan_aims([s]))

    def test_an_item_above_its_level_is_not_its_upgrade(self):
        found = seekers(
            [member_row(level=58)],
            5,
            6,
            [offer(required=60), offer(19326, 1, required=55)],
        )
        self.assertEqual([LIST_RING], [s.upgrade.entry for s in found])
        self.assertEqual({}, pvpgear.plan_aims(found))

    def test_an_empty_slot_is_always_strong(self):
        rows = [member_row(level=55)]
        gear = guildsocial.gear_by_name(rows, [], [])
        (s,) = pvpgear.seekers_from_rows(rows, gear, {}, [offer(required=55)])
        self.assertEqual(math.inf, s.upgrade.share)
        self.assertIn("Auren", pvpgear.plan_aims([s]))


class WhichBattleground(unittest.TestCase):
    def test_a_supply_officers_item_is_earned_in_its_battleground(self):
        self.assertEqual(
            "av", pvpgear.battleground_for(offer(vendor=STORMPIKE), 60).key
        )
        self.assertEqual("wsg", pvpgear.battleground_for(offer(vendor=14753), 60).key)
        self.assertEqual("ab", pvpgear.battleground_for(offer(vendor=15127), 60).key)

    def test_and_not_below_that_battlegrounds_floor(self):
        self.assertIsNone(pvpgear.battleground_for(offer(vendor=STORMPIKE), 50))

    def test_any_battleground_pays_a_rank_quartermaster(self):
        legacy = offer(vendor=LEGACY_ALLIANCE)
        self.assertEqual("av", pvpgear.battleground_for(legacy, 60).key)
        self.assertEqual("ab", pvpgear.battleground_for(legacy, 50).key)
        self.assertEqual("wsg", pvpgear.battleground_for(legacy, 60, follow="wsg").key)

    def test_guildmates_after_honor_queue_the_same_battleground(self):
        first = pvpgear.Seeker(
            "Auren",
            "Cave",
            60,
            0,
            pvpgear.Upgrade(1, "x", 5.0, 1.0, offer(vendor=14753)),
        )
        second = pvpgear.Seeker(
            "Bel",
            "Cave",
            60,
            0,
            pvpgear.Upgrade(2, "y", 5.0, 1.0, offer(vendor=LEGACY_ALLIANCE)),
        )
        aims = pvpgear.plan_aims([second, first])
        self.assertEqual("wsg", aims["Auren"].battleground.key)
        self.assertEqual("wsg", aims["Bel"].battleground.key)

    def test_the_battleground_maps_are_the_stranded_checks(self):
        self.assertEqual(guildrun.BATTLEGROUND_MAPS, pvpgear.BATTLEGROUND_MAPS)


def aim(held=0, honor=5000):
    return pvpgear.Aim(
        "Auren",
        "Cave",
        60,
        DON_JULIOS_BAND,
        "Don Julio's Band",
        honor,
        held,
        pvpgear.AV,
    )


def recent(age, status="delivered", action="pvp"):
    return (guildjobs.Recent("Auren", action, age, status),)


class WhenToStopAndBuy(unittest.TestCase):
    def test_short_of_honor_it_queues(self):
        move = pvpgear.next_move(aim(held=1200), 0, False, ())
        self.assertEqual(pvpgear.QUEUE, move.kind)
        self.assertEqual("bg-queue av", pvpgear.queue_command(aim()))

    def test_with_the_honor_it_stops_and_buys_under_an_honor_ceiling(self):
        move = pvpgear.next_move(aim(held=5000), 0, False, recent(2))
        self.assertEqual(pvpgear.BUY, move.kind)
        self.assertEqual("entry:19325 count:1 honor:5000", pvpgear.buy_command(aim()))

    def test_inside_a_battleground_it_plays(self):
        self.assertEqual(
            pvpgear.INSIDE, pvpgear.next_move(aim(held=5000), 30, False, ()).kind
        )

    def test_a_bought_item_in_the_bags_is_not_bought_again(self):
        self.assertEqual(
            pvpgear.CARRIED, pvpgear.next_move(aim(held=9000), 0, True, ()).kind
        )

    def test_a_fresh_queue_waits_for_its_battle(self):
        self.assertEqual(
            pvpgear.WAITING, pvpgear.next_move(aim(), 0, False, recent(5)).kind
        )

    def test_a_queue_that_failed_or_went_stale_is_asked_again(self):
        self.assertEqual(
            pvpgear.QUEUE, pvpgear.next_move(aim(), 0, False, recent(5, "error")).kind
        )
        self.assertEqual(
            pvpgear.QUEUE,
            pvpgear.next_move(aim(), 0, False, recent(pvpgear.QUEUE_MINUTES)).kind,
        )


def job_member(**kw):
    base = dict(
        name="Auren", guild="Cave", role=guildjobs.RAIDER, level=60, class_id=ROGUE,
        online=True, map_id=0, x=0.0, y=0.0, money=50000, eligible=True,
    )  # fmt: skip
    base.update(kw)
    return guildjobs.Member(**base)


def pvp_for(held=0, map_id=0, carried=False, rows=()):
    a = aim(held=held)
    return {"Auren": (a, pvpgear.next_move(a, map_id, carried, rows))}


class TheJobStep(unittest.TestCase):
    def test_a_queue_is_one_guild_row(self):
        plan = guildjobs.plan([job_member()], pvp=pvp_for())
        (step,) = plan.steps
        self.assertEqual("pvp", step.action)
        self.assertIsNone(step.walk)
        self.assertEqual(
            [("guild", "bg-queue av", "guildjobs:pvp:Auren")],
            [(r.kind, r.command, r.source) for r in step.rows],
        )

    def test_a_buy_walks_to_the_vendor_then_spends_honor(self):
        (step,) = guildjobs.plan([job_member()], pvp=pvp_for(held=6000)).steps
        self.assertEqual("walk-to-vendor item:19325", step.walk.command)
        self.assertEqual(
            ("buy", "entry:19325 count:1 honor:5000"),
            (step.rows[-1].kind, step.rows[-1].command),
        )

    def test_waiting_in_the_queue_or_playing_holds_every_other_job(self):
        for pvp in (pvp_for(rows=recent(3)), pvp_for(map_id=489)):
            plan = guildjobs.plan([job_member()], pvp=pvp)
            self.assertEqual((), plan.steps)
            self.assertIn("PvP for Don Julio's Band", plan.lines["Auren"])

    def test_a_failed_queue_waits_out_the_cooldown_at_its_ordinary_job(self):
        plan = guildjobs.plan(
            [job_member()],
            pvp=pvp_for(rows=recent(3, "error")),
            recent=recent(3, "error"),
        )
        self.assertFalse(any(s.action == "pvp" for s in plan.steps))
        self.assertNotIn("PvP for", plan.lines["Auren"])

    def test_a_member_not_yet_natural_plays_no_pvp(self):
        plan = guildjobs.plan([job_member(eligible=False)], pvp=pvp_for())
        self.assertEqual((), plan.steps)


class GuildChat(unittest.TestCase):
    def test_the_first_asks_and_a_guildmate_answers(self):
        a = aim()
        b = pvpgear.Aim(
            "Bel", "Cave", 60, 19325, "Don Julio's Band", 5000, 0, pvpgear.AV
        )
        q = pvpgear.Move(pvpgear.QUEUE, "")
        lines = dict(
            pvpgear.chat_lines({"Auren": q, "Bel": q}, {"Auren": a, "Bel": b}, ())
        )
        self.assertTrue(
            any(w in lines["Auren"] for w in ("anyone?", "Anyone", "come along"))
        )
        self.assertIn("AV", lines["Bel"])
        self.assertTrue(lines["Bel"].startswith(("I'm in", "Same here", "Count me in")))

    def test_a_member_already_queueing_says_nothing_new(self):
        q = pvpgear.Move(pvpgear.QUEUE, "")
        self.assertEqual(
            [], pvpgear.chat_lines({"Auren": q}, {"Auren": aim()}, recent(20))
        )

    def test_lines_are_ascii(self):
        for text in pvpgear._ASK + pvpgear._JOIN + pvpgear._BOUGHT:
            self.assertTrue(text.isascii(), text)


class TheStock(unittest.TestCase):
    COSTS = {489: {"honor": 5000, "arena": 0, "items": []},
             65: {"honor": 0, "arena": 1000, "items": []},
             9: {"honor": 1000, "arena": 0, "items": [(20560, 3)]}}  # fmt: skip

    def test_only_honor_priced_lines_of_known_vendors(self):
        rows = [
            dict(ring(19325, 15), vendor=STORMPIKE, extended_cost=489),
            dict(ring(27830, 15), vendor=STORMPIKE, extended_cost=65),
            dict(ring(19510, 15), vendor=14753, extended_cost=9),
            dict(ring(19326, 15), vendor=99999, extended_cost=489),
        ]
        offers = pvpgear.offers_from_rows(rows, self.COSTS)
        self.assertEqual(
            [(19325, STORMPIKE, 5000)], [(o.entry, o.vendor, o.honor) for o in offers]
        )
        self.assertEqual("av", offers[0].battleground)


class NotStranded(unittest.TestCase):
    def test_a_member_in_a_battleground_is_not_hearthed_out(self):
        for map_id in (30, 489, 529):
            member = guildrun.Member("Auren", "Cave", 60, ROGUE, map_id=map_id)
            self.assertFalse(guildrun.left_inside(member))
            self.assertFalse(guildrun.stranded(member, "Alliance"))
        self.assertTrue(
            guildrun.left_inside(guildrun.Member("Auren", "Cave", 30, ROGUE, map_id=36))
        )


class TheWiring(unittest.TestCase):
    def test_off_unless_switched_on(self):
        self.assertFalse(pvpgear.enabled({}))
        self.assertTrue(pvpgear.enabled({"PVP_FOR_UPGRADES": "1"}))

    def test_the_bridge_plans_says_and_holds(self):
        self.assertIn('pvp=await self._job_pvp_moves(members, facts["recent"])', BRIDGE)
        self.assertIn('await self._say_pvp_lines(plan, facts["recent"])', BRIDGE)
        self.assertIn("guildsocial.SOURCE))", BRIDGE)
        self.assertIn('getattr(self, "_pvp_held", {}).items() if held}', BRIDGE)

    def test_the_image_ships_the_module(self):
        self.assertIn("pvpgear.py", DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
