"""Only naturally earned gold goes to the guild (the operator, 2026-09-24).

"Naturally earned only! All guild members can feel free to contribute." A
guild bot the factory kitted contributes once it has been reset to level 1
(`overseer_naturalized` part `reset`, quadseven/mod-overseer#704), and never
before. A family character contributes freely unless it took the factory-made
members' dues, until those are taken out (part `gold`).

Pure tests against natural.py and guildwork.plan_dues, plus source checks on
the bridge's dues, guild-bank and tab-urgency wiring, the way test_guildwork
reads it (bridge.py imports discord and cannot be imported here).
"""

import pathlib
import unittest

import guildroute
import guildwork
import natural

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")

FAMILY = ["Grug", "Grog", "Bork", "Og", "Ugga"]
GOLD = guildwork.COPPER_PER_GOLD


def ledger(*pairs):
    return natural.parts_by_name([{"name": n, "part": p} for n, p in pairs])


def walker(name, yards=40.0):
    return guildroute.Walker(
        name=name, map_id=0, aim="at:0:1,2,3", yards=yards, by_row=True
    )


class TheRule(unittest.TestCase):
    def test_a_guild_bot_contributes_only_after_its_reset(self):
        parts = ledger(("Goraraa", "reset"))
        got = natural.contributors(["Goraraa", "Velalenn"], FAMILY, parts, ["Grug"])
        self.assertEqual(got, {"Goraraa"})
        self.assertIn("not been reset to level 1",
                      natural.why_not("Velalenn", FAMILY, parts, ["Grug"]))

    def test_another_part_is_not_a_reset(self):
        parts = ledger(("Velalenn", "items"), ("Velalenn", "gold"))
        self.assertEqual(natural.contributors(["Velalenn"], FAMILY, parts, []), set())

    def test_the_family_contributes_unless_it_holds_unearned_dues(self):
        got = natural.contributors(FAMILY, FAMILY, {}, ["Grug"])
        self.assertEqual(got, {"Grog", "Bork", "Og", "Ugga"})
        self.assertIn("discard-unearned-gold",
                      natural.why_not("Grug", FAMILY, {}, ["Grug"]))

    def test_the_dues_taker_contributes_once_the_dues_are_taken_out(self):
        got = natural.contributors(FAMILY, FAMILY, ledger(("Grug", "gold")), ["Grug"])
        self.assertIn("Grug", got)

    def test_an_unreadable_ledger_resets_nobody(self):
        parts = ledger(("Goraraa", "reset"))
        got = natural.contributors(["Goraraa", "Bork"], FAMILY, parts, ["Grug"],
                                   ledger_readable=False)
        self.assertEqual(got, {"Bork"})

    def test_only_contributors_keeps_order_and_drops_the_rest(self):
        rows = [{"name": "Og", "money": 1}, {"name": "Grug", "money": 2},
                {"name": "Bork", "money": 3}]
        self.assertEqual(
            [r["name"] for r in natural.only_contributors(rows, {"Bork", "Og"})],
            ["Og", "Bork"])


class TheDues(unittest.TestCase):
    masters = {"Cave": "Grug"}

    def members(self):
        return [guildwork.Member("Goraraa", "Cave", 3254 * GOLD, True),
                guildwork.Member("Velalenn", "Cave", 3254 * GOLD, True)]

    def test_a_member_not_reset_posts_nothing(self):
        crew = self.members()
        plan = guildwork.plan_dues(
            crew, self.masters, {m.name: walker(m.name) for m in crew}, (), (),
            eligible={"Goraraa"})
        self.assertEqual([r.holder for r in plan.runs], ["Goraraa"])
        self.assertTrue(any("Velalenn posts no dues" in n for n in plan.notes))

    def test_nobody_reset_means_no_dues_at_all(self):
        crew = self.members()
        plan = guildwork.plan_dues(
            crew, self.masters, {m.name: walker(m.name) for m in crew}, (), (),
            eligible=frozenset())
        self.assertEqual(plan.runs, ())

    def test_the_gate_cannot_be_forgotten(self):
        with self.assertRaises(TypeError):
            guildwork.plan_dues([], self.masters, {}, (), ())


class TheBridgeIsWired(unittest.TestCase):
    def test_the_dues_pass_asks_the_ledger_and_passes_the_gate(self):
        self.assertIn("_natural_contributors, [m.name for m in members], names)", BRIDGE)
        self.assertIn("max_yards=self._guild_walk_cap(),\n"
                      "                                   eligible=eligible)", BRIDGE)

    def test_both_guild_bank_passes_deposit_only_earned_gold(self):
        self.assertIn("members = natural.only_contributors(members, eligible)", BRIDGE)
        self.assertIn("natural.only_contributors(\n"
                      "                await asyncio.to_thread(_fetch_guild_money, names), eligible)",
                      BRIDGE)

    def test_a_tab_is_bought_only_with_earned_gold(self):
        self.assertIn("members, cohort, eligible)", BRIDGE)
        self.assertIn('actions = tuple(a for a in actions if not a.command.startswith("bank buy-tab"))',
                      BRIDGE)
        self.assertIn("if master not in _natural_contributors([master], names):", BRIDGE)

    def test_the_ledger_read_fails_closed(self):
        self.assertIn('"SELECT name, part FROM overseer_naturalized"', BRIDGE)
        self.assertIn("takers = {str(n) for n in family_names or ()}", BRIDGE)

    def test_the_image_ships_the_module(self):
        self.assertIn("natural.py", DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
