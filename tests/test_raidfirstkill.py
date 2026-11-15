"""First-kill roster mode: an operator-chosen Molten Core order for the members
who are already eligible (#2570).

The default order refuses unless every approved seat is online and at the raid
level. The first-kill roster is an explicit, per-guild operator flag, OFF by
default, that seats only the eligible subset for that one order. These tests
pin the pure decision (raidrun.first_kill_roster), the flag's parsing, and the
bridge's use of both. They never import bridge.py: the bridge functions are
read as source and run against fakes.
"""

import ast
import contextlib
import copy
import pathlib
import types
import unittest

import campaignqueue
import jobs
import raidlineup
import raidrun
import raidteams

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

GUILD = "Cave"


def _approved_members(low=(), offline=()):
    """The approved guild's seats as guild rows: level 60 unless named in `low`
    (level 30) and online unless named in `offline`."""
    rows = []
    for seat in raidteams.seats(GUILD):
        rows.append(
            {
                "name": seat.name,
                "level": 30 if seat.name in low else 60,
                "class_id": seat.class_id,
                "race": 1,
                "online": 0 if seat.name in offline else 1,
            }
        )
    return rows


def _lineup(members):
    lineup = raidlineup.build_lineup(members, guaranteed=["Grug"])
    assert lineup.get("approved") == GUILD
    return lineup


def _placed(lineup):
    return [m for g in lineup["groups"] for m in g["members"]]


def _low_set(lineup, keep):
    """Names of every placed seat except the first `keep` of them."""
    return {m["name"] for m in _placed(lineup)[keep:]}


POLICY = raidrun.FirstKillPolicy(frozenset({"cave"}), 14, 2, 3)


class TheFlagIsOffByDefault(unittest.TestCase):
    def test_no_environment_means_no_guild_is_on(self):
        policy = raidrun.first_kill_policy({})
        self.assertFalse(policy.guilds)
        self.assertFalse(policy.applies("moltencore", {"approved": "Cave"}))

    def test_a_named_guild_turns_it_on_for_that_guild_only(self):
        policy = raidrun.first_kill_policy({"RAID_FIRST_KILL_GUILDS": " cave , "})
        self.assertTrue(policy.applies("moltencore", {"approved": "Cave"}))
        self.assertFalse(policy.applies("moltencore", {"approved": "Bonkers"}))

    def test_it_never_applies_to_another_raid_or_an_unapproved_lineup(self):
        policy = raidrun.first_kill_policy({"RAID_FIRST_KILL_GUILDS": "Cave"})
        self.assertFalse(policy.applies("ubrs", {"approved": "Cave"}))
        self.assertFalse(policy.applies("moltencore", {}))

    def test_the_minimums_default_and_survive_a_bad_value(self):
        policy = raidrun.first_kill_policy({"RAID_FIRST_KILL_GUILDS": "Cave"})
        self.assertEqual((14, 2, 3), (policy.seats, policy.tanks, policy.healers))
        policy = raidrun.first_kill_policy(
            {
                "RAID_FIRST_KILL_GUILDS": "Cave",
                "RAID_FIRST_KILL_MIN_SEATS": "20",
                "RAID_FIRST_KILL_MIN_TANKS": "x",
                "RAID_FIRST_KILL_MIN_HEALERS": "0",
            }
        )
        self.assertEqual((20, 2, 0), (policy.seats, policy.tanks, policy.healers))


