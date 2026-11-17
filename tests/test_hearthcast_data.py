"""The stone, cooldown and pulse reads behind hearthcast (#2333).

Pinned here: what each statement asks for, how its rows are read, and that a
read which fails leaves its own fact unread, says so once, and never raises.
"""

import unittest

import hearthcast_data as hd


class Cursor:
    """Answers each statement by the table it names; a table mapped to an
    exception raises it."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []
        self._rows = []

    def execute(self, sql, args):
        self.asked.append((sql, tuple(args)))
        for table, answer in self.answers.items():
            if table in sql:
                if isinstance(answer, Exception):
                    raise answer
                self._rows = answer
                return
        self._rows = []

    def fetchall(self):
        return self._rows


class Log:
    def __init__(self):
        self.lines = []

    def warning(self, fmt, *args):
        self.lines.append(fmt % args)


STONES = [{"name": "Grug", "stones": 1}]
COOLDOWNS = [{"name": "Bork", "ends_at": 1700003600, "read_at": 1700000000}]
PULSE = [
    {"name": "Grug", "health": 3200, "has_corpse": 0},
    {"name": "Bork", "health": 1, "has_corpse": 1},
]
ALL = {
    "character_inventory": STONES,
    "character_spell_cooldown": COOLDOWNS,
    "overseer_snapshot": PULSE,
}


class TheRows(unittest.TestCase):
    def test_a_carried_stone_is_a_name(self):
        rows = [
            {"name": "Grug", "stones": 1},
            {"name": "Og", "stones": 2},
            {"name": "Bork", "stones": 0},
            {"name": None, "stones": 1},
            {"name": "Zug", "stones": None},
        ]
        self.assertEqual(frozenset({"Grug", "Og"}), hd.stones_from_rows(rows))
        self.assertEqual(frozenset(), hd.stones_from_rows(None))

    def test_a_running_cooldown_is_seconds_left(self):
        self.assertEqual({"Bork": 3600.0}, hd.cooldowns_from_rows(COOLDOWNS))

    def test_a_cooldown_row_with_no_clock_is_still_a_cooldown(self):
        rows = [
            {"name": "Bork", "ends_at": None, "read_at": None},
            {"name": "Og", "ends_at": "soon", "read_at": 5},
            {"name": "", "ends_at": 9, "read_at": 5},
        ]
        self.assertEqual({"Bork": 1.0, "Og": 1.0}, hd.cooldowns_from_rows(rows))
        self.assertEqual({}, hd.cooldowns_from_rows(()))

    def test_a_ghost_and_a_corpse_are_not_alive(self):
        rows = [
            {"name": "Grug", "health": 3200, "has_corpse": 0},
            {"name": "Ghost", "health": 1, "has_corpse": 1},
            {"name": "Corpse", "health": 0, "has_corpse": 1},
            # Raised before the corpse turned to bones: alive at full health.
            {"name": "Raised", "health": 2900, "has_corpse": 1},
            # One health and no corpse is a living member that is nearly dead.
            {"name": "Hurt", "health": 1, "has_corpse": 0},
            {"name": "Unread", "health": None, "has_corpse": None},
            {"name": None, "health": 100, "has_corpse": 0},
        ]
        self.assertEqual(
            {
                "Grug": True,
                "Ghost": False,
                "Corpse": False,
                "Raised": True,
                "Hurt": True,
                "Unread": False,
            },
            hd.alive_from_rows(rows),
        )


class TheStatements(unittest.TestCase):
    def test_the_stone_is_looked_for_where_the_core_looks(self):
        sql = hd.STONES_SQL
        self.assertIn("ii.itemEntry = %%s", sql)
        # The backpack and the four worn bags, and never the bank.
        self.assertIn("ci.slot BETWEEN 23 AND 38", sql)
        self.assertIn("bag.slot BETWEEN 19 AND 22", sql)
        self.assertNotIn("39", sql)

    def test_the_cooldown_is_the_stones_and_still_running(self):
        sql = hd.COOLDOWNS_SQL
        self.assertIn("sc.item = %%s OR sc.spell = %%s", sql)
        self.assertIn("sc.time > UNIX_TIMESTAMP()", sql)

    def test_the_pulse_is_a_fresh_snapshot_with_its_corpse(self):
        sql = hd.PULSE_SQL
        self.assertIn("FROM overseer_snapshot s", sql)
        self.assertIn("INTERVAL 60 SECOND", sql)
        self.assertIn("FROM corpse k WHERE k.guid = s.guid", sql)

    def test_no_statement_writes(self):
        for sql in (hd.STONES_SQL, hd.COOLDOWNS_SQL, hd.PULSE_SQL):
            self.assertTrue(sql.startswith("SELECT "))
            for verb in ("INSERT", "UPDATE", "DELETE", "REPLACE"):
                self.assertNotIn(verb, sql.upper().replace("UPDATED_AT", ""))


class TheRead(unittest.TestCase):
    def setUp(self):
        hd._SAID_FAILED.clear()
        self.addCleanup(hd._SAID_FAILED.clear)

    def test_three_reads_become_the_facts(self):
        cur = Cursor(ALL)
        facts = hd.read(cur, ["Grug", "Bork"])
        self.assertEqual(frozenset({"Grug"}), facts.stones)
        self.assertEqual({"Bork": 3600.0}, facts.cooldowns)
        self.assertEqual({"Grug": True, "Bork": False}, facts.alive)

    def test_every_value_is_bound(self):
        cur = Cursor(ALL)
        hd.read(cur, ["Grug", "Bork"])
        by_table = {
            table: args
            for sql, args in cur.asked
            for table in ALL
            if "JOIN %s" % table in sql or "FROM %s" % table in sql
        }
        self.assertEqual(
            ("Bork", "Grug", hd.HEARTHSTONE_ITEM), by_table["character_inventory"]
        )
        self.assertEqual(
            ("Bork", "Grug", hd.HEARTHSTONE_ITEM, hd.HEARTHSTONE_SPELL),
            by_table["character_spell_cooldown"],
        )
        self.assertEqual(("Bork", "Grug"), by_table["overseer_snapshot"])
        for sql, args in cur.asked:
            self.assertEqual(sql.count("%s"), len(args))
            self.assertNotIn("Grug", sql)

    def test_nobody_asked_reads_nothing(self):
        cur = Cursor(ALL)
        self.assertEqual(hd.Facts(frozenset(), {}, {}), hd.read(cur, []))
        self.assertEqual([], cur.asked)

    def test_a_failed_read_leaves_only_its_own_fact_unread(self):
        for table, field in (
            ("character_inventory", "stones"),
            ("character_spell_cooldown", "cooldowns"),
            ("overseer_snapshot", "alive"),
        ):
            with self.subTest(table):
                hd._SAID_FAILED.clear()
                log = Log()
                cur = Cursor(dict(ALL, **{table: RuntimeError("gone away")}))
                facts = hd.read(cur, ["Grug", "Bork"], log)
                unread = [
                    f
                    for f in ("stones", "cooldowns", "alive")
                    if getattr(facts, f) is None
                ]
                self.assertEqual([field], unread)
                self.assertEqual(1, len(log.lines))
                self.assertIn("could not be read (RuntimeError)", log.lines[0])

    def test_a_failed_read_is_said_once_and_again_after_it_recovers(self):
        log = Log()
        broken = Cursor(dict(ALL, character_inventory=RuntimeError("gone away")))
        hd.read(broken, ["Grug"], log)
        hd.read(broken, ["Grug"], log)
        self.assertEqual(1, len(log.lines))
        self.assertEqual(
            "hearth cast: the carried hearthstone could not be read "
            "(RuntimeError); no hearthstone hub is kept on it",
            log.lines[0],
        )
        hd.read(Cursor(ALL), ["Grug"], log)
        hd.read(broken, ["Grug"], log)
        self.assertEqual(2, len(log.lines))

    def test_a_failed_read_with_no_log_does_not_raise(self):
        broken = Cursor({t: RuntimeError("gone away") for t in ALL})
        self.assertEqual(hd.Facts(), hd.read(broken, ["Grug"]))


if __name__ == "__main__":
    unittest.main()
