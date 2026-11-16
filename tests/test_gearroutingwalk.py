"""The gear routing pass walks a waiting holder to a mailbox (#2503).

The executor writes a hand-over only when holder and wearer stand together or
the holder stands at a mailbox. A route that waits for neither is walked by the
guild mail-run machinery that already exists, and the letter goes to any guild
member because the guild post pass collects it (guildpost.py, #625).
"""

import pathlib
import unittest

import gearrouting as gr
import gearroutingexec as gx
import guildroute

HERE = pathlib.Path(__file__).resolve().parents[1]

NEAR = {"map_id": 0, "pos_x": 10.0, "pos_y": 10.0, "instance_id": 0}
FAR = {"map_id": 0, "pos_x": 900.0, "pos_y": 900.0, "instance_id": 0}


def route(holder="Cowpoke", wearer="Bigmon", guid=501, gain=0.4, item="Fez"):
    return gr.Route(
        wearer=wearer,
        holder=holder,
        guid=guid,
        entry=7001,
        item=item,
        slot="head",
        worn="Rags",
        worn_entry=1,
        gain=gain,
        reason="beats worn",
    )


def world(**kw):
    base = dict(
        carried={("Cowpoke", 501)},
        positions={"Cowpoke": NEAR, "Bigmon": FAR},
        at_mailbox=(),
        free_slots={"Bigmon": 3},
        family=frozenset({"Grug"}),
    )
    base.update(kw)
    return gx.World(**base)


class Rec:
    def __init__(self):
        self.rows = []

    def __call__(self, row):
        self.rows.append(row)
        return 1


class LettersGoToAnyGuildMember(unittest.TestCase):
    def test_a_postable_wearer_gets_a_letter_from_a_holder_at_a_mailbox(self):
        w = world(at_mailbox=("Cowpoke",), postable=frozenset({"Bigmon"}))
        rec = Rec()
        gx.execute(gr.Report(routes=(route(),)), w, rec)
        self.assertEqual([r.verb for r in rec.rows], ["mail"])

    def test_without_postable_only_family_is_posted_to(self):
        w = world(at_mailbox=("Cowpoke",))
        rec = Rec()
        result = gx.execute(gr.Report(routes=(route(),)), w, rec)
        self.assertEqual(rec.rows, [])
        self.assertEqual(result.steps[0].status, gx.WAITING)


class WhatIsWorthWalking(unittest.TestCase):
    def waiting(self, routes, w):
        result = gx.execute(gr.Report(routes=tuple(routes)), w, Rec())
        return gx.fetchable(result, w.postable or w.family)

    def test_a_route_apart_with_no_mailbox_is_fetchable_in_report_order(self):
        w = world(postable=frozenset({"Bigmon"}))
        got = self.waiting([route()], w)
        self.assertEqual(len(got), 1)
        one = got[0]
        self.assertEqual(
            (one.holder, one.taker, one.name, one.guid),
            ("Cowpoke", "Bigmon", "Fez", 501),
        )
        self.assertTrue(one.family)
        self.assertEqual(one.alternates, ())

    def test_what_is_not_apart_is_not_fetched(self):
        w = world(
            carried={("Cowpoke", 501), ("Cowpoke", 502), ("Cowpoke", 503)},
            positions={"Cowpoke": NEAR, "Bigmon": FAR, "Near": NEAR, "Full": NEAR},
            free_slots={"Bigmon": 3, "Near": 3, "Full": 0},
            postable=frozenset({"Bigmon", "Near", "Full"}),
        )
        routes = [
            route(holder=gr.BANK_HOLDER, guid=900),  # the bank cannot walk
            route(guid=999),  # not carried: stale
            route(wearer="Full", guid=502),  # beside it, but no bag slot
            route(wearer="Gone", guid=503),  # not in the world
        ]
        self.assertEqual(self.waiting(routes, w), [])

    def test_a_holder_beside_a_nonpostable_wearer_at_a_mailbox_is_not_walked(self):
        w = world(at_mailbox=("Cowpoke",))
        self.assertEqual(self.waiting([route()], w), [])

    def test_a_kept_piece_is_not_fetched(self):
        import keep

        kept = keep.Reservations(
            guids=frozenset({("cowpoke", 501)}), entries=frozenset()
        )
        w = world(kept=kept, postable=frozenset({"Bigmon"}))
        self.assertEqual(self.waiting([route()], w), [])

    def test_the_planner_the_guild_already_uses_takes_it_unchanged(self):
        w = world(postable=frozenset({"Bigmon"}))
        got = self.waiting([route()], w)
        walker = guildroute.Walker(
            name="Cowpoke",
            map_id=0,
            cohort="",
            yards=80.0,
            aim="at:0:1,2,3",
            by_row=True,
        )
        plan = guildroute.plan_mail_runs(
            got, {"Cowpoke": walker}, {}, 0, family_only=False
        )
        self.assertEqual(len(plan.runs), 1)
        self.assertEqual(plan.runs[0].taker, "Bigmon")
        self.assertEqual(plan.runs[0].guid, 501)


