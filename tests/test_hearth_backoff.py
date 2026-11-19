"""A stranded member refused for its hearthstone's cooldown waits to be asked
again (#2183).

The guild run loop sends every stranded guild member home by hearthstone, and
the once-an-hour spacing counts only hearths that went through. A refusal is an
error row, so a member whose stone was on cooldown was due again on the very
next cycle, for as long as it stayed stranded. The decision to ask again is
guildrun.hearth_backed_off, tested on rows written here; the bridge pass that
asks is pinned as source. The members are invented.
"""

import pathlib
import unittest

import guildrun
import jev_movement
import modsource

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
MODULE = modsource.read(modsource.MODULE, errors="replace")

COOLDOWN = "hearthstone is on cooldown"


def newest(name, status="error", detail=COOLDOWN, age=60):
    return {"name": name, "status": status, "detail": detail, "age": age}


class ACooldownRefusalIsNotAskedAgainAtOnce(unittest.TestCase):
    def test_a_member_refused_for_the_cooldown_is_held_inside_the_back_off(self):
        rows = [newest("Bonk", age=guildrun.HEARTH_BACKOFF_SECONDS - 1)]
        self.assertEqual(guildrun.hearth_backed_off(rows), {"Bonk"})

    def test_it_is_due_again_when_the_back_off_has_passed(self):
        rows = [newest("Bonk", age=guildrun.HEARTH_BACKOFF_SECONDS)]
        self.assertEqual(guildrun.hearth_backed_off(rows), set())

    def test_one_member_held_does_not_hold_another(self):
        rows = [
            newest("Bonk", age=30),
            newest("Durg", age=guildrun.HEARTH_BACKOFF_SECONDS + 1),
        ]
        self.assertEqual(guildrun.hearth_backed_off(rows), {"Bonk"})

    def test_the_words_are_read_inside_a_longer_detail(self):
        rows = [newest("Bonk", detail="refused: %s (4 min left)" % COOLDOWN)]
        self.assertEqual(guildrun.hearth_backed_off(rows), {"Bonk"})


class OtherAnswersKeepToday(unittest.TestCase):
    def test_a_refusal_that_is_not_the_cooldown_is_asked_again_at_once(self):
        for words in ("character is moving", "character is already casting"):
            rows = [newest("Bonk", detail=words, age=5)]
            self.assertEqual(guildrun.hearth_backed_off(rows), set(), words)

    def test_a_hearth_that_went_through_is_not_a_back_off(self):
        rows = [newest("Bonk", status="applied", detail="", age=5)]
        self.assertEqual(guildrun.hearth_backed_off(rows), set())

    def test_no_row_means_due(self):
        self.assertEqual(guildrun.hearth_backed_off([]), set())


class TheBackOffIsBoundedAndPinned(unittest.TestCase):
    def test_it_never_outlasts_the_stones_own_cooldown(self):
        self.assertGreater(guildrun.HEARTH_BACKOFF_SECONDS, 0)
        self.assertLessEqual(
            guildrun.HEARTH_BACKOFF_SECONDS, jev_movement.HEARTH_COOLDOWN_SECONDS
        )

    def test_the_refusal_words_are_the_modules(self):
        self.assertEqual(guildrun.HEARTH_COOLDOWN_WORDS, COOLDOWN)
        self.assertIn('refuse("%s")' % guildrun.HEARTH_COOLDOWN_WORDS, MODULE)


class TheBridgePassAsksOnlyThoseNotBackedOff(unittest.TestCase):
    def setUp(self):
        body = BRIDGE[BRIDGE.index("def _hearth_stranded_guild_members") :]
        self.body = body[: body.index("\ndef ")]

    def test_it_reads_each_due_members_newest_hearth_row_for_its_own_source(self):
        sql = BRIDGE[BRIDGE.index("_GUILD_HEARTH_NEWEST = (") :]
        sql = sql[: sql.index("\n\n")]
        self.assertIn("kind = 'hearth'", sql)
        self.assertIn("source = %s", sql)
        self.assertIn("MAX(id)", sql)
        self.assertIn("guildrun.HEARTH_BACKOFF_SECONDS", sql)
        self.assertIn("_GUILD_HEARTH_NEWEST", self.body)
        self.assertIn("guildrun.SOURCE", self.body)

    def test_it_skips_the_backed_off_and_keeps_the_hourly_spacing(self):
        self.assertIn("guildrun.hearth_backed_off(", self.body)
        self.assertIn("_MOVEMENT_HEARTHED", self.body)
        self.assertIn("_insert_hearth(name, guildrun.SOURCE)", self.body)


