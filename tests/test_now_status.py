"""Each streamed character says what it is doing and what it is waiting for.

The operator watched two characters stand still on the Watch tab with nothing
on the card but "in Stormwind" and "inside an instance", and could not tell a
hold from a fault. These tests pin the sentence, the steps behind it, the
rule that a missing reason is spoken aloud, and the plumbing that carries it
from the bridge's log and the module's intent book to the tile.

The fixtures are the shapes seen on the dev realm: a leader whose dungeon walk
ends and starts again every few seconds, and a leader held for bag room.
"""

import logging
import os
import re
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import nowstatus  # noqa: E402
import watchwall  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = 1_000_000


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def step(
    subject, doing, waiting="", scope="character", kind="x", times=1, first=60, last=10
):
    return {
        "subject": subject,
        "scope": scope,
        "kind": kind,
        "doing": doing,
        "waiting": waiting,
        "occurrences": times,
        "first_at": NOW - first,
        "last_at": NOW - last,
        "now_at": NOW,
    }


ROSTER = [
    {
        "name": "Zug",
        "family": "Zug",
        "enabled": 1,
        "job": "dungeon:shadowfang",
        "dungeon_runs_wanted": 10,
        "dungeon_runs_done": 3,
    },
    {"name": "Oz", "family": "Zug", "enabled": 1, "job": "quest"},
    {"name": "Grug", "family": "Grug", "enabled": 1, "job": "town run"},
    {"name": "Bork", "family": "Grug", "enabled": 1, "job": "quest"},
    {"name": "Idler", "family": "Idler", "enabled": 1, "job": "quest"},
    {"name": "Off", "family": "Off", "enabled": 0, "job": "quest"},
]
INTENTS = [
    {
        "leader_name": "Zug",
        "family": "Zug",
        "current_kind": "dungeon",
        "current_owner": "dungeon run",
        "current_target": "trigger:194",
        "current_for": 20,
        "members_state": "Oz|following|9\nZork|held too far to walk|another map",
    },
    {
        "leader_name": "Grug",
        "family": "Grug",
        "current_kind": "errand",
        "current_owner": "travel column",
        "current_target": "at:0:-8815.2,652.9,94.9",
        "current_for": 300,
        "members_state": "Bork|following|9",
    },
]
NAMES = ["Zug", "Oz", "Grug", "Bork", "Idler", "Off"]


def facts(steps=()):
    return nowstatus.build_facts(NAMES, ROSTER, INTENTS, list(steps), NOW)


def line_of(name, steps=(), **member):
    m = {"name": name, "present": True, "condition": "ok"}
    m.update(member)
    return nowstatus.compose(m, facts(steps)[name])


class TheLogTapReadsTheBridgesOwnReasons(unittest.TestCase):
    def one(self, message):
        got = nowstatus.classify(message)
        self.assertEqual(len(got), 1, message)
        return got[0]

    def test_bag_room_wait_belongs_to_the_family(self):
        s = self.one(
            "dungeon quests: Grug's family waits for bag room; the vendor trip keeps the travel column"
        )
        self.assertEqual((s.subject, s.scope, s.kind), ("Grug", "family", "bag_room"))
        self.assertIn("the vendor trip keeps the travel column", s.waiting)

    def test_withheld_queue_keeps_the_reason_verbatim(self):
        s = self.one(
            "queue: Grug's family: withheld: bags are near full, and a run started now would be evacuated before it could progress"
        )
        self.assertEqual(s.kind, "queue_held")
        self.assertTrue(s.waiting.startswith("bags are near full"))

    def test_standin_and_pace_and_town_lines(self):
        s = self.one(
            "standin: Grug's family: no guest at scarlet-library; the family runs four-handed"
        )
        self.assertIn("no guest at scarlet-library", s.doing)
        s = self.one(
            "pace: Grug's family: Scarlet Monastery (the Library) holds (no fought run yet)"
        )
        self.assertEqual(s.waiting, "no fought run yet")
        s = self.one(
            "activity: Grug's family waits in town for its campaign, so sell runs under job=town run rather than job=quest"
        )
        self.assertEqual(s.kind, "town_wait")
        s = self.one(
            "town slot: town errand takes the traveller Grug for 'at:0:-8815.2,652.9,94.9'; the column was free"
        )
        self.assertEqual((s.subject, s.scope), ("Grug", "character"))
        self.assertIn("a spot on the map", s.doing)

    def test_character_lines(self):
        s = self.one(
            "equip: Grug still carries Imperial Leather Bracers after 3 equip command(s); held until the memory window passes"
        )
        self.assertEqual((s.subject, s.scope), ("Grug", "character"))
        self.assertIn("3 tries", s.waiting)
        s = self.one(
            "economy: 2 carried candidate(s) for Bork but no vendor within reach - leader=Grug aim taken=False"
        )
        self.assertEqual((s.subject, s.waiting), ("Bork", "a vendor within reach"))

    def test_unrelated_lines_make_no_step(self):
        for text in (
            "protect: covering 5 (Bork, Grog, Grug, Og, Ugga), refreshed 0 this cycle",
            "the dungeon quests: Grug's family waits for bag room; x",
            "",
        ):
            self.assertEqual(nowstatus.classify(text), [], text)

    def test_the_handler_collects_without_io_and_drains_once(self):
        logger = logging.getLogger("now-status-test")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        tap = nowstatus.NowTap()
        logger.addHandler(tap)
        try:
            logger.info(
                "dungeon quests: %s's family waits for bag room; %s", "Zug", "x"
            )
            logger.info("something else entirely")
        finally:
            logger.removeHandler(tap)
        got = tap.drain()
        self.assertEqual([s.subject for s in got], ["Zug"])
        self.assertEqual(tap.drain(), [])


