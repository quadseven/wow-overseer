"""What the family is doing, chosen by Jev from the module's table.

Measured on the dev realm, 2026-09-26 02:07-02:14 UTC: the Alliance leader was
held for a regroup, sent to a banker 2,933 yards away, and asked to go back
for Og, 6,400 yards away and held there, inside two minutes, each by a
different rule of mod-overseer on its own poll. The module now keeps one
intent book per leader and publishes the requests on its table; this kind
lets Jev pick between them. Every test runs on fake rows and a fake Jev
transport; none touches a database or the API.
"""

import asyncio
import pathlib
import types
import unittest

from test_campaign_queue import _load  # sets up the pymysql stub
from test_jev_items import FakeJev

import jev  # noqa: E402
import jev_family_intent as jfi  # noqa: E402
import jevview  # noqa: E402
import situation as sit  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

# The measured moment, as the module would publish it: the regroup for Ugga
# holds him, the banker walk and the walk back for Og are asking.
TABLE = "\n".join(
    [
        "fetch|fetch|Og",
        "regroup|regroup|Ugga",
        "economy|travel column|banker",
    ]
)
MEMBERS = "\n".join(
    [
        "Bork|following|12",
        "Grog|walking back to the leader|40",
        "Og|held where it stands, too far to walk back|6409",
        "Ugga|walking back to the leader|4863",
    ]
)


def raw(**kw):
    row = dict(
        leader_name="Grug",
        family="Grug",
        current_kind="regroup",
        current_owner="regroup",
        current_target="Ugga",
        current_for=40,
        on_the_table=TABLE,
        goal_yards=2933,
        members_state=MEMBERS,
        module_age=10,
        chosen_kind="",
        chosen_target="",
        chosen_by="",
        changes=3,
    )
    row.update(kw)
    return row


def facts(**kw):
    return jfi.Facts(family="Grug", row=jfi.row_from_db(raw(**kw)))


def ask(f, fake=None, environ=None):
    client = jev.Client("k", transport=fake or FakeJev())
    return asyncio.run(jfi.ask(client, f, jfi.policy(environ or {})))


class TheTable(unittest.TestCase):
    def test_every_request_on_the_table_is_an_option(self):
        offered = jfi.options(facts())
        self.assertEqual({"fetch:Og", "regroup:Ugga", "economy:banker"}, set(offered))

    def test_a_member_option_says_what_is_being_done_with_it(self):
        offered = jfi.options(facts())
        self.assertIn("too far to walk back", offered["fetch:Og"])
        self.assertIn("6409 yards", offered["fetch:Og"])
        self.assertIn("what the leader is doing now", offered["regroup:Ugga"])

    def test_the_run_and_the_operator_are_never_offered(self):
        f = facts(
            on_the_table="dungeon|dungeon run|door\noperator|operator|stay\nquest|quest drive|"
        )
        self.assertEqual({"quest"}, set(jfi.options(f)))

    def test_the_heuristic_is_the_modules_static_order(self):
        # A standing Jev pick reorders the module's own table; the heuristic
        # re-sorts by the static ranks so it is what the book does unpicked.
        f = facts(on_the_table="economy|travel column|banker\nregroup|regroup|Ugga")
        answer, why = jfi.heuristic(f)
        self.assertEqual("regroup:Ugga", answer)
        self.assertIn("static order", why)

    def test_option_ids_fit_the_api(self):
        f = facts(
            on_the_table="errand|travel column|" + "x" * 80 + "\nquest|quest drive|"
        )
        self.assertTrue(all(len(o) <= 40 for o in jfi.options(f)))


class WhenItIsAsked(unittest.TestCase):
    def test_a_real_choice_is_asked_once_then_waits(self):
        f = facts()
        self.assertTrue(jfi.due(f, "", -1e9, 1000.0))
        sig = jfi.signature(f)
        self.assertFalse(jfi.due(f, sig, 1000.0, 1100.0))
        self.assertTrue(jfi.due(f, sig, 1000.0, 1000.0 + jfi.ASK_SECONDS))

    def test_a_change_on_the_table_asks_again_soon(self):
        f = facts()
        sig = jfi.signature(f)
        g = facts(on_the_table="regroup|regroup|Ugga\neconomy|travel column|banker")
        self.assertFalse(jfi.due(g, sig, 1000.0, 1010.0))
        self.assertTrue(jfi.due(g, sig, 1000.0, 1000.0 + jfi.EVENT_SECONDS))

    def test_not_while_the_run_or_the_operator_holds_him(self):
        self.assertFalse(jfi.due(facts(current_kind="dungeon"), "", -1e9, 1000.0))
        self.assertFalse(jfi.due(facts(current_kind="operator"), "", -1e9, 1000.0))

    def test_not_on_a_stale_row_or_with_one_option(self):
        self.assertFalse(jfi.due(facts(module_age=600), "", -1e9, 1000.0))
        self.assertFalse(jfi.due(facts(module_age=None), "", -1e9, 1000.0))
        one = facts(on_the_table="quest|quest drive|")
        self.assertFalse(jfi.due(one, "", -1e9, 1000.0))


class WhatJevSees(unittest.TestCase):
    def test_the_question_carries_the_doing_the_errand_distance_and_the_members(self):
        f = facts()
        state, questions = jfi.question(f, jfi.options(f))
        self.assertEqual("regroup", state["doing_now"]["intent"])
        self.assertEqual(40, state["doing_now"]["for_seconds"])
        self.assertEqual(2933, state["doing_now"]["leader_yards_from_his_errand"])
        og = next(m for m in state["members"] if m["name"] == "Og")
        self.assertEqual("6409", og["yards_from_leader"])
        self.assertIn("intent", questions)

    def test_the_facts_column_names_the_holds(self):
        line = jfi.facts_line(facts())
        self.assertIn("errand 2933 yd", line)
        self.assertIn("Og held where it stands", line)


