"""Raid seats raise their trades at town stops (slice 3 of the raid-seat plan).

READ FROM THE DEV REALM, the 24 hours to 2026-11-15, rows of the guild job pass
by rung (overseer_command rows with a `guildjobs:` source, members in brackets):
supply 1388 [86], pvp 549 [32], sell 448 [60], classquest walks 336 [58], level
325 [67], room 169 [30], collect 141 [31], bag 112 [23], gear 111 [14], farm 74
[21], post 73 [13], craft 54 [6, 34 of them errors], train 1 [1]. The trade
rungs (train, craft) fired for 6 and 1 members out of about 130 because a
raider's ordinary job is the post and the sale, and a rank-up only fired for a
trade already standing AT its ceiling.

THE NEW ORDER, asserted below: class quests, room, bags, upkeep, the early
post and the at-ceiling rank walk come first, as before. Then, for a seat under
level 60, PvP, the mail walk and the walk out of an outgrown zone: levelling is
never displaced. Only then, on a town stop the seat already made (a town row
inside TOWN_STOP_MINUTES), does a raid seat buy the next rank of a trade within
RANK_UP_MARGIN of its ceiling, learn a recipe, and cast what its bags allow.
A level 60 seat has no levelling to protect, so it takes its rank-up before
PvP and may craft without a town stop.

Pure unit tests against guildjobs.plan.
"""

import unittest

import guildjobs
import test_guildlevel_open_quests as fx
from test_guildjobs import stack

FA, H, M = guildjobs.FIRST_AID, guildjobs.HERBALISM, guildjobs.MINING
LINEN = 2589
BONKERS = "Bonkers"
STOP = (guildjobs.Recent("Medic", "sell", 20, "delivered"),)


def raider(name="Medic", **over):
    base = dict(
        name=name,
        guild=BONKERS,
        role=guildjobs.RAIDER,
        level=30,
        class_id=1,
        race=1,
        online=True,
        map_id=0,
        x=-9000.0,
        y=100.0,
        money=5000,
        eligible=True,
        skills={FA: (10, 75), H: (30, 75), M: (30, 75)},
        skills_read=True,
        carried=(stack(1, LINEN, 14, subclass=5),),
        free_slots=8,
        bag_slots=16,
    )
    base.update(over)
    return guildjobs.Member(**base)


def steps(result, name, action):
    return [s for s in result.steps if s.holder == name and s.action == action]


def plan(members, **kw):
    kw.setdefault("masters", {"Cave": "Grug", BONKERS: "Zug"})
    return guildjobs.plan(members, **kw)


class CraftingAtATownStop(unittest.TestCase):
    def test_a_raider_casts_what_its_bags_allow_on_a_town_stop(self):
        result = plan([raider()], recent=STOP, focus={BONKERS: "dungeon"})
        (step,) = steps(result, "Medic", "craft")
        self.assertIn("Linen Bandage", step.said)

    def test_the_same_raider_does_nothing_with_no_town_stop(self):
        result = plan([raider()], focus={BONKERS: "dungeon"})
        self.assertEqual([], steps(result, "Medic", "craft"))

    def test_a_town_stop_that_failed_is_no_stop(self):
        failed = (guildjobs.Recent("Medic", "sell", 20, "error"),)
        result = plan([raider()], recent=failed, focus={BONKERS: "dungeon"})
        self.assertEqual([], steps(result, "Medic", "craft"))

    def test_a_town_stop_long_ago_is_no_stop(self):
        old = (guildjobs.Recent("Medic", "sell", 200, "delivered"),)
        result = plan([raider()], recent=old, focus={BONKERS: "dungeon"})
        self.assertEqual([], steps(result, "Medic", "craft"))

    def test_a_level_60_raider_crafts_without_a_town_stop(self):
        result = plan([raider(level=60)], focus={BONKERS: "dungeon"})
        self.assertEqual(1, len(steps(result, "Medic", "craft")))

    def test_a_craft_waits_out_its_own_cooldown(self):
        rows = STOP + (guildjobs.Recent("Medic", "craft", 5, "delivered"),)
        result = plan([raider()], recent=rows, focus={BONKERS: "dungeon"})
        self.assertEqual([], steps(result, "Medic", "craft"))

    def test_a_seat_in_a_group_is_not_walked_to_cast(self):
        result = plan([raider(follows=True)], recent=STOP)
        self.assertEqual([], steps(result, "Medic", "craft"))


