"""Bank, mail and learn trips act per member in individual mode (#2406).

On main each of the three passes assumed one traveller per family: the bank
pass and the mail pass asked the town slot for the leader, and the learn aim
aimed the leader alone and left the rest waiting for the lead. In individual
mode (individual.py, #2395) a member that needs a banker, a mailbox or a
trainer walks there itself.

The pure half is tested on its own. The bridge half drives the real
`_bank_once`, `_mail_once` and `_reconcile_learn_aims` with every read
stubbed, and records which writer each pass reached: the per-member aim
(`travel.aim_only_statements`, an empty column only) or the family's one
traveller through the town slot. None touches a database.
"""

import asyncio
import os
import types
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, fresh_import, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import bank
    import bankbags
    import individual
    import learnaim
    import mailrun
    import travel


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    return fresh_import("bridge", discord=stub, pymysql=PYMYSQL)


bridge = _import_bridge()

NAMES = ["Bork", "Grug", "Og", "Ugga"]
GRUG = {individual.ENV: "Grug"}
APART = {"Bork": "quest", "Grug": "quest", "Og": "craft", "Ugga": "train"}
LINKED = dict(APART, Bork="dungeon:deadmines")
TRAINER = travel.resolve(learnaim.TRAINER_ROLE)
MINING, HERBALISM = 186, 182


# --- the pure half ------------------------------------------------------------


class AMemberAimIsWrittenIntoAnEmptyColumnOnly(unittest.TestCase):
    def test_a_ground_aim_is_a_target_for_a_members_own_walk(self):
        aim = travel.ground_aim(1, -7203.1, -3821.1, 8.6)
        sql, params = travel.aim_only_statements(["Og"], aim)[0]
        self.assertIn("WHERE travel_npc = %s AND name IN (%s)", sql)
        self.assertEqual((aim, travel.NONE, "Og"), params)

    def test_a_ground_aim_too_long_for_the_column_is_refused(self):
        with self.assertRaises(ValueError):
            travel.aim_only_statements(["Og"], "at:1:" + "9" * 40)

    def test_something_that_is_no_target_is_still_refused(self):
        with self.assertRaises(ValueError):
            travel.aim_only_statements(["Og"], "no-such-place")


class EachMembersBankErrandIsJudgedOnItsOwnFacts(unittest.TestCase):
    def steps(self, **kw):
        facts = dict(wanting=(), at_counter={}, outstanding={})
        facts.update(kw)
        return bank.member_errand_steps(NAMES, **facts)

    def test_a_member_with_work_and_no_banker_in_reach_is_aimed(self):
        steps = self.steps(wanting=["Og"])
        self.assertEqual(bank.BANK_ERRAND_AIM, steps["Og"])

    def test_nobody_else_is_aimed_for_that_members_work(self):
        steps = self.steps(wanting=["Og"])
        others = {n: s for n, s in steps.items() if n != "Og"}
        self.assertEqual({bank.BANK_ERRAND_RELEASE}, set(others.values()))

    def test_a_member_at_the_counter_with_work_holds_for_its_rows(self):
        steps = self.steps(wanting=["Og"], at_counter={"Og": True})
        self.assertEqual(bank.BANK_ERRAND_HOLD, steps["Og"])

    def test_unanswered_rows_hold_that_members_errand_only(self):
        steps = self.steps(outstanding={"Ugga": 2})
        self.assertEqual(bank.BANK_ERRAND_HOLD, steps["Ugga"])
        self.assertEqual(bank.BANK_ERRAND_RELEASE, steps["Bork"])

    def test_a_queue_that_cannot_be_read_holds(self):
        steps = self.steps(wanting=["Og"], outstanding={"Og": -1})
        self.assertEqual(bank.BANK_ERRAND_HOLD, steps["Og"])

    def test_one_members_far_walk_never_defers_another(self):
        """The split rule is the family trip's; nobody waits for anybody here."""
        steps = self.steps(wanting=["Og", "Ugga"], at_counter={"Ugga": True})
        self.assertEqual(bank.BANK_ERRAND_AIM, steps["Og"])
        self.assertEqual(bank.BANK_ERRAND_HOLD, steps["Ugga"])


