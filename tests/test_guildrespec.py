"""A guild short of tanks or healers grows them at the trainer (#580).

guildrespec.py counts, per guild and five-level band, the members whose spent
talents play a tank or healer seat (guildrun.Member.plays), and when a band is
short picks a member whose class can fill the seat to say so in guild chat,
pay its trainer for a reset and go that tree. These pin the count, the pick,
the fee, the damage cap, what is already on its way, and the bridge wiring.
"""

import ast
import contextlib
import json
import pathlib
import types
import unittest

import guildrespec
import guildrun
import raidrun

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

WARRIOR, PALADIN, ROGUE, PRIEST, SHAMAN, MAGE, WARLOCK, DRUID = 1, 2, 4, 5, 7, 8, 9, 11
G = guildrespec.GOLD


def mate(name, class_id, level=18, points=(), money=5 * G, fee=G, guild="Cave", **kw):
    return guildrespec.Mate(
        name=name,
        guild=guild,
        level=level,
        class_id=class_id,
        points=tuple(points),
        money=money,
        fee=fee,
        free=kw.pop("free", True),
        **kw,
    )


def damage(n, guild="Cave", level=18, prefix="M"):
    return [
        mate(
            "%s%d" % (prefix, i), MAGE, level=level, points=(("Frost", 9),), guild=guild
        )
        for i in range(n)
    ]


def holy_paladin(name="Hp", **kw):
    return mate(name, PALADIN, points=(("Holy", 9),), **kw)


def prot_warrior(name="Pw", **kw):
    return mate(name, WARRIOR, points=(("Protection", 9),), **kw)


class TheTrainersPrice(unittest.TestCase):
    """Player::resetTalentsCost, over resettalents_cost and resettalents_time."""

    def test_the_first_reset_is_a_gold_then_five_then_ten(self):
        self.assertEqual(1 * G, guildrespec.reset_fee(0, 0, 10**9))
        self.assertEqual(5 * G, guildrespec.reset_fee(1 * G, 10**9, 10**9))
        self.assertEqual(10 * G, guildrespec.reset_fee(5 * G, 10**9, 10**9))

    def test_then_five_more_each_time_up_to_fifty(self):
        now = 10**9
        self.assertEqual(15 * G, guildrespec.reset_fee(10 * G, now - 60, now))
        self.assertEqual(50 * G, guildrespec.reset_fee(50 * G, now - 60, now))

    def test_and_five_less_a_month_down_to_ten(self):
        now, month = 10**9, guildrespec.MONTH_SECONDS
        self.assertEqual(20 * G, guildrespec.reset_fee(30 * G, now - 2 * month, now))
        self.assertEqual(10 * G, guildrespec.reset_fee(12 * G, now - month, now))


class TheCount(unittest.TestCase):
    def test_only_spent_talents_that_play_the_seat_count(self):
        mates = [
            holy_paladin(),
            mate("Ret", PALADIN, points=(("Retribution", 9),)),
            prot_warrior(),
            mate("Fury", WARRIOR, points=(("Fury", 9),)),
        ]
        c = guildrespec.count(mates)[("Cave", "15-19")]
        self.assertEqual(
            (1, 1, 2, 4), (c["tank"], c["healer"], c["damage"], c["members"])
        )

    def test_a_member_with_nothing_outside_its_raid_plan_tree_counts_as_that_seat(self):
        planned = mate("Pr", PRIEST, points=(), target_tree="Holy")
        mixed = mate("Pr2", PRIEST, points=(("Shadow", 3),), target_tree="Holy")
        c = guildrespec.count([planned, mixed])[("Cave", "15-19")]
        self.assertEqual((1, 1), (c["healer"], c["damage"]))

    def test_the_family_is_left_out(self):
        c = guildrespec.count([holy_paladin(family=True), *damage(1)])
        self.assertEqual(0, c[("Cave", "15-19")]["healer"])
        self.assertEqual(1, c[("Cave", "15-19")]["members"])