class TheRosterIsTheEligibleSubset(unittest.TestCase):
    def setUp(self):
        self.members = _approved_members()
        self.lineup = _lineup(self.members)
        self.eligible = 19
        self.low = _low_set(self.lineup, self.eligible)
        self.rows = _approved_members(low=self.low)

    def test_the_eligible_members_form_and_the_rest_are_named(self):
        result = raidrun.first_kill_roster("moltencore", self.lineup, self.rows, POLICY)
        self.assertEqual("", result.refusal)
        self.assertEqual(self.eligible, len(_placed(result.lineup)))
        self.assertEqual(self.low, {entry["name"] for entry in result.left_out})
        self.assertEqual(len(self.low), len(result.left_out))
        for entry in result.left_out:
            self.assertIn("level 30; needs 50", entry["why"])

    def test_the_approved_lineup_itself_is_never_rewritten(self):
        before = copy.deepcopy(self.lineup)
        raidrun.first_kill_roster("moltencore", self.lineup, self.rows, POLICY)
        self.assertEqual(before, self.lineup)

    def test_subgroups_are_kept_so_a_seat_does_not_move(self):
        result = raidrun.first_kill_roster("moltencore", self.lineup, self.rows, POLICY)
        full = {
            m["name"]: int(g["number"])
            for g in self.lineup["groups"]
            for m in g["members"]
        }
        for group in result.lineup["groups"]:
            for member in group["members"]:
                self.assertEqual(full[member["name"]], int(group["number"]))

    def test_the_order_records_that_it_is_a_first_kill_roster(self):
        result = raidrun.first_kill_roster("moltencore", self.lineup, self.rows, POLICY)
        self.assertIn("first-kill roster", result.line)
        self.assertIn("%d of 40" % self.eligible, result.line)
        self.assertIn("level 30; needs 50", result.line)
        self.assertTrue(result.lineup["first_kill"]["left_out"])

    def test_an_offline_member_is_left_out_as_offline(self):
        name = _placed(self.lineup)[0]["name"]
        rows = _approved_members(offline={name})
        result = raidrun.first_kill_roster("moltencore", self.lineup, rows, POLICY)
        why = {e["name"]: e["why"] for e in result.left_out}
        self.assertEqual("offline", why[name])

    def test_a_member_with_no_current_row_is_left_out(self):
        name = _placed(self.lineup)[0]["name"]
        rows = [r for r in self.rows if r["name"] != name]
        result = raidrun.first_kill_roster("moltencore", self.lineup, rows, POLICY)
        why = {e["name"]: e["why"] for e in result.left_out}
        self.assertEqual("no current character row", why[name])

    def test_seat_rows_for_the_subset_carry_the_same_shape(self):
        result = raidrun.first_kill_roster("moltencore", self.lineup, self.rows, POLICY)
        seats = raidrun.seat_rows("Grug", "moltencore", result.lineup, duty=True)
        self.assertEqual(self.eligible, len(seats))
        self.assertTrue(all(len(s) == 6 for s in seats))


class TheMinimumGuardsTheRoster(unittest.TestCase):
    def test_too_few_seats_refuses_and_says_what_is_short(self):
        lineup = _lineup(_approved_members())
        rows = _approved_members(low=_low_set(lineup, 10))
        result = raidrun.first_kill_roster("moltencore", lineup, rows, POLICY)
        self.assertIn("first-kill roster refused", result.refusal)
        self.assertIn("10 seats", result.refusal)
        self.assertIn("needs 14", result.refusal)

    def test_too_few_tanks_or_healers_refuses_by_role(self):
        lineup = _lineup(_approved_members())
        rows = _approved_members(
            low={m["name"] for m in _placed(lineup) if m["role"] == "tank"}
        )
        result = raidrun.first_kill_roster("moltencore", lineup, rows, POLICY)
        self.assertIn("0 tanks", result.refusal)
        rows = _approved_members(
            low={m["name"] for m in _placed(lineup) if m["role"] == "healer"}
        )
        result = raidrun.first_kill_roster("moltencore", lineup, rows, POLICY)
        self.assertIn("0 healers", result.refusal)

    def test_the_whole_lineup_eligible_leaves_nobody_out(self):
        lineup = _lineup(_approved_members())
        result = raidrun.first_kill_roster(
            "moltencore", lineup, _approved_members(), POLICY
        )
        self.assertEqual([], result.left_out)
        self.assertEqual(40, len(_placed(result.lineup)))


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("no %s in bridge.py" % name)