class WhoActs(unittest.TestCase):
    def test_a_confident_different_answer_is_the_pick(self):
        j = ask(facts(), FakeJev(picks={"intent": "economy:banker"}, confidence=0.9))
        self.assertEqual(jev.JEV, j.acted)
        self.assertEqual("economy:banker", j.pick)
        self.assertEqual(("economy", "banker"), jfi.pick_of(j.pick))

    def test_below_the_threshold_the_module_order_stands(self):
        j = ask(facts(), FakeJev(picks={"intent": "economy:banker"}, confidence=0.5))
        self.assertEqual(jev.HEURISTIC, j.acted)
        self.assertEqual("", j.pick)

    def test_agreeing_writes_no_pick(self):
        j = ask(facts(), FakeJev(picks={"intent": "fetch:Og"}, confidence=0.95))
        self.assertEqual(jev.BOTH, j.acted)
        self.assertEqual("", j.pick)

    def test_off_asks_nothing(self):
        self.assertIsNone(ask(facts(), environ={"JEV_MODE_FAMILY_INTENT": "off"}))

    def test_the_record_has_the_judgment_shape(self):
        j = ask(facts(), FakeJev(picks={"intent": "economy:banker"}, confidence=0.9))
        self.assertEqual("family_intent", j.kind)
        self.assertEqual("Grug", j.holder)
        self.assertFalse(j.agree)
        self.assertTrue(j.probabilities_json())
        self.assertIn("Jev picks economy:banker", j.line())


class TheBridge(unittest.TestCase):
    def load(self, picks=None, confidence=0.9):
        written = {"pick": [], "clear": [], "judgment": []}
        ns = _load(
            ["_family_intent_for"],
            {
                "asyncio": asyncio,
                "time": __import__("time"),
                "jev_family_intent": jfi,
                "campaignqueue": __import__("campaignqueue"),
                "log": types.SimpleNamespace(
                    info=lambda *a: None, exception=lambda *a: None
                ),
                "_insert_jev_judgment": written["judgment"].append,
                "_write_family_pick": lambda *a: written["pick"].append(a) or 1,
                "_clear_family_pick": written["clear"].append,
            },
        )

        async def no_picture(*a):
            return None

        me = types.SimpleNamespace(
            _intent_seen={},
            _jev=jev.Client(
                "k", transport=FakeJev(picks=picks or {}, confidence=confidence)
            ),
            _situation_for=no_picture,
        )
        return ns, me, written

    def test_a_pick_is_written_for_the_leader(self):
        ns, me, written = self.load(picks={"intent": "economy:banker"})
        asyncio.run(
            ns["_family_intent_for"](me, "Grug", ["Grug"], raw(), jfi.policy({}))
        )
        self.assertEqual(1, len(written["judgment"]))
        self.assertEqual("Grug", written["pick"][0][0])
        self.assertEqual(("economy", "banker"), written["pick"][0][1:3])

    def test_a_standing_pick_the_latest_answer_does_not_back_is_cleared(self):
        ns, me, written = self.load(picks={"intent": "fetch:Og"})
        asyncio.run(
            ns["_family_intent_for"](
                me, "Grug", ["Grug"], raw(chosen_by="jev"), jfi.policy({})
            )
        )
        self.assertEqual([], written["pick"])
        self.assertEqual(["Grug"], written["clear"])

    def test_the_loop_runs_in_both_lists_and_has_a_label(self):
        self.assertEqual(2, BRIDGE.count("self._family_intent_loop,"))
        self.assertIn("family_intent", jevview.KINDS)

    def test_the_situation_carries_the_intent_book(self):
        self.assertIn('intent=reads.get("intent")', BRIDGE)
        self.assertIn("WHERE leader_name = %s", BRIDGE)


class TheSituationPicture(unittest.TestCase):
    """The shared picture every movement-related kind reads gains the facts
    the low-confidence judgments lacked."""

    def picture(self, **kw):
        rows = [
            dict(
                name="Grug",
                map_id=1,
                zone_id=440,
                pos_x=0.0,
                pos_y=0.0,
                pos_z=0.0,
                health=100,
                max_health=100,
                in_combat=0,
                age=2,
            ),
        ]
        tr = sit.Tracker()
        for i in range(8):
            tr.record("Grug", sit.Point(1, i * 20.0, 0.0, 0.0), i * 30.0)
        return sit.build(
            ("Grug",), "Grug", rows, tr, 210.0, leader_travel="banker", **kw
        )

    def test_a_role_errand_has_a_distance_when_the_module_resolved_it(self):
        w = self.picture(intent=raw())
        self.assertEqual(2933, w.goal_state()["yards"])
        self.assertIn("unknown", str(self.picture().goal_state()["yards"]))

    def test_the_leader_trail_is_numbers_not_only_a_verdict(self):
        state = self.picture().state()
        self.assertEqual(140, state["leader_trail"]["walked_yards"])

    def test_the_intent_book_is_in_the_picture(self):
        state = self.picture(intent=raw()).state()
        book = state["leader_intent"]
        self.assertEqual("regroup", book["doing"])
        self.assertIn("Og", book["members"])
        self.assertNotIn("Bork", book["members"])
        self.assertTrue(any("fetch Og" in a for a in book["also_asking"]))


if __name__ == "__main__":
    unittest.main()
