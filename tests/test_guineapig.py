"""The corps' guinea pigs, and the vial buy they try first (#2398).

Measured on the dev realm on 2026-11-13: the four corps alchemists (Diggo,
Snipp, Lipgloss, Gutsy) sat at Alchemy 1 carrying 100+ Peacebloom and
Silverleaf, because Minor Healing Potion needs an Empty Vial and nothing
bought one for a guild member.

Pure unit tests against guineapig and guildjobs.
"""

import pathlib
import unittest

import guildjobs
import guineapig

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

H, ALC, TAIL, FA = guildjobs.HERBALISM, 171, 197, guildjobs.FIRST_AID
COOK = guildjobs.COOKING
PEACEBLOOM, SILVERLEAF, EMPTY_VIAL = 2447, 765, 3371


def stack(guid, entry, count):
    return guildjobs.Carried(
        guid=guid, entry=entry, count=count, item_class=7, subclass=9, sell_price=5
    )


def member(name, guild="Cave", role=guildjobs.MAINTENANCE, skills=None, **over):
    base = dict(
        name=name,
        guild=guild,
        role=role,
        level=55,
        class_id=3,
        race=3,
        online=True,
        map_id=0,
        x=0.0,
        y=0.0,
        money=50000,
        eligible=True,
        skills=skills or {H: (75, 150), ALC: (1, 75), FA: (40, 75), COOK: (1, 75)},
    )
    base.update(over)
    return guildjobs.Member(**base)


def alchemist(name="Diggo", vials=0, **over):
    carried = [stack(1, PEACEBLOOM, 20), stack(2, SILVERLEAF, 20)]
    if vials:
        carried.append(stack(3, EMPTY_VIAL, vials))
    return member(name, carried=tuple(carried), **over)


class PickingTheGuineaPigs(unittest.TestCase):
    def test_the_highest_skill_maintenance_member_per_trade_and_guild(self):
        members = [
            member("Diggo", skills={ALC: (1, 75)}),
            member("Snipp", skills={ALC: (3, 75)}),
            member("Whakk", skills={TAIL: (50, 150)}),
            member("Nobody", guild="Bonkers", skills={TAIL: (49, 75)}),
        ]
        pigs = guineapig.pick(members)
        self.assertEqual({ALC: "Snipp", TAIL: "Whakk"}, pigs["Cave"])
        self.assertEqual({TAIL: "Nobody"}, pigs["Bonkers"])

    def test_a_tie_goes_to_the_first_name(self):
        pigs = guineapig.pick([member("Snipp"), member("Diggo")])
        self.assertEqual("Diggo", pigs["Cave"][ALC])

    def test_raiders_and_unnatural_members_are_never_picked(self):
        members = [
            member("Bonk", role=guildjobs.RAIDER, skills={ALC: (90, 150)}),
            member("Fresh", eligible=False, skills={ALC: (80, 150)}),
            member("Diggo", skills={ALC: (1, 75)}),
        ]
        self.assertEqual("Diggo", guineapig.pick(members)["Cave"][ALC])

    def test_the_line_names_each_pig_and_each_gap(self):
        members = [member("Diggo", skills={ALC: (1, 75)})]
        (line,) = guineapig.lines(guineapig.pick(members), members)
        self.assertTrue(line.startswith("Cave guinea pigs: Alchemy Diggo 1"), line)
        self.assertIn("nobody in the corps holds Tailoring, Leatherworking", line)


class TheGate(unittest.TestCase):
    def test_a_corps_feature_reaches_only_that_trades_pig(self):
        f = guineapig.VENDOR_REAGENTS
        self.assertTrue(guineapig.allows(f, ALC, frozenset({ALC})))
        self.assertFalse(guineapig.allows(f, ALC, frozenset({TAIL})))
        self.assertFalse(guineapig.allows(f, ALC, frozenset()))

    def test_a_family_feature_reaches_everyone(self):
        stages = {guineapig.VENDOR_REAGENTS: guineapig.FAMILY}
        self.assertTrue(
            guineapig.allows(guineapig.VENDOR_REAGENTS, ALC, frozenset(), stages)
        )

    def test_an_unknown_feature_reaches_nobody(self):
        self.assertFalse(guineapig.allows("nothing", ALC, frozenset({ALC})))

    def test_the_vial_buy_starts_with_the_corps(self):
        self.assertEqual(guineapig.CORPS, guineapig.FEATURES[guineapig.VENDOR_REAGENTS])


class TheVialBuy(unittest.TestCase):
    def test_the_alchemy_pig_with_herbs_and_no_vial_buys_a_batch(self):
        m = alchemist(pig_skills=frozenset({ALC}))
        step = guildjobs.reagent_buy_step(m, 600)
        self.assertEqual("reagent", step.action)
        self.assertTrue(step.walk.command.startswith("walk-to-vendor item:3371"))
        (row,) = step.rows
        self.assertEqual("buy", row.kind)
        self.assertTrue(row.command.startswith("entry:3371 count:10 "), row.command)
        self.assertIn("Empty Vial", step.said)
        self.assertIn("guinea pig", step.said)

    def test_an_alchemist_that_is_not_the_pig_buys_nothing(self):
        self.assertIsNone(guildjobs.reagent_buy_step(alchemist(), 600))

    def test_at_stage_family_every_crafter_buys(self):
        stages = {guineapig.VENDOR_REAGENTS: guineapig.FAMILY}
        self.assertIsNotNone(guildjobs.reagent_buy_step(alchemist(), 600, stages))

    def test_a_vial_in_the_bags_needs_no_buy(self):
        m = alchemist(vials=5, pig_skills=frozenset({ALC}))
        self.assertIsNone(guildjobs.reagent_buy_step(m, 600))

    def test_no_herbs_no_buy(self):
        m = member("Diggo", pig_skills=frozenset({ALC}))
        self.assertIsNone(guildjobs.reagent_buy_step(m, 600))

    def test_a_short_purse_buys_what_it_can_pay_for(self):
        m = alchemist(money=70, pig_skills=frozenset({ALC}))
        step = guildjobs.reagent_buy_step(m, 600)
        self.assertTrue(step.rows[0].command.startswith("entry:3371 count:3 "))

    def test_the_plan_marks_the_pig_and_gives_it_the_buy(self):
        result = guildjobs.plan(
            [alchemist("Diggo"), alchemist("Snipp")],
            masters={"Cave": "Grug"},
        )
        self.assertEqual("Diggo", result.pigs["Cave"][ALC])
        actions = {s.holder: s.action for s in result.steps}
        self.assertEqual("reagent", actions.get("Diggo"))
        self.assertNotEqual("reagent", actions.get("Snipp"))


class TheBridgeLogsThem(unittest.TestCase):
    def test_the_guild_jobs_pass_logs_the_guinea_pigs(self):
        self.assertTrue("guineapig.lines(plan.pigs" in BRIDGE)

    def test_the_image_ships_the_module(self):
        self.assertTrue(
            "guineapig.py" in (HERE / "Dockerfile").read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()