class TheIntentBookBecomesSteps(unittest.TestCase):
    def row(self, kind="dungeon", target="trigger:194", age=20):
        return {
            "leader_name": "Zug",
            "current_kind": kind,
            "current_owner": "dungeon run",
            "current_target": target,
            "current_for": age,
        }

    def test_first_sighting_records_what_holds_now(self):
        got = nowstatus.intent_steps(None, self.row())
        self.assertEqual(len(got), 1)
        self.assertIn("took over: walking to trigger 194", got[0].doing)

    def test_same_walk_later_is_nothing(self):
        self.assertEqual(nowstatus.intent_steps(self.row(age=20), self.row(age=30)), [])

    def test_same_walk_begun_again_is_an_end_and_a_start(self):
        got = nowstatus.intent_steps(self.row(age=38), self.row(age=4))
        self.assertEqual(len(got), 2)
        self.assertIn("ended", got[0].doing)
        self.assertIn("took over", got[1].doing)
        # No duration in the text, so the loop dedupes into a count.
        self.assertFalse(re.search(r"\d+ s", got[0].doing))

    def test_a_different_walk_ends_one_and_starts_the_other(self):
        got = nowstatus.intent_steps(
            self.row(), self.row(kind="economy", target="vendor")
        )
        self.assertEqual(len(got), 2)
        self.assertIn("the vendor", got[1].doing)

    def test_going_idle_records_only_the_end(self):
        got = nowstatus.intent_steps(self.row(), self.row(kind="none", target=""))
        self.assertEqual(len(got), 1)
        self.assertIn("ended", got[0].doing)


class TheSentenceNamesTheWork(unittest.TestCase):
    def test_a_restarting_walk_says_so_with_a_count_and_a_clock(self):
        took = step(
            "Zug",
            "dungeon run took over: walking to trigger 194 for the dungeon run",
            kind="intent",
            times=6,
            first=240,
            last=20,
        )
        got = line_of("Zug", [took])
        self.assertEqual(
            got["line"],
            "Doing: Walking to trigger 194 for the dungeon run. Waiting for: a way "
            "there; the walk has ended and restarted 6 times (for 4 min).",
        )
        self.assertTrue(got["known"])

    def test_a_bag_room_wait_reaches_the_leader_and_the_follower(self):
        held = step(
            "Grug",
            "Clearing bag space before the dungeon quests",
            "bag room (the vendor trip keeps the travel column)",
            scope="family",
            kind="bag_room",
            times=9,
            first=240,
            last=30,
        )
        lead = line_of("Grug", [held])
        self.assertIn(
            "Waiting for: bag room (the vendor trip keeps the travel column) (for 4 min).",
            lead["line"],
        )
        self.assertTrue(lead["line"].startswith("Doing: Walking to a spot on the map"))
        follower = line_of("Bork", [held])
        self.assertIn("Doing: Following Grug (9 yards behind).", follower["line"])
        self.assertIn("bag room", follower["line"])

    def test_a_follower_waits_for_its_leader(self):
        self.assertEqual(
            line_of("Oz")["line"],
            "Doing: Following Zug (9 yards behind). Waiting for: Zug to move on.",
        )

    def test_a_stale_step_no_longer_counts(self):
        old = step(
            "Grug",
            "Clearing bag space",
            "bag room",
            scope="family",
            first=5000,
            last=4000,
        )
        self.assertNotIn("bag room", line_of("Grug", [old])["line"])

    def test_the_job_speaks_when_nothing_else_does(self):
        solo = nowstatus.build_facts(["Zug"], ROSTER, [], [], NOW)["Zug"]
        got = nowstatus.compose({"name": "Zug", "present": True}, solo)
        self.assertIn("On the shadowfang dungeon job (run 4 of 10)", got["doing"])
        self.assertIn("Waiting for: nothing it reports.", got["line"])

    def test_urgent_states_come_first(self):
        self.assertTrue(
            line_of("Zug", condition="dead")["line"].startswith("Doing: Dead.")
        )
        self.assertTrue(
            line_of("Zug", combat=True)["line"].startswith("Doing: Fighting.")
        )


