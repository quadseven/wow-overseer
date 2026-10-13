"""GET /api/v2/quests, /api/v2/quests/{id} and /api/v2/questers (#923), run
against the in-memory realm reader."""

import datetime
import pathlib
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import apiv2  # noqa: E402
import questcatalogue as qc  # noqa: E402
import questledger as ql  # noqa: E402
import realmread  # noqa: E402
from apiv2 import quests as v2quests  # noqa: E402

HORDE_ONLY = 2 | 16 | 32 | 128 | 512
ALLIANCE_ONLY = 1 | 4 | 8 | 64 | 1024
WHEN = datetime.datetime(2026, 10, 13, 9, 30, 0)


def quest(qid, level, sort, races=0):
    return {
        "quest": qid,
        "title": "Quest %d" % qid,
        "level": level,
        "min_level": max(1, level - 2),
        "sort": sort,
        "races": races,
        "classes": 0,
        "follows": 0,
    }


QUEST_ROWS = [
    quest(1, 5, 12, ALLIANCE_ONLY),  # Elwynn
    quest(2, 6, 12, ALLIANCE_ONLY),
    quest(3, 5, 14, HORDE_ONLY),  # Durotar
    quest(4, 15, 17),  # the Barrens, both sides
    quest(5, 64, 3483),  # Hellfire: never in the catalogue
]
GIVER_ROWS = [
    {"quest": q, "role": role, "map_id": m}
    for q, m in ((1, 0), (2, 0), (3, 1), (4, 1), (5, 530))
    for role in ("start", "end")
]


def entry(quest_id, guid, name, state, reason=""):
    return {
        "quest": quest_id,
        "guid": guid,
        "character_name": name,
        "state": state,
        "first_taken": WHEN,
        "finished": WHEN if state != "taken" else None,
        "reason": reason,
    }


LEDGER = [
    entry(1, 7, "Tharn", "completed"),
    entry(1, 8, "Mirra", "broken", ql.FAILED_REASON),
    entry(2, 8, "Mirra", "broken", ql.FAILED_REASON),
    entry(3, 21, "Grakk", "taken"),
]


class Ctx:
    def __init__(self, answers):
        self.read = realmread.Memory(answers)
        self.server = None


def answers(**extra):
    out = {
        qc.QUESTS_SQL: QUEST_ROWS,
        qc.GIVERS_SQL: GIVER_ROWS,
        v2quests.LEDGER_SQL: LEDGER,
        v2quests.QUEST_LEDGER_SQL: lambda args: [
            r for r in LEDGER if r["quest"] == args[0]
        ],
    }
    out.update(extra)
    return out


class Base(unittest.TestCase):
    def setUp(self):
        qc.forget()
        self.addCleanup(qc.forget)

    def get(self, path, query=None, **extra):
        return apiv2.handle(path, query or {}, Ctx(answers(**extra)))


class TheCatalogueEndpoint(Base):
    def test_every_ruleset_quest_with_its_status(self):
        code, body = self.get("/api/v2/quests")
        self.assertEqual(code, 200)
        by_id = {q["id"]: q for q in body["quests"]}
        self.assertEqual(sorted(by_id), [1, 2, 3, 4])
        self.assertEqual(by_id[1]["status"], "completed")
        self.assertEqual(by_id[1]["attempts"], 2)
        self.assertEqual(by_id[2]["status"], "broken")
        self.assertEqual(by_id[3]["status"], "taken")
        self.assertEqual(by_id[4]["status"], "not_reached")
        self.assertEqual(by_id[1]["zone_name"], "Elwynn Forest")
        self.assertEqual(by_id[1]["faction"], "alliance")

    def test_coverage_totals_overall_and_per_side(self):
        _, body = self.get("/api/v2/quests")
        self.assertEqual(
            body["totals"],
            {
                "quests": 4,
                "completed": 1,
                "broken": 1,
                "taken": 1,
                "abandoned": 0,
                "not_reached": 1,
            },
        )
        self.assertEqual(body["by_faction"]["alliance"]["quests"], 3)
        self.assertEqual(body["by_faction"]["alliance"]["completed"], 1)
        self.assertEqual(body["by_faction"]["horde"]["quests"], 2)
        self.assertEqual(body["by_faction"]["horde"]["taken"], 1)

    def test_filters(self):
        def ids(**query):
            _, body = self.get("/api/v2/quests", {k: [v] for k, v in query.items()})
            return [q["id"] for q in body["quests"]]

        self.assertEqual(ids(faction="horde"), [3, 4])
        self.assertEqual(ids(zone="12"), [1, 2])
        self.assertEqual(ids(level_min="10", level_max="20"), [4])
        self.assertEqual(ids(status="broken"), [2])
        self.assertEqual(ids(faction="alliance", status="not_reached"), [4])

    def test_the_status_filter_leaves_the_totals_whole(self):
        _, body = self.get("/api/v2/quests", {"status": ["completed"]})
        self.assertEqual(body["shown"], 1)
        self.assertEqual(body["totals"]["quests"], 4)

    def test_bad_filters_are_400(self):
        for query in (
            {"faction": ["pirates"]},
            {"zone": ["Elwynn"]},
            {"status": ["done"]},
            {"level_min": ["ten"]},
        ):
            self.assertEqual(self.get("/api/v2/quests", query)[0], 400, query)

    def test_a_realm_without_the_ledger_reads_not_reached(self):
        _, body = self.get(
            "/api/v2/quests", **{v2quests.LEDGER_SQL: realmread.MISSING_TABLE}
        )
        self.assertEqual(body["totals"]["not_reached"], 4)


