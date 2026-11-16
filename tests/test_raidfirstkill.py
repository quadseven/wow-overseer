"""The first-kill order mode (#2570) and the seats the order is written from (#2104).

What these pin:

  1. THE DEFAULT ORDER IS UNCHANGED. Forty approved seats, all online at the
     door's level, or a refusal; the refusal now names the first-kill order as
     the way forward.
  2. A FIRST-KILL ORDER FORMS FROM THE ELIGIBLE SEATS. Online, at the level
     floor and in the approved lineup; nobody outside the lineup is brought
     in, every kept seat keeps its group and role, and the left-out seats are
     named, in the log line the bridge writes and on the Raid tab's card.
  3. A QUORUM BOUNDS IT. Below the configured seats, tanks or healers the
     order is refused, and nothing is written.
  4. THE FLAG RIDES THE QUEUE ENTRY from the order sentence to the writer.
"""

import contextlib
import unittest

from test_raidrun import DOOR, GUILD, _load_drive_raid  # noqa: F401

import campaignqueue  # noqa: E402
import raidlineup  # noqa: E402
import raidready  # noqa: E402
import raidrun  # noqa: E402

SMALL_QUORUM = (14, 1, 1)


def _lineup():
    return raidlineup.build_lineup(GUILD, guaranteed=["Grug"])


def _seat_names(lineup):
    return [m["name"] for g in lineup["groups"] for m in g["members"]]


def _rows(lineup, eligible):
    """Current character rows: the named seats online at 60, the rest offline."""
    names = _seat_names(lineup)
    return [
        {"name": n, "level": 60, "online": 1 if n in eligible else 0} for n in names
    ]


def _fourteen(lineup):
    """Two tanks, three healers and nine damage, by the lineup's own roles."""
    by_role = {"tank": [], "healer": [], "dps": []}
    for g in lineup["groups"]:
        for m in g["members"]:
            by_role.setdefault(m["role"], []).append(m["name"])
    return set(by_role["tank"][:2] + by_role["healer"][:3] + by_role["dps"][:9])


class TheDefaultOrderStillRefuses(unittest.TestCase):
    def test_fourteen_eligible_of_forty_refuse_and_name_the_first_kill_order(self):
        lineup = _lineup()
        rows = _rows(lineup, _fourteen(lineup))
        refusal = raidrun.seat_eligibility_refusal("moltencore", lineup, rows)
        self.assertIn("26 of 40", refusal)
        self.assertIn("first kill", refusal)

    def test_a_full_lineup_forms_with_no_refusal(self):
        lineup = _lineup()
        rows = _rows(lineup, set(_seat_names(lineup)))
        self.assertEqual(
            "", raidrun.seat_eligibility_refusal("moltencore", lineup, rows)
        )