class AMissingReasonIsSaidAloud(unittest.TestCase):
    def test_no_errand_and_no_hold_is_a_sentence_not_a_blank(self):
        got = line_of("Idler")
        self.assertEqual(got["line"], "Idle: no errand and no hold found.")
        self.assertFalse(got["known"])

    def test_a_character_the_feed_never_heard_of_is_idle_too(self):
        got = nowstatus.compose({"name": "Stranger", "present": True}, None)
        self.assertEqual(got["line"], "Idle: no errand and no hold found.")

    def test_logged_out_is_not_idle(self):
        got = line_of("Idler", present=False)
        self.assertEqual(got["line"], "Doing: Logged out. Waiting for: a login.")
        off = line_of("Off", present=False)
        self.assertIn("switched on in the roster", off["line"])

    def test_an_unreadable_feed_says_so(self):
        self.assertIn("did not answer", nowstatus.unavailable()["line"])


class TheSheetListsTheLastFiveSteps(unittest.TestCase):
    def test_five_newest_first_with_counts_and_ages(self):
        steps = [
            step(
                "Zug",
                "step %d" % i,
                last=10 * i + 1,
                first=10 * i + 2,
                times=1 + (i == 0),
            )
            for i in range(7)
        ]
        got = line_of("Zug", steps)["steps"]
        self.assertEqual(len(got), 5)
        self.assertEqual([g["text"] for g in got], ["step %d" % i for i in range(5)])
        self.assertEqual(got[0]["times"], 2)
        self.assertEqual(got[0]["ago_s"], 1)
        self.assertEqual(got[0]["at"], NOW - 1)

    def test_a_wait_reads_as_what_was_tried_and_what_it_waits_for(self):
        got = line_of(
            "Grug", [step("Grug", "Selling in town", "the family's dungeon campaign")]
        )
        self.assertEqual(
            got["steps"][0]["text"],
            "Selling in town: waiting for the family's dungeon campaign",
        )


class TheTileCarriesIt(unittest.TestCase):
    def members(self):
        base = {"present": True, "condition": "ok", "broadcast_url": "http://x/y"}
        return [("", {"members": [dict(base, name="Idler"), dict(base, name="Zug")]})]

    def test_each_tile_has_a_now_when_facts_are_given(self):
        wall = watchwall.build_heads(self.members(), facts=facts())["wall"]
        self.assertEqual(
            {t["name"]: t["now"]["known"] for t in wall["tiles"]},
            {"Idler": False, "Zug": True},
        )

    def test_an_unreadable_feed_marks_every_tile(self):
        wall = watchwall.build_heads(self.members(), facts=False)["wall"]
        for t in wall["tiles"]:
            self.assertIn("did not answer", t["now"]["line"])

    def test_callers_without_facts_get_no_now_key(self):
        wall = watchwall.build_heads(self.members())["wall"]
        for t in wall["tiles"]:
            self.assertNotIn("now", t)


class ThePlumbingIsConnected(unittest.TestCase):
    def test_the_bridge_runs_the_loop_in_both_loop_lists(self):
        src = read("bridge.py")
        self.assertEqual(src.count("                self._now_loop,\n"), 2)
        self.assertIn("log.addHandler(NOW_TAP)", src)
        self.assertIn("nowstatus.CREATE_SQL", src)

    def test_the_site_reads_the_feed_for_the_wall(self):
        src = read("map_server.py")
        self.assertIn("facts=facts)", src)
        self.assertIn("nowstatus.READ_SQL", src)

    def test_the_store_bumps_an_identical_step_instead_of_inserting(self):
        bridge = _import_bridge()

        class Cur:
            def __init__(self):
                self.sql = []
                self.lastrowid = 7

            def execute(self, sql, args=()):
                self.sql.append(sql.split(" ")[0] + " " + sql.split(" ")[1])

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        cur = Cur()

        class Conn:
            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False

            def cursor(self_):
                return cur

        one = nowstatus.Step("Zug", "family", "bag_room", "a", "b")
        seen = {}
        with mock.patch.object(bridge, "_connect", return_value=Conn()):
            bridge._store_now_steps([one], seen, 100.0)
            bridge._store_now_steps([one], seen, 160.0)
            bridge._store_now_steps(
                [one], seen, 160.0 + nowstatus.SAME_STEP_SECONDS + 1
            )
        inserts = [s for s in cur.sql if s.startswith("INSERT")]
        bumps = [s for s in cur.sql if s.startswith("UPDATE")]
        self.assertEqual((len(inserts), len(bumps)), (2, 1))


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


class ThePageShowsItOnAPhone(unittest.TestCase):
    def test_the_new_files_are_ascii(self):
        for name in ("nowstatus.py", "tests/test_now_status.py"):
            read(name).encode("ascii")


if __name__ == "__main__":
    unittest.main()