class WhoMayWalk(unittest.TestCase):
    def two(self):
        w = world(
            carried={("A", 1), ("B", 2), ("A", 3)},
            positions={"A": NEAR, "B": NEAR, "W": FAR},
            postable=frozenset({"W"}),
            free_slots={"W": 3},
        )
        routes = [
            route(holder="A", wearer="W", guid=1),
            route(holder="B", wearer="W", guid=2),
            route(holder="A", wearer="W", guid=3),
        ]
        result = gx.execute(gr.Report(routes=tuple(routes)), w, Rec())
        return gx.fetchable(result, w.postable)

    def test_a_busy_holder_is_not_walked_and_says_why(self):
        kept, notes = gx.walkable(self.two(), busy={"A"})
        self.assertEqual([r.holder for r in kept], ["B"])
        self.assertTrue(any("A" in n and "walk" in n for n in notes))

    def test_a_held_family_member_is_not_walked(self):
        kept, notes = gx.walkable(self.two(), held={"B"})
        self.assertEqual({r.holder for r in kept}, {"A"})
        self.assertTrue(any("operator hold" in n for n in notes))

    def test_one_route_per_holder(self):
        kept, _notes = gx.walkable(self.two())
        self.assertEqual([(r.holder, r.guid) for r in kept], [("A", 1), ("B", 2)])


class GearPhraseStillMatches(unittest.TestCase):
    def test_the_wait_note_gear_writes_ends_with_the_phrase_the_executor_reads(self):
        w = world(postable=frozenset({"Bigmon"}))
        result = gx.execute(gr.Report(routes=(route(),)), w, Rec())
        self.assertIn(gx.APART_NO_MAILBOX, result.steps[0].why)


class TheBridgeWalksThem(unittest.TestCase):
    def bridge(self):
        return (HERE / "bridge.py").read_text(encoding="utf-8")

    def body(self, name):
        text = self.bridge()
        start = text.index(name)
        end = text.find("\n    async def ", start + 1)
        return text[start:end]

    def test_the_pass_walks_after_it_writes(self):
        body = self.body("async def _gear_routing_once(")
        self.assertLess(
            body.index("gearroutingexec.execute"), body.index("_gear_routing_walks(")
        )
        self.assertIn("postable=", body)
        self.assertIn("self._guild_mail_runs", body)  # arrived walkers asked first

    def test_the_walk_step_goes_through_the_existing_door_with_its_own_budget(self):
        body = self.body("async def _gear_routing_walks(")
        for needle in (
            "gearroutingexec.fetchable(",
            "gearroutingexec.walkable(",
            "_operator_held(",
            "_walk_route_holders(",
            "family_only=False",
            "GEAR_ROUTING_WALKS_PER_DAY",
            "GEAR_ROUTING_WALKS_PER_PASS",
            "_job_steps",
            "_guild_run_names",
        ):
            self.assertIn(needle, body)
        for banned in ("travel_npc", "_write_trade_errand", "_insert_mail_walk"):
            self.assertNotIn(banned, body)

    def test_a_by_row_walk_is_checked_against_the_death_discs(self):
        body = self.body("async def _walk_route_holders(")
        self.assertIn("_member_death_disc_refusals", body)
        self.assertIn("per_day", body)
        self.assertIn("per_pass", body)

    def test_the_kill_switch_exists(self):
        self.assertIn('os.environ.get("GEAR_ROUTING_WALKS"', self.bridge())


if __name__ == "__main__":
    unittest.main()