class WhoGoesTankOrHealer(unittest.TestCase):
    def test_a_band_with_no_healer_sends_the_member_with_fewest_points(self):
        mates = [
            prot_warrior(),
            mate("Shadow", PRIEST, points=(("Shadow", 9),)),
            mate("Ret", PALADIN, level=16, points=(("Retribution", 7),)),
            *damage(3),
        ]
        plan = guildrespec.plan(mates)
        self.assertEqual(1, len(plan.choices))
        choice = plan.choices[0]
        self.assertEqual(
            ("Ret", "healer", "Holy", 0, True),
            (choice.name, choice.seat, choice.tree, choice.tab, choice.reset),
        )
        self.assertEqual("walk-to-trainer talents:0", choice.command())
        self.assertIn("healer", choice.said)
        self.assertIn("Holy", choice.said)
        self.assertEqual(G, choice.fee)

    def test_a_priest_goes_holy_on_its_second_tab(self):
        mates = [
            prot_warrior(),
            mate("Shadow", PRIEST, points=(("Shadow", 9),)),
            *damage(3),
        ]
        choice = guildrespec.plan(mates).choices[0]
        self.assertEqual(("Shadow", 1), (choice.name, choice.tab))
        self.assertEqual("walk-to-trainer talents:1 max:20000", choice.command(20000))

    def test_a_druid_tanks_as_a_bear_and_says_so(self):
        mates = [
            holy_paladin(),
            mate("Boomkin", DRUID, points=(("Balance", 9),)),
            *damage(3),
        ]
        choice = guildrespec.plan(mates).choices[0]
        self.assertEqual(
            ("tank", "Feral Combat", 1), (choice.seat, choice.tree, choice.tab)
        )
        self.assertIn("bear", choice.said)
        self.assertNotIn("Feral Combat", choice.said)

    def test_the_larger_gap_first_and_healers_on_a_tie(self):
        mates = [
            mate("Fury", WARRIOR, points=(("Fury", 9),)),
            mate("Shadow", PRIEST, points=(("Shadow", 9),)),
            *damage(3),
        ]
        self.assertEqual("healer", guildrespec.plan(mates).choices[0].seat)
        two_groups = [
            holy_paladin(),
            holy_paladin("Hp2"),
            mate("Fury", WARRIOR, points=(("Fury", 9),)),
            *damage(7),
        ]
        self.assertEqual("tank", guildrespec.plan(two_groups).choices[0].seat)

    def test_a_member_who_cannot_pay_the_fee_is_passed_over(self):
        mates = [
            prot_warrior(),
            mate("Poor", PRIEST, points=(("Shadow", 2),), money=G - 1),
            mate("Rich", PRIEST, points=(("Shadow", 9),), money=2 * G),
            *damage(3),
        ]
        self.assertEqual("Rich", guildrespec.plan(mates).choices[0].name)

    def test_nobody_who_can_pay_leaves_the_band_short_and_says_why(self):
        mates = [
            prot_warrior(),
            mate("Poor", PRIEST, points=(("Shadow", 2),), money=0),
            *damage(3),
        ]
        plan = guildrespec.plan(mates)
        self.assertEqual((), plan.choices)
        self.assertIn("Cave 15-19 is 1 healer(s) short", plan.notes[0])

    def test_a_member_with_no_points_spent_needs_no_trainer_and_no_money(self):
        mates = [prot_warrior(), mate("Fresh", SHAMAN, points=(), money=0), *damage(3)]
        choice = guildrespec.plan(mates).choices[0]
        self.assertEqual(
            ("Fresh", "Restoration", False, 0),
            (choice.name, choice.tree, choice.reset, choice.fee),
        )
        self.assertIn("Resto", choice.said)

    def test_the_raid_plans_own_tree_wins_a_tie_then_the_class_that_only_heals(self):
        mates = [
            prot_warrior(),
            mate("Ret", PALADIN, points=(("Retribution", 9),)),
            mate("Enh", SHAMAN, points=(("Enhancement", 9),)),
            mate("Ret2", PALADIN, points=(("Retribution", 9),), target_tree="Holy"),
            *damage(2),
        ]
        self.assertEqual("Ret2", guildrespec.plan(mates).choices[0].name)
        mates[3] = mate("Ret2", PALADIN, points=(("Retribution", 9),))
        self.assertEqual("Enh", guildrespec.plan(mates).choices[0].name)

    def test_only_a_free_member_of_a_class_that_fits_at_level_ten_goes(self):
        mates = [
            prot_warrior(),
            mate("Busy", PRIEST, points=(("Shadow", 9),), free=False),
            mate("Rogue", ROGUE, points=(("Combat", 9),)),
            *damage(3),
        ]
        self.assertEqual((), guildrespec.plan(mates).choices)
        low = [
            mate("W%d" % i, WARRIOR, level=9, points=(("Arms", 1),)) for i in range(6)
        ]
        self.assertEqual((), guildrespec.plan(low).choices)

    def test_a_death_knight_is_never_asked_to_tank(self):
        mates = [holy_paladin(), mate("Dk", 6, points=(("Frost", 9),)), *damage(3)]
        self.assertEqual((), guildrespec.plan(mates).choices)