class RankUpsAtATownStop(unittest.TestCase):
    NEAR_CAP = {H: (72, 75), M: (30, 75), FA: (10, 75)}

    def test_a_trade_within_the_margin_is_ranked_on_a_town_stop(self):
        m = raider(skills=self.NEAR_CAP, carried=())
        result = plan([m], recent=STOP, focus={BONKERS: "dungeon"})
        (step,) = [s for s in steps(result, "Medic", "train") if s.key == H]
        self.assertIn("up to 150", step.said)

    def test_the_same_trade_is_left_alone_with_no_town_stop(self):
        m = raider(skills=self.NEAR_CAP, carried=())
        result = plan([m], focus={BONKERS: "dungeon"})
        self.assertEqual([], [s for s in steps(result, "Medic", "train") if s.key == H])

    def test_a_trade_at_its_ceiling_is_still_ranked_with_no_town_stop(self):
        m = raider(skills={H: (75, 75), M: (30, 75)}, carried=())
        result = plan([m], focus={BONKERS: "dungeon"})
        self.assertEqual(
            1, len([s for s in steps(result, "Medic", "train") if s.key == H])
        )

    def test_a_trade_short_of_the_margin_is_not_ranked(self):
        m = raider(skills={H: (60, 75), M: (30, 75)}, carried=())
        result = plan([m], recent=STOP, focus={BONKERS: "dungeon"})
        self.assertEqual([], steps(result, "Medic", "train"))

    def test_a_short_purse_saves_and_says_so(self):
        m = raider(skills=self.NEAR_CAP, carried=(), money=100)
        result = plan([m], recent=STOP, focus={BONKERS: "dungeon"})
        self.assertEqual([], steps(result, "Medic", "train"))
        self.assertTrue(any("saves for" in n for n in result.notes), result.notes)

    def test_a_level_60_seat_ranks_a_trade_within_the_margin_before_pvp(self):
        import pvpgear

        a = pvpgear.Aim("Medic", BONKERS, 60, 19325, "Bow", 400, 0, pvpgear.AV)
        pvp = {"Medic": (a, pvpgear.Move(pvpgear.BUY, ""))}
        m = raider(
            level=60, skills={H: (222, 225), M: (30, 75)}, money=90000, carried=()
        )
        result = plan([m], recent=STOP, pvp=pvp, focus={BONKERS: "dungeon"})
        self.assertEqual(
            1, len([s for s in steps(result, "Medic", "train") if s.key == H])
        )
        self.assertFalse(any(s.action == "pvp" for s in result.steps))

    def test_a_seat_under_60_keeps_its_pvp_ahead_of_a_margin_rank(self):
        import pvpgear

        a = pvpgear.Aim("Medic", BONKERS, 30, 19325, "Bow", 400, 0, pvpgear.AV)
        pvp = {"Medic": (a, pvpgear.Move(pvpgear.BUY, ""))}
        m = raider(skills=self.NEAR_CAP, carried=())
        result = plan([m], recent=STOP, pvp=pvp, focus={BONKERS: "dungeon"})
        self.assertTrue(any(s.action == "pvp" for s in result.steps))
        self.assertEqual([], [s for s in steps(result, "Medic", "train") if s.key == H])


class LevellingIsNeverDisplaced(unittest.TestCase):
    def levelling(self, outgrown):
        return fx.member(
            "Tugga",
            guild=BONKERS,
            skills={FA: (10, 75), H: (30, 75), M: (30, 75)},
            skills_read=True,
            carried=(stack(1, LINEN, 14, subclass=5),),
            free_slots=8,
            bag_slots=16,
            # Unread rewards judge the zone by its band alone: Hillsbrad fits 26.
            rewarded=fx.done_in(fx.HILLSBRAD) if outgrown else None,
        )

    def run_plan(self, m):
        stop = (guildjobs.Recent("Tugga", "sell", 20, "delivered"),)
        return guildjobs.plan(
            [m],
            masters={BONKERS: "Zug"},
            leveling=fx.WORLD,
            recent=stop,
            focus={BONKERS: "dungeon"},
        )

    def test_a_seat_that_has_outgrown_its_zone_walks_to_level_not_to_craft(self):
        result = self.run_plan(self.levelling(True))
        self.assertEqual(1, len(steps(result, "Tugga", guildjobs.guildlevel.ACTION)))
        self.assertEqual([], steps(result, "Tugga", "craft"))

    def test_a_seat_with_quests_left_here_crafts_on_its_town_stop(self):
        result = self.run_plan(self.levelling(False))
        self.assertEqual([], steps(result, "Tugga", guildjobs.guildlevel.ACTION))
        self.assertEqual(1, len(steps(result, "Tugga", "craft")))


class WhatABagKeepsForItsCasts(unittest.TestCase):
    def test_a_raider_keeps_one_batch_of_cloth_and_posts_the_rest(self):
        cloth = stack(1, LINEN, 40, subclass=5)
        m = raider(carried=(cloth,))
        kept = guildjobs.craft_keep(m)
        self.assertEqual(guildjobs.CRAFT_BATCH, kept[LINEN])
        posted = guildjobs.postable(m, None)
        self.assertEqual([], [c for c in posted if int(c.guid) == 1])

    def test_a_raider_with_no_crafting_trade_keeps_nothing_back(self):
        m = raider(skills={H: (30, 75)}, carried=(stack(1, LINEN, 40, subclass=5),))
        self.assertEqual({}, guildjobs.craft_keep(m))


if __name__ == "__main__":
    unittest.main()