def _learn_rows():
    return [
        learnaim.Row("Grug", leads=True, wanted=(MINING,)),
        learnaim.Row("Og", learn_skill=MINING, wanted=(MINING,)),
        learnaim.Row("Ugga", learn_skill=HERBALISM, wanted=(HERBALISM,)),
        learnaim.Row("Bork", learn_skill=MINING, travel_npc="vendor", wanted=(MINING,)),
    ]


class TheLearnAimActsPerMember(unittest.TestCase):
    def test_every_member_with_an_unwalked_errand_is_aimed(self):
        plan = learnaim.plan(_learn_rows(), individual=True)
        self.assertEqual(("Og", "Ugga"), plan.aims)
        self.assertEqual((), plan.waiting, "nobody waits for the lead")

    def test_a_member_already_walking_somewhere_is_not_aimed(self):
        plan = learnaim.plan(_learn_rows(), individual=True)
        self.assertNotIn("Bork", plan.aims)

    def test_the_write_is_the_empty_column_aim_and_names_only_them(self):
        plan = learnaim.plan(_learn_rows(), individual=True)
        self.assertEqual(
            travel.aim_only_statements(["Og", "Ugga"], learnaim.TRAINER_ROLE),
            learnaim.statements(plan),
        )

    def test_no_statement_can_touch_a_member_it_does_not_name(self):
        plan = learnaim.plan(_learn_rows(), individual=True)
        for sql, _params in learnaim.statements(plan):
            self.assertIn("name", sql.split("WHERE", 1)[1])
            self.assertNotIn("NOT IN", sql)

    def test_the_report_names_every_member_aimed(self):
        said = learnaim.report(learnaim.plan(_learn_rows(), individual=True))
        self.assertIn("individual: aimed Og, Ugga", said)

    def test_a_linked_family_still_waits_for_the_lead(self):
        plan = learnaim.plan(_learn_rows())
        self.assertEqual((), plan.aims)
        self.assertEqual("", plan.aim)
        self.assertEqual(("Og", "Ugga"), plan.waiting)
        self.assertEqual([], learnaim.statements(plan))

    def test_a_linked_familys_leader_keeps_its_guarded_aim(self):
        rows = [learnaim.Row("Grug", learn_skill=MINING, leads=True, wanted=(MINING,))]
        sql, params = learnaim.statements(learnaim.plan(rows))[0]
        self.assertIn("AND learn_skill = %s AND travel_npc = ''", sql)
        self.assertEqual((learnaim.TRAINER_ROLE, "Grug", MINING), params)


# --- the bridge half ----------------------------------------------------------


class _World:
    """The reads every pass makes, stubbed, and the writers it reached."""

    def __init__(self, jobs=None, queue_owns=False, in_run=False):
        self.jobs = dict(APART if jobs is None else jobs)
        self.queue_owns = queue_owns
        self.in_run = in_run
        self.member_aims, self.slot_claims, self.released = [], [], []
        self.learn_statements, self.inserted = [], []
        self.asked = []

    def bridge_self(self):
        this = bridge.Bridge.__new__(bridge.Bridge)
        this._bank_family_movement = {}

        async def mid_run(names):
            self.asked.append("run")
            return self.in_run

        async def claim(claimant, character, aim, **kwargs):
            self.slot_claims.append((claimant, character, aim))
            return True

        async def exit_route(*args):
            return False

        async def settled(names):
            return {}

        this._mid_run = mid_run
        this._claim_town_slot = claim
        this._bank_exit_route = exit_route
        this._settled_positions = settled
        this._cohort_town_slot = lambda cohort=None: None
        this._town_slot = types.SimpleNamespace(learn_waits="")
        return this

    def queue_owns_job(self, family=None, dungeon=False):
        self.asked.append("queue")
        return self.queue_owns

    def aim_members_alone(self, names, target):
        self.member_aims.append((list(names), target))
        return len(names)

    def common(self):
        log = types.SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            debug=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        )
        return dict(
            log=log,
            _STANDIN_OUT=frozenset(),
            _family_of=lambda cohort=None: (list(NAMES), "Grug"),
            _individual_family=lambda cohort=None: (
                "Grug" if individual.families() else None
            ),
            _standing_jobs=lambda family=None: dict(self.jobs),
            _queue_owns_job=self.queue_owns_job,
            _aim_members_alone=self.aim_members_alone,
            _economy_aimable=lambda claimant, names: tuple(names),
            _member_death_disc_refusals=lambda names, aim: {},
            _release_trade_errand=lambda name, aim: (
                self.released.append((name, aim)) or True
            ),
        )


