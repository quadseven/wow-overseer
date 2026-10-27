"""GET /api/v2/audit (#374): six player-level fields per member, read only.

The handler runs against a fake database connection through the realm
reader's database adapter, so every statement it sends is recorded: the
fields are pinned on a fixed set of rows, and every statement must be a
SELECT.
"""

import pathlib
import re
import sys
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import apiv2  # noqa: E402
import families as families_module  # noqa: E402
import realmread  # noqa: E402
from apiv2 import audit, presence  # noqa: E402
from apiv2._context import Context  # noqa: E402

NOW = 1_800_000_000
# A statement verb that writes or changes schema, as a whole word.
WRITES = re.compile(
    r"\b(INSERT|UPDATE|DELETE|REPLACE|ALTER|DROP|CREATE|TRUNCATE|GRANT)\b", re.I
)


class FakeCursor:
    """Answers each execute() with the rows of the first rule whose words are
    all in the statement, and records every statement it is given."""

    def __init__(self, rules, log):
        self.rules, self.log, self.rows = rules, log, []

    def execute(self, sql, params=()):
        self.log.append((sql, params))
        self.rows = []
        for words, rows in self.rules:
            if all(w in sql for w in words):
                self.rows = list(rows)
                return

    def fetchall(self):
        return list(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, rules, log):
        self.rules, self.log = rules, log

    def cursor(self):
        return FakeCursor(self.rules, self.log)

    def close(self):
        pass


# The roster is Grug and Ugga. Their guild also holds Bork, online now, and
# Stale, offline: Stale is not audited.
ROSTER = {"Grug": ["Grug", "Ugga"]}
GUILD = [
    {"guild_name": "Cave", "name": n, "level": lv, "class_id": 1}
    for n, lv in (("Grug", 20), ("Ugga", 18), ("Bork", 30), ("Stale", 40))
]
RULES = [
    (("lineup guild",), GUILD),
    (
        ("overseer_snapshot",),
        [
            {"name": "Grug", "health": 100, "max_health": 100, "at": NOW},
            {"name": "Bork", "health": 50, "max_health": 100, "at": NOW},
        ],
    ),
    (("playerFlags",), []),
    (
        ("leveltime",),
        [
            {"name": "Grug", "level": 20, "leveltime": 7200},
            {"name": "Ugga", "level": 18, "leveltime": 900},
            {"name": "Bork", "level": 30, "leveltime": None},
        ],
    ),
    (
        ("ItemLevel",),
        [
            # Grug: chest 18, legs 22, and a shirt and a tabard, which are not
            # stat slots and are not counted.
            {"name": "Grug", "slot": 4, "item_level": 18},
            {"name": "Grug", "slot": 6, "item_level": 22},
            {"name": "Grug", "slot": 3, "item_level": 1},
            {"name": "Grug", "slot": 18, "item_level": 1},
            # Bork wears all 17 stat slots at item level 30.
            *[
                {"name": "Bork", "slot": s, "item_level": 30}
                for s in range(19)
                if s not in (3, 18)
            ],
        ],
    ),
    (("wearable",), [{"name": "Grug", "wearable": 3}]),
    (("FROM mail",), [{"name": "Ugga", "letters": 2}]),
    (("overseer_death",), [{"name": "Ugga", "deaths": 7}]),
    (
        ("overseer_event",),
        [
            {"name": "Grug", "at": NOW - 3600},
            {"name": "Bork", "at": NOW - 60},
        ],
    ),
    (("now_at",), [{"now_at": NOW}]),
]


def run(rules=RULES, roster=ROSTER, guildmates=("Bork", "Stale")):
    log = []
    everyone = [n for names in roster.values() for n in names]
    store = families_module.MemoryStore(roster, {"Cave": everyone + list(guildmates)})
    fams = families_module.Families(store, fallback=lambda: [])
    srv = types.SimpleNamespace(_LINEUP_GUILD="SELECT lineup guild ({holes})")
    rd = realmread.Session(lambda: FakeConn(rules, log))
    ctx = Context(
        read=rd,
        server=srv,
        families=fams,
        presence=lambda names: presence.of(rd, names),
    )
    with rd:
        code, payload = apiv2.handle("/api/v2/audit", {}, ctx)
    return code, payload, log