class AFirstKillOrderFormsFromTheEligibleSeats(unittest.TestCase):
    def setUp(self):
        self.lineup = _lineup()
        self.eligible = _fourteen(self.lineup)
        self.rows = _rows(self.lineup, self.eligible)

    def test_fourteen_eligible_seats_form_and_26_are_named_left_out(self):
        roster = raidrun.first_kill_roster(
            "moltencore", self.lineup, self.rows, SMALL_QUORUM
        )
        self.assertEqual("", roster.refusal)
        self.assertEqual(14, len(roster.seats))
        self.assertEqual(self.eligible, {s for s in roster.seats})
        self.assertEqual(26, len(roster.left_out))
        left = {name for name, _why in roster.left_out}
        self.assertEqual(set(_seat_names(self.lineup)) - self.eligible, left)
        for word in ("14 of 40", "26", "left out"):
            self.assertIn(word, roster.line)
        for name in list(left)[:3]:
            self.assertIn(name, roster.line)

    def test_every_kept_seat_keeps_its_group_and_role_and_nobody_is_added(self):
        full = raidrun.seat_rows("Grug", "moltencore", self.lineup)
        kept = {r[2]: r for r in full if r[2] in self.eligible}
        roster = raidrun.first_kill_roster(
            "moltencore", self.lineup, self.rows, SMALL_QUORUM
        )
        written = raidrun.seat_rows("Grug", "moltencore", roster.lineup)
        self.assertEqual(14, len(written))
        for row in written:
            self.assertEqual(kept[row[2]], row)

    def test_the_default_quorum_refuses_fourteen_and_says_what_it_needs(self):
        roster = raidrun.first_kill_roster("moltencore", self.lineup, self.rows)
        self.assertEqual((30, 3, 8), raidrun.FIRST_KILL_QUORUM)
        self.assertIn("30 seats, 3 tanks and 8 healers", roster.refusal)
        self.assertIn("14 seats, 2 tanks and 3 healers", roster.refusal)
        self.assertEqual(14, len(roster.seats))

    def test_a_tank_short_roster_refuses_even_with_the_seats(self):
        roster = raidrun.first_kill_roster(
            "moltencore", self.lineup, self.rows, (14, 3, 1)
        )
        self.assertIn("3 tanks", roster.refusal)

    def test_the_left_out_say_why_offline_level_or_no_row(self):
        names = sorted(self.eligible)
        rows = [dict(r) for r in self.rows]
        rows[0]["online"] = 1
        rows[0]["level"] = 49
        gone = rows.pop(1)["name"]
        roster = raidrun.first_kill_roster("moltencore", self.lineup, rows, (1, 1, 1))
        why = dict(roster.left_out)
        self.assertIn("level 49", why[rows[0]["name"]])
        self.assertEqual("no current character row", why[gone])
        self.assertTrue(any(v == "offline" for v in why.values()))
        self.assertTrue(names)

    def test_a_full_lineup_forms_whole_and_names_nobody(self):
        rows = _rows(self.lineup, set(_seat_names(self.lineup)))
        roster = raidrun.first_kill_roster("moltencore", self.lineup, rows)
        self.assertEqual("", roster.refusal)
        self.assertEqual(40, len(roster.seats))
        self.assertEqual([], roster.left_out)

    def test_the_quorum_is_configurable_and_defaults_survive_bad_values(self):
        self.assertEqual((30, 3, 8), raidrun.first_kill_quorum({}))
        env = {
            "RAID_FIRST_KILL_QUORUM_SEATS": "14",
            "RAID_FIRST_KILL_QUORUM_TANKS": "x",
            "RAID_FIRST_KILL_QUORUM_HEALERS": "-2",
        }
        self.assertEqual((14, 3, 8), raidrun.first_kill_quorum(env))

    def test_a_zero_or_negative_quorum_falls_back_to_the_defaults(self):
        for env in (
            {"RAID_FIRST_KILL_QUORUM_SEATS": "0"},
            {"RAID_FIRST_KILL_QUORUM_TANKS": "-1"},
            {"RAID_FIRST_KILL_QUORUM_HEALERS": "0"},
        ):
            self.assertEqual((30, 3, 8), raidrun.first_kill_quorum(env))
        zeros = {k: "0" for k in raidrun.FIRST_KILL_ENV}
        self.assertEqual((30, 3, 8), raidrun.first_kill_quorum(zeros))

    def test_a_zero_quorum_is_logged_once(self):
        zeros = {k: "0" for k in raidrun.FIRST_KILL_ENV}
        raidrun._QUORUM_SAID.clear()
        with self.assertLogs("raidrun", level="WARNING") as seen:
            raidrun.first_kill_quorum(zeros)
            raidrun.first_kill_quorum(zeros)
        self.assertEqual(3, len(seen.output))  # one per key, not per call

    def test_an_empty_lineup_with_zero_quorum_still_refuses(self):
        empty = dict(self.lineup, groups=[])
        roster = raidrun.first_kill_roster("moltencore", empty, [], (0, 0, 0))
        self.assertTrue(roster.refusal)
        self.assertEqual((), roster.seats)
        offline = _rows(self.lineup, set())
        roster = raidrun.first_kill_roster(
            "moltencore", self.lineup, offline, (0, 0, 0)
        )
        self.assertIn("30 seats, 3 tanks and 8 healers", roster.refusal)

    def test_only_molten_core_has_a_first_kill_mode(self):
        roster = raidrun.first_kill_roster("ubrs", self.lineup, self.rows)
        self.assertIn("Molten Core", roster.refusal)