def _og_deposit():
    return bank.Move("Og", "deposit", 501, "Rough Stone", 5, "kept in the bank")


def _run_bank(world, counter=(), environ=GRUG):
    this = world.bridge_self()
    facts = [bankbags.Facts(name=n, worn=(10, 10, 10, 10)) for n in NAMES]
    here = {"map_id": 0, "pos_x": 0.0, "pos_y": 0.0}
    with (
        mock.patch.dict(os.environ, environ),
        mock.patch.multiple(
            bridge,
            _pass_completed=lambda name: True,
            _plan_bank=lambda names: bank.Plan(moves=(_og_deposit(),)),
            _log_changed=lambda *a, **k: None,
            _recent_bank_keys=lambda minutes: set(),
            _fetch_positions=lambda names: {n: here for n in names},
            _fetch_bank_bag_facts=lambda names: list(facts),
            _fetch_town=lambda name: types.SimpleNamespace(banker=name in counter),
            _outstanding_bank_moves=lambda names: 0,
            _current_travel_npc=lambda name: "",
            _nearest_banker_yards=lambda name: 80.0,
            _insert_bank=lambda move, command: (
                world.inserted.append((move.character, command)) or 1
            ),
            **world.common(),
        ),
    ):
        asyncio.run(this._bank_once())
    return world


class TheBankPassActsPerMember(unittest.TestCase):
    def test_the_member_with_bank_work_is_aimed_and_the_leader_is_not(self):
        world = _run_bank(_World())
        self.assertEqual([(["Og"], "banker")], world.member_aims)
        self.assertEqual([], world.slot_claims, "the leader walked for Og")

    def test_the_run_and_the_queue_are_asked_before_the_aim_is_written(self):
        world = _run_bank(_World())
        self.assertIn("queue", world.asked)
        self.assertIn("run", world.asked)

    def test_only_a_members_own_banker_errand_is_handed_back(self):
        world = _run_bank(_World())
        self.assertEqual(
            [("Bork", "banker"), ("Grug", "banker"), ("Ugga", "banker")],
            world.released,
        )

    def test_a_member_at_a_banker_has_its_row_written_and_is_not_aimed(self):
        world = _run_bank(_World(), counter=("Og",))
        self.assertEqual([], world.member_aims)
        self.assertEqual(["Og"], [who for who, _command in world.inserted])

    def test_a_linked_family_sends_its_leader_as_on_main(self):
        world = _run_bank(_World(jobs=LINKED))
        self.assertEqual([], world.member_aims)
        self.assertEqual([("bank", "Grug", "banker")], world.slot_claims)

    def test_a_queue_that_owns_the_job_sends_the_leader_as_on_main(self):
        world = _run_bank(_World(queue_owns=True))
        self.assertEqual([], world.member_aims)
        self.assertEqual([("bank", "Grug", "banker")], world.slot_claims)

    def test_a_family_the_setting_does_not_name_is_unchanged(self):
        world = _run_bank(_World(), environ={individual.ENV: ""})
        self.assertEqual([], world.member_aims)
        self.assertEqual([("bank", "Grug", "banker")], world.slot_claims)
        self.assertEqual([], [a for a in world.asked if a == "queue"])


BOX = {"map_id": 1, "x": 100.0, "y": 0.0, "z": 5.0, "d2": 0.0}
BOX_AIM = travel.ground_aim(1, 100.0, 0.0, 5.0)