TOWN_ERRAND = "overseer:town-errand"
NEXT_DEF = chr(10) + "def "


class TheTownErrandDoesNotRetryAStoneOnCooldownEveryPass(unittest.TestCase):
    """wow-dev 2026-11-17: 48 of the errand's hearth rows in eight hours were
    refused for the stone's cooldown, one a minute per member, because only
    the guild run asked the back-off before writing (#2183)."""

    def helper(self, rows):
        import ast
        import logging
        import types

        body = BRIDGE[BRIDGE.index("def _hearth_backed_off_names") :]
        body = body[: body.index(NEXT_DEF)]
        calls = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=()):
                calls.append((sql, params))

            def fetchall(self):
                return rows

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def cursor(self):
                return Cursor()

        ns = {
            "guildrun": guildrun,
            "_connect": Conn,
            "_GUILD_HEARTH_NEWEST": "SELECT %s WHERE n IN (%s)",
            "pymysql": types.SimpleNamespace(
                err=types.SimpleNamespace(MySQLError=Exception)
            ),
            "log": logging.getLogger("t"),
        }
        exec(compile(ast.parse(body), "bridge", "exec"), ns)  # noqa: S102
        return ns["_hearth_backed_off_names"], calls

    def test_a_member_refused_for_the_cooldown_is_held(self):
        ask, calls = self.helper([newest("Zork", age=60), newest("Oz", age=5000)])
        self.assertEqual(ask(["Zork", "Oz", "Uzza"], TOWN_ERRAND), {"Zork"})
        self.assertEqual(calls[0][1], (TOWN_ERRAND, "Zork", "Oz", "Uzza"))

    def test_a_refusal_for_moving_is_still_asked_again(self):
        ask, _ = self.helper([newest("Zork", detail="character is moving", age=5)])
        self.assertEqual(ask(["Zork"], TOWN_ERRAND), set())

    def test_the_regroup_holds_a_member_refused_as_moving_for_a_few_minutes(self):
        moving = "character is moving"
        rows = [newest("Zork", detail=moving, age=60)]
        ask, _ = self.helper(rows)
        seconds = guildrun.REGROUP_MOVING_BACKOFF_SECONDS
        self.assertEqual(ask(["Zork"], TOWN_ERRAND, seconds), {"Zork"})
        late = [newest("Zork", detail=moving, age=seconds)]
        ask, _ = self.helper(late)
        self.assertEqual(ask(["Zork"], TOWN_ERRAND, seconds), set())

    def test_the_regroup_passes_the_moving_back_off(self):
        regroup = BRIDGE[BRIDGE.index("async def _town_errand_regroup") :]
        regroup = regroup[: regroup.index("async def _town_errand_aim")]
        self.assertIn("guildrun.REGROUP_MOVING_BACKOFF_SECONDS", regroup)

    def test_nobody_asked_for_reads_nothing(self):
        ask, calls = self.helper([])
        self.assertEqual(ask([], TOWN_ERRAND), set())
        self.assertEqual(calls, [])

    def test_an_unreadable_table_holds_nobody(self):
        ask, _ = self.helper([])

        ask.__globals__["_connect"] = lambda: (_ for _ in ()).throw(
            ask.__globals__["pymysql"].err.MySQLError(2003)
        )
        self.assertEqual(ask(["Zork"], TOWN_ERRAND), set())

    def test_both_errand_hearth_writers_ask_first(self):
        for name in ("async def _town_errand_start", "async def _town_errand_regroup"):
            self.assertIn(name, BRIDGE, name)
        start = BRIDGE[
            BRIDGE.index("await asyncio.to_thread(_town_errand_jobs, names)") :
        ]
        start = start[: start.index("began = townerrand.start")]
        self.assertIn("_hearth_backed_off_names", start)
        regroup = BRIDGE[BRIDGE.index("async def _town_errand_regroup") :]
        regroup = regroup[: regroup.index("async def _town_errand_aim")]
        self.assertIn("_hearth_backed_off_names", regroup)
        self.assertIn("TOWN_ERRAND_SOURCE", regroup)


if __name__ == "__main__":
    unittest.main()