class TheFlagRidesTheOrder(unittest.TestCase):
    def test_the_words_set_the_flag_and_the_keyword_still_resolves(self):
        for text in (
            "moltencore first kill 1",
            "first-kill moltencore 1",
            "mc first kill 1",
            "molten core firstkill 1",
        ):
            entries, refusal = campaignqueue.parse_entries(text)
            self.assertEqual("", refusal, text)
            self.assertEqual(
                (campaignqueue.Entry("moltencore", 1, first_kill=True),),
                entries,
                text,
            )

    def test_ordinary_words_come_back_unchanged(self):
        for words in (
            ["moltencore"],
            ["first", "aid", "kit"],
            ["firstkiller", "moltencore"],
            ["unfirst", "kill"],
            ["first", "killing", "moltencore"],
        ):
            self.assertEqual((words, False), raidrun.strip_first_kill(words), words)
        self.assertEqual(
            (["moltencore"], True),
            raidrun.strip_first_kill(["moltencore", "first", "kill"]),
        )

    def test_a_plain_order_does_not_carry_it(self):
        entries, _ = campaignqueue.parse_entries("moltencore 1")
        self.assertFalse(entries[0].first_kill)

    def test_a_dungeon_has_no_first_kill_mode(self):
        _entries, refusal = campaignqueue.parse_entries("ragefire first kill 1")
        self.assertIn("Molten Core", refusal)

    def test_the_plan_says_it_is_a_first_kill(self):
        entries, _ = campaignqueue.parse_entries("moltencore first kill 1")
        rows = [
            {"name": n, "level": 60, "race": 1, "map_id": 0}
            for n in ("Grug", "Ugga", "Og", "Bork", "Grog")
        ]
        plan = campaignqueue.plan("Grug", entries, rows)
        self.assertEqual("", plan.refusal)
        self.assertIn("first kill", plan.says)

    def test_the_queue_row_carries_it_to_the_move(self):
        rows = [
            {
                "id": 7,
                "keyword": "moltencore",
                "runs_wanted": 1,
                "status": "queued",
                "position": 0,
                "first_kill": 1,
            }
        ]
        move = campaignqueue.step(rows, {"job": "quest", "dungeon_runs_done": 0})
        self.assertTrue(move.first_kill)
        rows[0]["first_kill"] = 0
        self.assertFalse(
            campaignqueue.step(
                rows, {"job": "quest", "dungeon_runs_done": 0}
            ).first_kill
        )

    def test_the_insert_and_the_read_name_the_column(self):
        self.assertIn("first_kill", campaignqueue.SELECT_PENDING_SQL)
        self.assertIn("first_kill", campaignqueue.FIRST_KILL_INSERT_SQL)
        self.assertIn("first_kill", campaignqueue.CREATE_SQL)


class TheBridgeWritesOnlyTheEligibleSeats(unittest.TestCase):
    def _run(self, first_kill, quorum, eligible=None):
        lineup = _lineup()
        eligible = _fourteen(lineup) if eligible is None else eligible
        rows = _rows(lineup, eligible)
        events = []
        drive = _load_drive_raid(events, GUILD, current_rows=rows)
        withheld = []
        with unittest_env(quorum):
            written = drive(
                "moltencore",
                "Grug",
                ["Grug"],
                "overseer:queue",
                withheld,
                first_kill=first_kill,
            )
        return written, withheld, events

    def test_a_first_kill_order_writes_fourteen_seats_and_the_job(self):
        written, withheld, events = self._run(True, SMALL_QUORUM)
        self.assertEqual(1, written)
        self.assertEqual([], withheld)
        inserts = [e for e in events if e[0] == "seat" and e[1] == "INSERT"]
        self.assertEqual(14, len(inserts[0][2]))
        self.assertIn(("job", "Grug", "raid:moltencore"), events)

    def test_below_the_quorum_nothing_is_written(self):
        written, withheld, events = self._run(True, (30, 3, 8))
        self.assertEqual(0, written)
        self.assertIn("30 seats", " ".join(withheld))
        self.assertFalse([e for e in events if e[0] in ("seat", "job")])

    def test_the_default_order_still_refuses_and_writes_nothing(self):
        written, withheld, events = self._run(False, SMALL_QUORUM)
        self.assertEqual(0, written)
        self.assertIn("26 of 40", " ".join(withheld))
        self.assertFalse([e for e in events if e[0] in ("seat", "job")])


@contextlib.contextmanager
def unittest_env(quorum):
    import os

    keys = (
        "RAID_FIRST_KILL_QUORUM_SEATS",
        "RAID_FIRST_KILL_QUORUM_TANKS",
        "RAID_FIRST_KILL_QUORUM_HEALERS",
    )
    old = {k: os.environ.get(k) for k in keys}
    try:
        for key, value in zip(keys, quorum, strict=True):
            os.environ[key] = str(value)
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class TheRaidTabNamesTheLeftOut(unittest.TestCase):
    def test_the_card_line_counts_the_eligible_and_names_the_left_out(self):
        raiders = [
            {"name": "A%d" % i, "level": 60 if i < 14 else 30, "role": r}
            for i, r in enumerate(["tank"] * 2 + ["healer"] * 3 + ["dps"] * 35)
        ]
        card = raidready.first_kill_card(raiders, 50)
        self.assertEqual(14, card["seats"])
        self.assertEqual(26, len(card["left_out"]))
        self.assertIn("14 of 40", card["line"])
        self.assertIn("A39", card["line"])
        self.assertFalse(card["can_form"])


if __name__ == "__main__":
    unittest.main()