def _run_mail(world, standing=None, environ=GRUG):
    this = world.bridge_self()
    far = {"map_id": 1, "pos_x": 900.0, "pos_y": 0.0, "pos_z": 5.0}
    standing = standing or {}
    takes = (
        mailrun.Take("Og", mailrun.TAKE_MONEY, 7, 0, "copper waiting"),
        mailrun.Take("Ugga", mailrun.TAKE_MONEY, 8, 0, "copper waiting"),
    )
    with (
        mock.patch.dict(os.environ, environ),
        mock.patch.object(
            bridge.mailrun, "letters_from_rows", lambda rows, names: ["a letter"]
        ),
        mock.patch.object(
            bridge.mailrun, "plan", lambda *a, **k: mailrun.Plan(takes=takes)
        ),
        mock.patch.object(bridge.mailrun, "gear_waiting", lambda letters: {}),
        mock.patch.multiple(
            bridge,
            _fetch_mail=lambda names: [],
            _recent_mail_keys=lambda minutes: set(),
            _fetch_free_slots=lambda names: {},
            _fetch_positions=lambda names: {n: standing.get(n, far) for n in names},
            _nearest_mailbox=lambda name: dict(BOX),
            _mail_range_refusals=lambda names, minutes: set(),
            _dues_fund_tab=lambda names: False,
            _insert_mail=lambda take, command: (
                world.inserted.append((take.character, command)) or 1
            ),
            **world.common(),
        ),
    ):
        asyncio.run(this._mail_once())
    return world


class TheMailPassActsPerMember(unittest.TestCase):
    def test_each_taker_is_aimed_at_its_own_mailbox(self):
        world = _run_mail(_World())
        self.assertEqual([(["Og"], BOX_AIM), (["Ugga"], BOX_AIM)], world.member_aims)
        self.assertEqual([], world.slot_claims, "the leader walked for them")

    def test_a_taker_already_at_a_mailbox_is_not_aimed(self):
        at_box = {"map_id": 1, "pos_x": 100.0, "pos_y": 0.0, "pos_z": 5.0}
        world = _run_mail(_World(), standing={"Og": at_box})
        self.assertEqual([(["Ugga"], BOX_AIM)], world.member_aims)

    def test_a_linked_family_sends_its_leader_as_on_main(self):
        world = _run_mail(_World(jobs=LINKED))
        self.assertEqual([], world.member_aims)
        self.assertEqual([("mail", "Grug", BOX_AIM)], world.slot_claims)

    def test_a_queue_that_owns_the_job_sends_the_leader_as_on_main(self):
        world = _run_mail(_World(queue_owns=True))
        self.assertEqual([], world.member_aims)
        self.assertEqual([("mail", "Grug", BOX_AIM)], world.slot_claims)


def _run_learn(world, environ=GRUG):
    this = world.bridge_self()
    with (
        mock.patch.dict(os.environ, environ),
        mock.patch.multiple(
            bridge,
            _learn_aim_rows=_learn_rows,
            _run_learn_aim_plan=lambda statements: (
                world.learn_statements.append(list(statements)) or len(statements)
            ),
            **world.common(),
        ),
    ):
        asyncio.run(this._reconcile_learn_aims())
    return world


class TheLearnTripActsPerMember(unittest.TestCase):
    def test_every_member_with_an_unwalked_errand_is_aimed(self):
        world = _run_learn(_World())
        self.assertEqual(
            [travel.aim_only_statements(["Og", "Ugga"], learnaim.TRAINER_ROLE)],
            world.learn_statements,
        )

    def test_a_linked_family_aims_nobody_but_its_leader(self):
        world = _run_learn(_World(jobs=LINKED))
        self.assertEqual([[]], world.learn_statements)

    def test_a_run_in_progress_aims_nobody_but_its_leader(self):
        world = _run_learn(_World(in_run=True))
        self.assertEqual([[]], world.learn_statements)

    def test_a_family_the_setting_does_not_name_is_unchanged(self):
        world = _run_learn(_World(), environ={individual.ENV: ""})
        self.assertEqual([[]], world.learn_statements)


if __name__ == "__main__":
    unittest.main()