def _drive(members, rows, environ):
    """bridge._drive_raid and its helpers, run against recording fakes."""
    events, logs = [], []
    source = "\n\n".join(
        ast.get_source_segment(BRIDGE, _function(name))
        for name in (
            "_withheld",
            "_raid_seat_eligibility",
            "_write_raid_seats",
            "_log_raid_arrivals",
            "_plan_first_kill_roster",
            "_plan_raid_seats",
            "_persist_raid_lineup",
            "_insert_raid_jobs",
            "_drive_raid",
        )
    )

    class Err(Exception):
        pass

    class Cursor:
        def execute(self, sql, args=()):
            if "overseer_raid_seat" in sql:
                events.append(("seat", sql.split()[0], args))
            elif sql.startswith("SELECT c.name, c.level, c.online FROM characters"):
                events.append(("eligibility", args))
            else:
                events.append(("read", args))

        def executemany(self, sql, seat_rows):
            events.append(("seat", sql.split()[0], list(seat_rows)))

        def fetchall(self):
            if events and events[-1][0] == "eligibility":
                return list(rows)
            return list(members)

    class Conn:
        def cursor(self):
            return contextlib.nullcontext(Cursor())

    class Log:
        def info(self, fmt, *a):
            logs.append(fmt % a if a else fmt)

        warning = exception = info

    namespace = {
        "os": types.SimpleNamespace(environ=environ),
        "jobs": jobs,
        "raidrun": raidrun,
        "guildjobs": types.SimpleNamespace(entrances=lambda: {}),
        "_with_readiness": lambda cur, ms: ms,
        "campaignqueue": campaignqueue,
        "log": Log(),
        "_insert_job": lambda name, mode, by: events.append(("job", name, mode)),
        "_connect": lambda: contextlib.nullcontext(Conn()),
        "pymysql": types.SimpleNamespace(err=types.SimpleNamespace(MySQLError=Err)),
    }
    exec(compile(source, str(BRIDGE), "exec"), namespace)  # noqa: S102 - bridge.py's own source
    return namespace["_drive_raid"], events, logs


class TheBridgeOrdersTheSubsetOnlyWhenTheFlagIsOn(unittest.TestCase):
    def setUp(self):
        self.members = _approved_members()
        lineup = _lineup(self.members)
        self.low = _low_set(lineup, 19)
        self.rows = _approved_members(low=self.low)

    def _inserts(self, events):
        return [e for e in events if e[0] == "seat" and e[1] == "INSERT"]

    def test_flag_off_the_default_refusal_is_unchanged_and_nothing_is_written(self):
        drive, events, _ = _drive(self.members, self.rows, {})
        withheld = []
        self.assertEqual(0, drive("moltencore", "Grug", ["Grug"], "q", withheld))
        self.assertIn("refused: 21 of 40 approved members unavailable", withheld[0])
        self.assertNotIn("first-kill", withheld[0])
        self.assertFalse([e for e in events if e[0] in ("seat", "job")])

    def test_flag_off_the_event_order_is_the_old_one_exactly(self):
        drive, events, logs = _drive(self.members, self.members, {})
        self.assertEqual(1, drive("moltencore", "Grug", ["Grug"], "q", []))
        self.assertEqual(
            ["read", "eligibility", "seat", "seat", "read", "job"],
            [e[0] for e in events],
        )
        self.assertEqual(40, len(self._inserts(events)[0][2]))
        self.assertFalse([line for line in logs if "first-kill" in line])

    def test_another_guilds_flag_changes_nothing_here(self):
        env = {"RAID_FIRST_KILL_GUILDS": "Bonkers"}
        drive, events, _ = _drive(self.members, self.rows, env)
        withheld = []
        self.assertEqual(0, drive("moltencore", "Grug", ["Grug"], "q", withheld))
        self.assertIn("refused", withheld[0])
        self.assertFalse([e for e in events if e[0] in ("seat", "job")])

    def test_flag_on_the_eligible_subset_is_seated_and_the_job_written(self):
        env = {"RAID_FIRST_KILL_GUILDS": "Cave"}
        drive, events, logs = _drive(self.members, self.rows, env)
        withheld = []
        self.assertEqual(1, drive("moltencore", "Grug", ["Grug"], "q", withheld))
        self.assertEqual([], withheld)
        inserts = self._inserts(events)
        self.assertEqual(1, len(inserts), "the seats are still one statement")
        self.assertEqual(19, len(inserts[0][2]))
        seated = {row[2] for row in inserts[0][2]}
        self.assertFalse(seated & self.low)
        self.assertEqual(("job", "Grug", "raid:moltencore"), events[-1])
        record = [line for line in logs if "first-kill roster" in line]
        self.assertTrue(record)
        self.assertIn("19 of 40", record[0])

    def test_flag_on_but_below_the_minimum_writes_nothing(self):
        env = {"RAID_FIRST_KILL_GUILDS": "Cave", "RAID_FIRST_KILL_MIN_SEATS": "30"}
        drive, events, _ = _drive(self.members, self.rows, env)
        withheld = []
        self.assertEqual(0, drive("moltencore", "Grug", ["Grug"], "q", withheld))
        self.assertIn("first-kill roster refused", withheld[0])
        self.assertFalse([e for e in events if e[0] in ("seat", "job")])


if __name__ == "__main__":
    unittest.main()