class TheQuestEndpoint(Base):
    def test_one_quest_with_every_attempt(self):
        code, body = self.get("/api/v2/quests/1")
        self.assertEqual(code, 200)
        self.assertEqual(body["quest"]["id"], 1)
        self.assertEqual(body["quest"]["status"], "completed")
        self.assertEqual(
            body["attempts"],
            [
                {
                    "character": "Tharn",
                    "guid": 7,
                    "guild": "Cave",
                    "state": "completed",
                    "first_taken": "2026-10-13 09:30:00",
                    "finished": "2026-10-13 09:30:00",
                    "reason": "",
                },
                {
                    "character": "Mirra",
                    "guid": 8,
                    "guild": "Cave",
                    "state": "broken",
                    "first_taken": "2026-10-13 09:30:00",
                    "finished": "2026-10-13 09:30:00",
                    "reason": ql.FAILED_REASON,
                },
            ],
        )

    def test_a_quest_outside_the_catalogue_is_404(self):
        self.assertEqual(self.get("/api/v2/quests/5")[0], 404)
        self.assertEqual(self.get("/api/v2/quests/999")[0], 404)

    def test_a_bad_id_is_400(self):
        self.assertEqual(self.get("/api/v2/quests/abc")[0], 400)

    def test_the_path_id_beats_a_query_id(self):
        code, body = self.get("/api/v2/quests/4", {"id": ["1"]})
        self.assertEqual((code, body["quest"]["id"]), (200, 4))


CHARACTER_ROWS = [
    {
        "guid": 7,
        "name": "Tharn",
        "level": 6,
        "race": 4,
        "class": 11,
        "zone": 141,
        "online": 1,
    },
    {
        "guid": 21,
        "name": "Grakk",
        "level": 4,
        "race": 2,
        "class": 9,
        "zone": 14,
        "online": 0,
    },
]
LOG_ROWS = [
    {"guid": 7, "quest": 2, "status": 3},
    {"guid": 7, "quest": 1, "status": 1},
    {"guid": 21, "quest": 3, "status": 5},
    {"guid": 21, "quest": 4, "status": 0},
]
COUNT_ROWS = [
    {"guid": 7, "state": "completed", "n": 4},
    {"guid": 7, "state": "broken", "n": 1},
    {"guid": 21, "state": "taken", "n": 2},
]


class TheQuestersEndpoint(Base):
    def get_questers(self):
        return self.get(
            "/api/v2/questers",
            **{
                ql.CHARACTERS_SQL: CHARACTER_ROWS,
                ql.LOG_SQL: LOG_ROWS,
                v2quests.COUNTS_SQL: COUNT_ROWS,
            },
        )

    def test_lists_all_ten_questers(self):
        code, body = self.get_questers()
        self.assertEqual(code, 200)
        self.assertEqual([q["name"] for q in body["questers"]], ql.quester_names())

    def test_a_quester_on_the_realm(self):
        _, body = self.get_questers()
        tharn = body["questers"][0]
        self.assertEqual(
            tharn,
            {
                "name": "Tharn",
                "guild": "Cave",
                "present": True,
                "level": 6,
                "zone": 141,
                "zone_name": "Teldrassil",
                "online": True,
                "current": [
                    {"id": 1, "title": "Quest 1", "status": "complete"},
                    {"id": 2, "title": "Quest 2", "status": "incomplete"},
                ],
                "taken": 0,
                "completed": 4,
                "broken": 1,
                "abandoned": 0,
            },
        )
        grakk = next(q for q in body["questers"] if q["name"] == "Grakk")
        self.assertEqual(grakk["guild"], "Bonkers")
        self.assertEqual(
            grakk["current"], [{"id": 3, "title": "Quest 3", "status": "failed"}]
        )
        self.assertEqual(grakk["taken"], 2)

    def test_a_quester_not_recruited_yet(self):
        _, body = self.get_questers()
        mirra = next(q for q in body["questers"] if q["name"] == "Mirra")
        self.assertFalse(mirra["present"])
        self.assertIsNone(mirra["level"])
        self.assertEqual(
            (mirra["completed"], mirra["broken"], mirra["current"]), (0, 0, [])
        )

    def test_no_questers_on_the_realm_reads_no_logs(self):
        code, body = self.get("/api/v2/questers", **{ql.CHARACTERS_SQL: []})
        self.assertEqual(code, 200)
        self.assertFalse(any(q["present"] for q in body["questers"]))


class TheRoutes(unittest.TestCase):
    def test_the_three_paths_are_served(self):
        self.assertIs(apiv2.ROUTES["/api/v2/quests"], v2quests.quests)
        self.assertIs(apiv2.ROUTES["/api/v2/quests/{id}"], v2quests.quest)
        self.assertIs(apiv2.ROUTES["/api/v2/questers"], v2quests.questers)

    def test_a_path_under_no_template_is_still_404(self):
        self.assertEqual(apiv2.handle("/api/v2/roll/1", {}, None)[0], 404)
        self.assertEqual(apiv2.handle("/api/v2/quests/", {}, None)[0], 404)


if __name__ == "__main__":
    unittest.main()
