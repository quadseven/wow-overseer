"""Individual mode outside dungeons (#2395): who a drive acts for, per member.

The pure rules are ordinary unit tests. The last classes pin the bridge's
wiring as text, the pattern test_trainjob.py uses, because the drives live in
bridge.py and run against a live realm.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import craft_rhythm  # noqa: E402
import individual  # noqa: E402
import trainjob  # noqa: E402
import travel  # noqa: E402

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
FAMILY = "Grug"
ON = {individual.ENV: "Grug"}
OFF = {}


class TheSetting(unittest.TestCase):
    def test_unset_names_no_family(self):
        self.assertFalse(individual.enabled(FAMILY, OFF))

    def test_a_named_family_is_on_whatever_its_case(self):
        for value in ("Grug", "grug", " Zug , GRUG "):
            self.assertTrue(individual.enabled(FAMILY, {individual.ENV: value}), value)

    def test_a_family_not_named_stays_off(self):
        self.assertFalse(individual.enabled("Zug", ON))

    def test_a_true_word_is_not_a_family(self):
        """The setting is a list of families, never a global switch."""
        for value in ("1", "true", "yes", "on", "all"):
            self.assertFalse(individual.enabled(FAMILY, {individual.ENV: value}), value)

    def test_a_family_with_no_key_is_never_individual(self):
        self.assertFalse(individual.enabled(None, {individual.ENV: "Grug"}))
        self.assertFalse(individual.enabled("", {individual.ENV: "Grug"}))


class WhatLinksAFamily(unittest.TestCase):
    def test_a_dungeon_job_links(self):
        for job in ("dungeon", "dungeon:wailing", " Dungeon:scarlet "):
            self.assertTrue(individual.links(job), job)

    def test_a_raid_job_links(self):
        self.assertTrue(individual.links("raid:moltencore"))

    def test_town_run_and_raid_prep_do_not_link(self):
        """Only a dungeon or a raid links a family."""
        self.assertFalse(individual.links("town run"))
        self.assertFalse(individual.links("raid prep"))

    def test_trade_and_quest_jobs_do_not_link(self):
        for job in ("quest", "craft", "train", "fish", "", None):
            self.assertFalse(individual.links(job), job)

    def test_one_linking_member_links_the_family(self):
        self.assertTrue(individual.linked({"Grug": "craft", "Og": "dungeon:wailing"}))
        self.assertFalse(individual.linked({"Grug": "craft", "Og": "quest"}))

    def test_active_needs_the_family_named_and_no_link(self):
        jobs = {"Grug": "craft", "Og": "quest"}
        self.assertTrue(individual.active(jobs, FAMILY, ON))
        self.assertFalse(individual.active(jobs, FAMILY, OFF))
        self.assertFalse(individual.active(jobs, "Zug", ON))
        self.assertFalse(individual.active({**jobs, "Ugga": "dungeon"}, FAMILY, ON))

    def test_an_empty_family_is_not_active(self):
        self.assertFalse(individual.active({}, FAMILY, ON))


class WhoADriveActsFor(unittest.TestCase):
    JOBS = {"Grug": "quest", "Og": "craft", "Ugga": "craft", "Bork": "train"}

    def test_individual_picks_each_member_on_the_mode(self):
        self.assertEqual(
            individual.members_on(self.JOBS, ("craft",), FAMILY, ON), ("Og", "Ugga")
        )

    def test_several_modes_may_be_asked_for(self):
        self.assertEqual(
            individual.members_on(self.JOBS, ("craft", "quest"), FAMILY, ON),
            ("Grug", "Og", "Ugga"),
        )

    def test_off_and_disagreeing_acts_for_nobody(self):
        """The old rule: rows that disagree are a half-landed order."""
        self.assertEqual(individual.members_on(self.JOBS, ("craft",), FAMILY, OFF), ())

    def test_off_and_agreeing_acts_for_everybody(self):
        jobs = {"Grug": "craft", "Og": "craft"}
        self.assertEqual(
            individual.members_on(jobs, ("craft",), FAMILY, OFF), ("Grug", "Og")
        )

    def test_a_linked_family_keeps_the_old_rule_with_the_setting_on(self):
        jobs = {"Grug": "dungeon", "Og": "craft"}
        self.assertEqual(individual.members_on(jobs, ("craft",), FAMILY, ON), ())

    def test_exempt_members_are_left_out(self):
        self.assertEqual(
            individual.members_on(self.JOBS, ("craft",), FAMILY, ON, exempt=("Og",)),
            ("Ugga",),
        )

    def test_exempt_members_do_not_spoil_agreement_when_off(self):
        jobs = {"Grug": "craft", "Og": "quest"}
        self.assertEqual(
            individual.members_on(jobs, ("craft",), FAMILY, OFF, exempt=("Og",)),
            ("Grug",),
        )


class AimingOnlyTheNamed(unittest.TestCase):
    def test_it_sets_the_named_and_clears_nobody_else(self):
        statements = travel.aim_only_statements(["Og", "Bork"], "trainer")
        self.assertEqual(len(statements), 1)
        sql, params = statements[0]
        self.assertNotIn("NOT IN", sql)
        self.assertEqual(params, (travel.resolve("trainer"), travel.NONE, "Bork", "Og"))

    def test_it_never_writes_over_an_aim_already_there(self):
        """Run, catch-up, trade and learn aims share the column; only an
        empty one is written."""
        sql, params = travel.aim_only_statements(["Og"], "trainer")[0]
        self.assertIn("WHERE travel_npc = %s AND name IN", sql)
        self.assertEqual(params[1], "")

    def test_naming_nobody_writes_nothing(self):
        self.assertEqual(travel.aim_only_statements([], "trainer"), [])

    def test_an_unknown_target_is_refused(self):
        with self.assertRaises(ValueError):
            travel.aim_only_statements(["Og"], "no-such-place")

    def test_a_target_is_required(self):
        with self.assertRaises(ValueError):
            travel.aim_only_statements(["Og"], "")


def trainee(name, job="train", skill=0, wanted=(), holds=()):
    return trainjob.Member(
        name=name, job=job, learn_skill=skill, wanted=tuple(wanted), holds=tuple(holds)
    )


class TrainingPerMember(unittest.TestCase):
    TAILORING = 197
    MINING = 186

    def family(self):
        return [
            trainee("Grug", job="quest"),
            trainee("Og", skill=self.TAILORING, wanted=(self.TAILORING,)),
            trainee("Bork", skill=self.MINING, wanted=(self.MINING,)),
        ]

    def test_off_a_disagreeing_family_sends_nobody(self):
        plan = trainjob.plan(self.family())
        self.assertEqual(plan.traveller, "")
        self.assertIn("not agreed", plan.why_not)

    def test_individual_sends_every_member_on_train(self):
        plan = trainjob.plan(self.family(), individual=True)
        self.assertEqual(plan.travellers, ("Bork", "Og"))
        self.assertEqual(plan.traveller, "Bork")
        self.assertTrue(plan.individual)

    def test_individual_statements_clear_nobody_else(self):
        plan = trainjob.plan(self.family(), individual=True)
        statements = trainjob.statements(plan)
        self.assertEqual(
            statements,
            travel.aim_only_statements(["Bork", "Og"], trainjob.TRAINER_ROLE),
        )

    def test_individual_with_nobody_on_train_says_why(self):
        members = [trainee("Grug", job="quest"), trainee("Og", job="craft")]
        plan = trainjob.plan(members, individual=True)
        self.assertEqual(plan.travellers, ())
        self.assertIn("Nobody", plan.why_not)

    def test_individual_skips_a_member_with_nothing_to_learn(self):
        members = self.family() + [trainee("Ugga")]
        plan = trainjob.plan(members, individual=True)
        self.assertNotIn("Ugga", plan.travellers)

    def test_the_linked_plan_is_unchanged(self):
        members = [
            trainee("Og", skill=self.TAILORING, wanted=(self.TAILORING,)),
            trainee("Bork", skill=self.MINING, wanted=(self.MINING,)),
        ]
        plan = trainjob.plan(members)
        self.assertEqual(plan.traveller, "Bork")
        self.assertEqual(plan.waiting, ("Og",))
        self.assertFalse(plan.individual)
        self.assertEqual(
            trainjob.statements(plan),
            travel.aim_statements(["Bork"], trainjob.TRAINER_ROLE),
        )


def stand(name, verdict):
    return craft_rhythm.Stand(
        name=name, craft_spell=1, verdict=verdict, casts=0, thinnest="x", why=""
    )


class TheRhythmPerMember(unittest.TestCase):
    def test_each_member_gets_its_own_mode(self):
        stands = [stand("Og", craft_rhythm.SHORT), stand("Ugga", craft_rhythm.STOCKED)]
        jobs = {"Og": craft_rhythm.MODE_CRAFT, "Ugga": craft_rhythm.MODE_GATHER}
        plans = dict(craft_rhythm.member_rhythms(stands, jobs))
        self.assertEqual(plans["Og"].mode, craft_rhythm.MODE_GATHER)
        self.assertTrue(plans["Og"].changed)
        self.assertEqual(plans["Ugga"].mode, craft_rhythm.MODE_CRAFT)
        self.assertTrue(plans["Ugga"].changed)

    def test_a_member_on_another_job_is_left_alone(self):
        stands = [stand("Bork", craft_rhythm.SHORT)]
        plans = dict(craft_rhythm.member_rhythms(stands, {"Bork": "train"}))
        self.assertEqual(plans["Bork"].mode, "")
        self.assertFalse(plans["Bork"].changed)

    def test_a_member_already_in_its_mode_is_not_changed(self):
        stands = [stand("Og", craft_rhythm.STOCKED)]
        plans = dict(
            craft_rhythm.member_rhythms(stands, {"Og": craft_rhythm.MODE_CRAFT})
        )
        self.assertFalse(plans["Og"].changed)

    def test_a_member_with_no_row_is_left_alone(self):
        stands = [stand("Og", craft_rhythm.SHORT)]
        plans = dict(craft_rhythm.member_rhythms(stands, {}))
        self.assertFalse(plans["Og"].changed)


class TheBridgeIsWired(unittest.TestCase):
    """Source-shape pins: the drives ask `individual` before standing down."""

    SOURCE = BRIDGE.read_text(encoding="utf-8")

    def body(self, header):
        start = self.SOURCE.index(header)
        end = self.SOURCE.find("\n    async def ", start + len(header))
        return self.SOURCE[start:end]

    def test_the_bridge_imports_the_module(self):
        self.assertTrue("\nimport individual\n" in self.SOURCE)

    def test_the_train_drive_asks_per_member(self):
        body = self.body("    async def _drive_train(self)")
        self.assertIn("individual.active(", body)
        self.assertIn("trainjob.plan(members, individual=", body)

    def test_the_train_drive_respects_a_run_and_the_queue(self):
        body = self.body("    async def _drive_train(self)")
        self.assertLess(body.index("_queue_owns_job"), body.index("trainjob.plan("))
        self.assertLess(body.index("self._mid_run("), body.index("trainjob.plan("))

    def test_the_gather_half_is_held(self):
        body = self.body("    async def _individual_rhythm_moves(self")
        self.assertIn("if plan.mode != craft_rhythm.MODE_CRAFT:", body)
        self.assertLess(
            body.index("if plan.mode != craft_rhythm.MODE_CRAFT:"),
            body.index("_insert_job"),
        )

    def test_the_craft_rhythm_acts_per_member(self):
        body = self.body("    async def _craft_rhythm_once(self")
        self.assertIn("individual.active(", body)
        self.assertIn("self._individual_rhythm_moves(", body)

    def test_per_member_moves_respect_the_campaign_queue(self):
        body = self.body("    async def _individual_rhythm_moves(self")
        self.assertIn("_queue_owns_job", body)
        self.assertIn("_insert_job", body)

    def test_craft_supply_acts_per_member(self):
        body = self.body("    async def _craft_supply_once(self")
        self.assertIn("individual.members_on(", body)


if __name__ == "__main__":
    unittest.main()