class TheAudit(unittest.TestCase):
    def setUp(self):
        self.code, self.payload, self.log = run()
        self.by = {m["name"]: m for m in self.payload["members"]}

    def test_it_is_a_v2_route(self):
        self.assertIs(apiv2.ROUTES["/api/v2/audit"], audit.audit)
        self.assertEqual(self.code, 200)

    def test_every_roster_member_and_every_online_guild_member(self):
        self.assertEqual(sorted(self.by), ["Bork", "Grug", "Ugga"])
        self.assertTrue(self.by["Ugga"]["roster"])
        self.assertFalse(self.by["Ugga"]["online"])
        self.assertFalse(self.by["Bork"]["roster"])
        self.assertTrue(self.by["Bork"]["online"])

    def test_the_six_fields_are_pinned(self):
        self.assertEqual(
            self.by["Grug"],
            {
                "name": "Grug",
                "guild": "Cave",
                "roster": True,
                "online": True,
                "level": 20,
                "since_moved_s": 3600,
                "deaths_last_hour": 0,
                "slots_filled": 2,
                "slots": 17,
                "wearable_in_bags": 3,
                "item_level": 20.0,
                "mail_uncollected": 0,
                "hours_at_level": 2.0,
            },
        )
        ugga = self.by["Ugga"]
        # Ugga has no event of her own; her family (Grug's) moved an hour ago.
        self.assertEqual(ugga["since_moved_s"], 3600)
        self.assertEqual(ugga["deaths_last_hour"], 7)
        self.assertEqual(ugga["slots_filled"], 0)
        self.assertIsNone(ugga["item_level"])
        self.assertEqual(ugga["mail_uncollected"], 2)
        self.assertEqual(ugga["hours_at_level"], 0.2)
        bork = self.by["Bork"]
        self.assertEqual(bork["since_moved_s"], 60)
        self.assertEqual(bork["slots_filled"], 17)
        self.assertEqual(bork["item_level"], 30.0)
        self.assertIsNone(bork["hours_at_level"])

    def test_stalled_and_empty_slot_members_are_named(self):
        # Grug's family is quiet an hour (over agenda.STALL_AFTER), so both
        # of its members are named; Bork moved a minute ago.
        self.assertEqual(self.payload["stalled"], ["Grug", "Ugga"])
        self.assertEqual(self.payload["empty_slots"], ["Grug", "Ugga"])
        self.assertEqual(self.payload["checked_at"], NOW)

    def test_a_member_with_no_event_reads_its_family_not_unknown(self):
        # The Now page judges a stall per family: a follower with no event of
        # its own is as quiet as its family. Read alone it was None, unknown
        # and never stalled, while the Now page called the family stalled.
        self.assertEqual(self.by["Ugga"]["since_moved_s"], 3600)
        self.assertIn("Ugga", self.payload["stalled"])

    def test_a_family_with_no_event_at_all_is_unknown_not_stalled(self):
        rules = [r for r in RULES if r[0] != ("overseer_event",)]
        _code, payload, _log = run(rules=rules)
        by = {m["name"]: m for m in payload["members"]}
        self.assertIsNone(by["Grug"]["since_moved_s"])
        self.assertIsNone(by["Ugga"]["since_moved_s"])
        self.assertEqual(payload["stalled"], [])

    def test_a_boss_credit_is_movement_as_on_the_now_page(self):
        # A family repeating one dungeon writes no quest, level or equip; its
        # boss credit two minutes ago is its newest movement (#1314), so it is
        # not stalled, as the Now page says.
        credit = (
            ("overseer_dungeon_run_event",),
            [{"name": "Grug", "at": NOW - 120, "detail": "1 encounter credited"}],
        )
        _code, payload, log = run(rules=[credit, *RULES])
        by = {m["name"]: m for m in payload["members"]}
        self.assertEqual(by["Grug"]["since_moved_s"], 120)
        self.assertEqual(by["Ugga"]["since_moved_s"], 120)
        self.assertEqual(payload["stalled"], [])
        boss = [p for s, p in log if "overseer_dungeon_run_event" in s]
        self.assertEqual(boss, [("Grug", "Ugga", "boss")])

    def test_the_death_window_is_one_hour(self):
        deaths = [p for s, p in self.log if "overseer_death" in s]
        self.assertEqual(len(deaths), 1)
        self.assertEqual(deaths[0][-1], 3600)

    def test_it_issues_only_select_statements(self):
        self.assertGreaterEqual(len(self.log), 10)
        for sql, _ in self.log:
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)
            self.assertIsNone(WRITES.search(sql), sql)

    def test_an_empty_roster_reads_nothing(self):
        code, payload, log = run(roster={}, guildmates=())
        self.assertEqual((code, payload["members"], log), (200, [], []))


if __name__ == "__main__":
    unittest.main()
