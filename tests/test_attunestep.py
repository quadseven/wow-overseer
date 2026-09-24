"""The Molten Core attunement step (attunestep.py): when the family walks to
Lothos Riftwaker, which quest row each member gets there, and when the planner
waits for it."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import attunestep  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
with open(os.path.join(ROOT, "bridge.py")) as f:
    BRIDGE = f.read()

# The dev realm's own rows (read-only, 2026-09-24): Lothos's spawn, and the two
# attunement rows with their MinLevel and AllowableRaces.
SPAWN = (0, -7508.63, -1039.84, 180.995)
QUESTS = (
    attunestep.QuestRow(7487, 55, 690),
    attunestep.QuestRow(7848, 55, 1101),
)
HUMAN, DWARF, ORC = 1, 3, 2
FAMILY = ("Grug", "Grog", "Bork", "Og", "Ugga")


def member(name, *, race=HUMAN, level=60, at=None, map_id=0, **kw):
    x, y, z = at if at is not None else (-8900.0, 560.0, 94.0)
    return attunestep.Member(name, level, race, map_id, x, y, z, **kw)


def at_lothos(name, **kw):
    return member(name, at=(SPAWN[1] + 3.0, SPAWN[2], SPAWN[3]), **kw)


def facts(members, **kw):
    base = dict(
        family="Grug",
        leader="Grug",
        members=tuple(members),
        quests=QUESTS,
        spawn=SPAWN,
        job="quest",
        due=True,
    )
    base.update(kw)
    return attunestep.Facts(**base)


class WhichRow(unittest.TestCase):
    def test_the_row_every_members_race_may_take(self):
        alliance = [member(n) for n in FAMILY]
        self.assertEqual(attunestep.quest_for(alliance, QUESTS).quest_id, 7848)
        horde = [member(n, race=ORC) for n in FAMILY]
        self.assertEqual(attunestep.quest_for(horde, QUESTS).quest_id, 7487)
        self.assertIsNone(
            attunestep.quest_for([member("A"), member("B", race=ORC)], QUESTS)
        )

    def test_the_commands(self):
        self.assertEqual(attunestep.command(attunestep.TAKE, 7848), "take quest:7848")
        self.assertEqual(
            attunestep.command(attunestep.TURN_IN, 7848), "turnin quest:7848"
        )


class WhenItWaits(unittest.TestCase):
    def test_every_member_attuned_is_done(self):
        s = attunestep.step(facts([member(n, rewarded=True) for n in FAMILY]))
        self.assertEqual(s.verdict, attunestep.DONE)
        self.assertFalse(s.hold_planner)

    def test_below_the_quests_minimum_waits(self):
        zug = [member(n, race=ORC, level=29) for n in ("Zug", "Zrog")]
        s = attunestep.step(facts(zug, leader="Zug"))
        self.assertEqual(s.verdict, attunestep.WAIT)
        self.assertIn("below level 55", s.line)
        self.assertFalse(s.hold_planner)

    def test_on_kalimdor_it_waits_for_the_crossing(self):
        """Measured 2026-09-24: the family stood in the Barrens, map 1."""
        s = attunestep.step(facts([member(n, map_id=1) for n in FAMILY]))
        self.assertEqual(s.verdict, attunestep.WAIT)
        self.assertIn("Eastern Kingdoms", s.line)
        self.assertFalse(s.hold_planner, "the planner may take the family across")
        self.assertFalse(s.aim)

    def test_an_unread_member_is_not_on_the_eastern_kingdoms(self):
        members = [member(n) for n in FAMILY[:4]] + [member("Ugga", map_id=None)]
        s = attunestep.step(facts(members))
        self.assertEqual(s.verdict, attunestep.WAIT)
        self.assertIn("Ugga unread", s.line)

    def test_queued_runs_come_first(self):
        s = attunestep.step(facts([member(n) for n in FAMILY], due=False))
        self.assertEqual(s.verdict, attunestep.WAIT)
        self.assertIn("after the family's queued runs", s.line)
        self.assertFalse(s.hold_planner)

    def test_another_job_holds_the_planner_and_moves_nobody(self):
        s = attunestep.step(facts([member(n) for n in FAMILY], job="town run"))
        self.assertEqual(s.verdict, attunestep.WAIT)
        self.assertTrue(s.hold_planner)
        self.assertFalse(s.aim or s.rows)
        mid = attunestep.step(facts([member(n) for n in FAMILY], mid_run=True))
        self.assertIn("mid-run", mid.line)

    def test_holding_the_quest_without_a_fragment_is_blackrock_depths(self):
        members = [member(n, status=attunestep.STATUS_INCOMPLETE) for n in FAMILY]
        s = attunestep.step(facts(members))
        self.assertEqual(s.verdict, attunestep.BLACKROCK)
        self.assertIn("Blackrock Depths is next", s.line)
        self.assertFalse(s.hold_planner)

    def test_no_spawn_or_no_row_is_said(self):
        self.assertIn(
            "no spawn", attunestep.step(facts([member("Grug")], spawn=None)).line
        )
        self.assertIn(
            "admits every member",
            attunestep.step(facts([member("Grug")], quests=())).line,
        )


class WhenItWalks(unittest.TestCase):
    def test_far_from_lothos_the_leader_walks_and_the_planner_waits(self):
        s = attunestep.step(facts([member(n) for n in FAMILY]))
        self.assertEqual(s.verdict, attunestep.GO)
        self.assertTrue(s.hold_planner and s.aim)
        self.assertFalse(s.rows or s.release)
        self.assertIn("Grug walks the family to Lothos Riftwaker", s.line)
        self.assertIn("yards", s.line)

    def test_at_lothos_each_member_in_reach_takes_the_quest(self):
        members = [at_lothos(n) for n in FAMILY[:4]] + [member("Ugga")]
        s = attunestep.step(facts(members))
        self.assertEqual(s.verdict, attunestep.GO)
        self.assertEqual(
            [r for r in s.rows],
            [(n, "take quest:7848") for n in FAMILY[:4]],
        )
        self.assertTrue(s.release, "the leader is there: the walk is handed back")
        self.assertFalse(s.aim)

    def test_a_row_is_not_written_twice_inside_the_retry(self):
        members = [at_lothos(n) for n in FAMILY]
        recent = frozenset({("Grug", "take quest:7848"), ("Grog", "take quest:7848")})
        s = attunestep.step(facts(members, recent=recent))
        self.assertEqual([r[0] for r in s.rows], ["Bork", "Og", "Ugga"])

    def test_a_complete_quest_is_handed_in_and_the_attuned_are_left_alone(self):
        members = [
            at_lothos("Grug", status=attunestep.STATUS_COMPLETE),
            at_lothos("Grog", rewarded=True),
            at_lothos("Bork", status=attunestep.STATUS_INCOMPLETE),
        ]
        s = attunestep.step(facts(members))
        self.assertEqual(s.rows, (("Grug", "turnin quest:7848"),))

    def test_the_horde_row_for_the_horde(self):
        members = [at_lothos(n, race=ORC) for n in ("Zug", "Zrog")]
        s = attunestep.step(facts(members, leader="Zug", family="Zug"))
        self.assertEqual(s.rows[0], ("Zug", "take quest:7487"))


class TheRows(unittest.TestCase):
    def test_facts_from_the_statements_rows(self):
        f = attunestep.facts_from_rows(
            "Grug",
            "Grug",
            ["Grug", "Ugga"],
            [
                {"name": "Grug", "level": 60, "race": 1},
                {"name": "Ugga", "level": 60, "race": 3},
            ],
            [
                {
                    "name": "Grug",
                    "map_id": 0,
                    "pos_x": -7505.0,
                    "pos_y": -1040.0,
                    "pos_z": 181.0,
                }
            ],
            [{"name": "Ugga", "quest": 7848}],
            [{"name": "Grug", "quest": 7848, "status": 1}],
            [
                {"ID": 7487, "MinLevel": 55, "AllowableRaces": 690},
                {"ID": 7848, "MinLevel": 55, "AllowableRaces": 1101},
            ],
            [
                {
                    "map": 0,
                    "position_x": -7508.63,
                    "position_y": -1039.84,
                    "position_z": 180.995,
                }
            ],
            [{"target_name": "Grug", "command": "turnin quest:7848"}],
            job="quest",
            due=True,
        )
        grug, ugga = f.members
        self.assertEqual((grug.map_id, grug.status, grug.rewarded), (0, 1, False))
        self.assertTrue(attunestep.in_reach(grug, f.spawn))
        self.assertIsNone(ugga.map_id, "no fresh snapshot is unread, not map 0")
        self.assertTrue(ugga.rewarded)
        self.assertEqual(f.quests[1], attunestep.QuestRow(7848, 55, 1101))
        self.assertIn(("Grug", "turnin quest:7848"), f.recent)

    def test_the_snapshot_age_is_the_constant(self):
        self.assertIn(
            "INTERVAL %d SECOND" % attunestep.SNAPSHOT_MAX_AGE_SECONDS,
            attunestep.SNAPSHOT_SQL,
        )

    def test_the_switch(self):
        self.assertTrue(attunestep.enabled({}))
        self.assertFalse(attunestep.enabled({"ATTUNEMENT_STEP": "off"}))


class TheBridgeCarriesItOut(unittest.TestCase):
    def test_the_step_runs_before_the_planner_and_holds_it(self):
        body = BRIDGE[BRIDGE.index("    async def _plan_campaigns(") :]
        body = body[: body.index("    async def _plan_campaign(")]
        attune = body.index("held = await self._attunement_pass(pending, fams)")
        self.assertLess(attune, body.index("for key, fam in sorted(fams.items()):"))
        self.assertIn("            if key in held:\n                continue", body)

    def test_the_walk_goes_through_the_town_slot_with_a_long_lease(self):
        self.assertIn(
            "await self._claim_town_slot(ATTUNE_CLAIMANT, leader,\n"
            "                                        attunestep.AIM,",
            BRIDGE,
        )
        self.assertIn('ATTUNE_CLAIMANT = "%s"' % attunestep.CLAIMANT, BRIDGE)
        self.assertEqual(
            BRIDGE.count("ATTUNE_CLAIMANT: TOWN_SLOT_FLIGHT_LEASE_SECONDS"), 2
        )

    def test_a_realm_without_the_quest_kind_is_said_not_crashed(self):
        self.assertIn("overseer_command.kind has no 'quest' value", BRIDGE)
        self.assertIn("if exc.args and exc.args[0] == 1265:", BRIDGE)

    def test_the_hold_has_a_limit(self):
        self.assertIn("if now - since <= attunestep.HOLD_LIMIT_SECONDS:", BRIDGE)


if __name__ == "__main__":
    unittest.main()
