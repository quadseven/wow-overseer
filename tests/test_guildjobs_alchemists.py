"""The maintenance crew's alchemists: the raid's potions need somebody to brew
them, and before this nobody outside the family ever started Alchemy.

guildcorps.ROLES asks two alchemists of every guild for Molten Core (#275), and
plan_corps fills that post only from maintenance members who already hold the
trade. The trade split handed maintenance members gathering trades, Tailoring
and First Aid, never Alchemy, so on the dev realm on 2026-10-10 both guilds'
alchemist posts were empty and raidsupply said "no alchemist is free" on every
pass. One maintenance member in ALCHEMIST_EVERY learns Alchemy now, beside
Herbalism, the trade that feeds it.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import guildcorps  # noqa: E402
import guildjobs  # noqa: E402

H, M, S = guildjobs.HERBALISM, guildjobs.MINING, guildjobs.SKINNING
FA, TAILOR, ALCH = guildjobs.FIRST_AID, guildjobs.TAILORING, guildjobs.ALCHEMY


def crewman(name, guild="Cave", **over):
    base = dict(
        name=name,
        guild=guild,
        role=guildjobs.MAINTENANCE,
        level=20,
        class_id=3,
        race=1,
        online=True,
        map_id=0,
        x=-9000.0,
        y=100.0,
        money=5000,
        eligible=True,
    )
    base.update(over)
    base["skills"] = dict(base.get("skills") or {FA: (40, 75)})
    return guildjobs.Member(**base)


def trades_of(crew):
    tailors = guildjobs.choose_tailors(crew)
    alchemists = guildjobs.choose_alchemists(crew, tailors)
    return guildjobs.cloth_trades(
        guildjobs.split_trades(crew, tailors, alchemists), tailors, alchemists
    )


class TheCrewAlchemists(unittest.TestCase):
    def test_a_crew_of_ten_has_as_many_alchemists_as_the_corps_asks(self):
        crew = [crewman("M%02d" % i) for i in range(10)]
        trades = trades_of(crew)
        alchemists = [n for n, t in trades.items() if ALCH in t]
        want = dict((role, n) for role, _skill, n in guildcorps.ROLES)["alchemist"]
        self.assertEqual(len(alchemists), want)

    def test_an_alchemist_gathers_herbs_and_keeps_two_primaries(self):
        crew = [crewman("M%02d" % i) for i in range(10)]
        trades = trades_of(crew)
        for name, held in trades.items():
            primaries = [s for s in held if s in guildjobs.PRIMARY_SKILLS]
            self.assertLessEqual(len(primaries), guildjobs.MAX_PRIMARY, name)
            if ALCH in held:
                self.assertEqual(
                    [s for s in held if s in guildjobs.GATHERING], [H], name
                )
                self.assertNotIn(TAILOR, held, name)

    def test_a_held_alchemist_is_kept_an_alchemist(self):
        crew = [crewman("M%02d" % i) for i in range(9)]
        crew.append(crewman("Zed", skills={FA: (40, 75), ALCH: (30, 75)}))
        self.assertIn("Zed", guildjobs.choose_alchemists(crew))

    def test_a_herbalist_with_a_free_slot_comes_before_an_empty_member(self):
        crew = [
            crewman("A%02d" % i, skills={FA: (1, 75), H: (5, 75), M: (5, 75)})
            for i in range(8)
        ]
        crew += [crewman("Bare"), crewman("Diggo", skills={FA: (1, 75), H: (75, 75)})]
        self.assertEqual(
            guildjobs.choose_alchemists(crew), frozenset({"Diggo", "Bare"})
        )

    def test_a_member_with_both_primaries_taken_is_no_alchemist(self):
        crew = [crewman("F%d" % i, skills={H: (5, 75), M: (5, 75)}) for i in range(10)]
        self.assertEqual(guildjobs.choose_alchemists(crew), frozenset())

    def test_a_tailor_is_not_also_the_alchemist(self):
        crew = [crewman("M%02d" % i) for i in range(10)]
        tailors = guildjobs.choose_tailors(crew)
        self.assertFalse(tailors & guildjobs.choose_alchemists(crew, tailors))

    def test_a_small_crew_has_no_alchemist(self):
        crew = [crewman("M%d" % i) for i in range(guildjobs.ALCHEMIST_EVERY - 1)]
        self.assertEqual(guildjobs.choose_alchemists(crew), frozenset())

    def test_each_guild_chooses_its_own(self):
        crew = [crewman("C%02d" % i) for i in range(10)]
        crew += [crewman("B%02d" % i, guild="Bonkers") for i in range(10)]
        chosen = guildjobs.choose_alchemists(crew)
        self.assertEqual(len([n for n in chosen if n.startswith("C")]), 2)
        self.assertEqual(len([n for n in chosen if n.startswith("B")]), 2)

    def test_raiders_and_summoners_are_never_chosen(self):
        crew = [crewman("R%02d" % i, role=guildjobs.RAIDER) for i in range(10)]
        crew += [crewman("W%02d" % i, role=guildjobs.SUMMONER) for i in range(10)]
        self.assertEqual(guildjobs.choose_alchemists(crew), frozenset())

    def test_the_plan_sends_an_alchemist_to_learn_alchemy(self):
        crew = [
            crewman("M%02d" % i, skills={FA: (40, 75), H: (40, 75)}) for i in range(10)
        ]
        result = guildjobs.plan(crew, masters={"Cave": "Grug"})
        alchemists = [n for n, t in result.trades.items() if ALCH in t]
        self.assertEqual(len(alchemists), 2)
        commands = [
            r.command for s in result.steps if s.holder in alchemists for r in s.rows
        ]
        self.assertIn("walk-to-trainer skill:%d" % ALCH, commands)

    def test_the_corps_fills_its_alchemist_post_once_the_trade_is_held(self):
        held = guildcorps.Member(
            name="Diggo",
            guild="Cave",
            maintenance=True,
            skills={ALCH: (1, 75), H: (75, 75)},
        )
        posts = guildcorps.plan_corps([held])["Cave"]
        self.assertIn(("Diggo", "alchemist"), [(p.name, p.role) for p in posts])


if __name__ == "__main__":
    unittest.main()