class TheGuildKeepsItsDamage(unittest.TestCase):
    def test_a_respec_never_takes_a_band_under_three_damage_a_group(self):
        mates = [
            prot_warrior(),
            mate("Shadow", PRIEST, points=(("Shadow", 9),)),
            *damage(2),
        ]
        mates.append(prot_warrior("Pw2"))
        self.assertEqual((), guildrespec.plan(mates).choices)

    def test_a_band_too_small_for_a_group_is_left_alone(self):
        mates = [mate("Shadow", PRIEST, points=(("Shadow", 9),)), *damage(3)]
        self.assertEqual((), guildrespec.plan(mates).choices)

    def test_one_a_guild_a_pass_and_each_guild_gets_its_own(self):
        cave = [
            mate("Shadow", PRIEST, points=(("Shadow", 9),)),
            mate("Fury", WARRIOR, points=(("Fury", 9),)),
            *damage(8),
        ]
        bonkers = [
            mate("Ele", SHAMAN, points=(("Elemental", 9),), guild="Bonkers"),
            prot_warrior("Pb", guild="Bonkers"),
            *damage(3, guild="Bonkers", prefix="B"),
        ]
        plan = guildrespec.plan(cave + bonkers)
        self.assertEqual(["Ele", "Shadow"], sorted(c.name for c in plan.choices))

    def test_a_member_already_playing_a_seat_is_never_moved(self):
        mates = [holy_paladin(), prot_warrior(), *damage(3)]
        self.assertEqual((), guildrespec.plan(mates).choices)


class WhatIsAlreadyOnItsWay(unittest.TestCase):
    """The database reads the old tree until the character saves."""

    def row(self, name, status, age, tab=1):
        return {
            "target_name": name,
            "command": "walk-to-trainer talents:%d" % tab,
            "source": guildrespec.source_for(name),
            "status": status,
            "age": age,
        }

    def mates(self):
        return [
            prot_warrior(),
            mate("Shadow", PRIEST, points=(("Shadow", 9),)),
            mate("Shadow2", PRIEST, points=(("Shadow", 9),)),
            *damage(3),
        ]

    def test_an_applied_respec_counts_as_its_seat(self):
        plan = guildrespec.plan(self.mates(), [self.row("Shadow", "applied", 30)])
        self.assertEqual((), plan.choices)

    def test_a_waiting_one_counts_until_it_is_stale(self):
        self.assertEqual(
            (),
            guildrespec.plan(self.mates(), [self.row("Shadow", "pending", 5)]).choices,
        )
        stale = [self.row("Shadow", "pending", guildrespec.PENDING_MINUTES + 1)]
        self.assertEqual(1, len(guildrespec.plan(self.mates(), stale).choices))

    def test_a_failed_one_cools_that_member_and_another_goes(self):
        plan = guildrespec.plan(self.mates(), [self.row("Shadow", "error", 30)])
        self.assertEqual("Shadow2", plan.choices[0].name)
        later = [self.row("Shadow", "error", guildrespec.RETRY_MINUTES + 1)]
        self.assertEqual(
            "Shadow", guildrespec.plan(self.mates(), later).choices[0].name
        )

    def test_the_guild_chat_line_is_not_a_respec_row(self):
        said = {
            "target_name": "Shadow",
            "command": "I'll go Holy talents:1",
            "source": guildrespec.say_source_for("Shadow"),
            "status": "applied",
            "age": 1,
        }
        self.assertEqual(1, len(guildrespec.plan(self.mates(), [said]).choices))


class FromTheJobPassRows(unittest.TestCase):
    def spells(self, class_id, tree, n):
        raw = json.loads((HERE / "talents.json").read_text(encoding="utf-8"))
        tid = next(
            k
            for k, t in raw["trees"].items()
            if t["class"] == class_id and t["name"] == tree
        )
        ranks = [r for t in raw["talents"] if str(t["tree"]) == tid for r in t["ranks"]]
        # One rank-1 spell of n different talents: n points.
        firsts = [t["ranks"][0] for t in raw["talents"] if str(t["tree"]) == tid]
        self.assertTrue(ranks)
        return ",".join(str(s) for s in firsts[:n])

    def test_the_members_talents_fee_target_and_freedom(self):
        job = types.SimpleNamespace(
            name="Ret",
            guild="Cave",
            level=18,
            class_id=PALADIN,
            money=3 * G,
            eligible=True,
            online=True,
            in_combat=False,
            map_id=0,
        )
        rows = [
            {
                "name": "Ret",
                "talent_spells": self.spells(PALADIN, "Retribution", 4),
                "resettalents_cost": G,
                "resettalents_time": 10**9,
            }
        ]
        (m,) = guildrespec.mates_from([job], rows, {"Ret": "Holy"}, (), (), 10**9)
        self.assertEqual(
            (4, "Retribution", 5 * G, "Holy", True),
            (m.spent, m.tree, m.fee, m.target_tree, m.free),
        )
        inside = types.SimpleNamespace(**{**vars(job), "map_id": 389})
        self.assertFalse(
            guildrespec.mates_from([inside], rows, {}, (), (), 10**9)[0].free
        )
        self.assertFalse(
            guildrespec.mates_from([job], rows, {}, (), {"Ret"}, 10**9)[0].free
        )

    def test_plays_is_guildruns_own(self):
        m = holy_paladin()
        member = guildrun.Member(
            name="Hp", guild="Cave", level=18, class_id=PALADIN, tree="Holy"
        )
        self.assertEqual(member.plays("healer"), m.plays("healer"))
        self.assertTrue(m.plays("healer"))


class TheRaidPlanKeepsTheTree(unittest.TestCase):
    def test_the_lineups_rewrite_keeps_a_guild_respecs_row(self):
        self.assertIn(
            "duty NOT IN (%s)"
            % ", ".join("'%s'" % d for d in sorted(guildrespec.GUILD_DUTY.values())),
            raidrun.DELETE_SPECS_SQL,
        )
        self.assertEqual(1, raidrun.DELETE_SPECS_SQL.count("%s"))

    def test_an_applied_respec_writes_its_row(self):
        source = ast.get_source_segment(BRIDGE, _function("_record_guild_respec"))
        writes = []

        class Cursor:
            def execute(self, sql, args=()):
                writes.append((sql, args))

        class Conn:
            def cursor(self):
                return contextlib.nullcontext(Cursor())

        namespace = {
            "raidrun": raidrun,
            "raidroles": guildrespec.raidroles,
            "_connect": lambda: contextlib.nullcontext(Conn()),
        }
        exec(compile(source, "bridge.py", "exec"), namespace)  # noqa: S102 - bridge.py's own source
        mates = [
            prot_warrior(),
            mate("Shadow", PRIEST, points=(("Shadow", 9),)),
            *damage(3),
        ]
        choice = guildrespec.plan(mates).choices[0]
        namespace["_record_guild_respec"](choice)
        self.assertEqual(raidrun.INSERT_SPEC_SQL, writes[0][0])
        self.assertEqual(
            ("Shadow", "Cave", PRIEST, 1, "Holy", "guild healer", 0), writes[0][1]
        )


def _function(name):
    tree = ast.parse(BRIDGE)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError("bridge.py has no %s" % name)


class TheBridgeRunsIt(unittest.TestCase):
    def body(self, name):
        return ast.get_source_segment(BRIDGE, _function(name))

    def test_the_job_pass_starts_the_respecs(self):
        self.assertIn("self._start_guild_respecs(", self.body("_start_guild_job_pass"))
        start = self.body("_start_guild_respecs")
        self.assertIn("guildrespec.enabled()", start)
        self.assertIn("guildrespec.plan(", start)
        self.assertIn("self._run_guild_respec(", start)

    def test_it_says_it_walks_and_records_in_that_order(self):
        run = self.body("_run_guild_respec")
        said = run.index('"guild", choice.said')
        walked = run.index("self._job_row(")
        recorded = run.index("_record_guild_respec")
        self.assertLess(said, walked)
        self.assertLess(walked, recorded)
        self.assertIn("if not await self._job_row(", run)

    def test_the_member_read_carries_the_reset_price(self):
        self.assertIn("c.resettalents_cost, c.resettalents_time", BRIDGE)
        facts = self.body("_fetch_job_facts")
        self.assertIn("SELECT name, tree FROM overseer_raid_spec", facts)
        self.assertIn('facts["recent_rows"]', facts)

    def test_it_can_be_switched_off(self):
        self.assertTrue(guildrespec.enabled({}))
        self.assertFalse(guildrespec.enabled({"GUILD_RESPEC": "off"}))


if __name__ == "__main__":
    unittest.main()
