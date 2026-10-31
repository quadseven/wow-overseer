"""Probing a living character, and the two ways that can quietly lie.

The probe exists because acore_characters is up to fifteen minutes stale and a
`delivered` command says only that a row was handed over. A tool that replaces
those with a DIFFERENT wrong answer would be worse than the situation it
replaces, because it would be confidently wrong rather than obviously silent.

So the two failures worth pinning are: an answer that belongs to a different
probe, and a probe nobody answered being reported as though it had nothing to
say.
"""

import json
import pathlib
import re
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import probe  # noqa: E402
import modsource


class FakeCursor:
    """Answers SELECTs from a scripted set of rows, one batch per poll."""

    def __init__(self, batches):
        self._batches = list(batches)
        self._last = []
        self.lastrowid = 0
        self.inserted = []

    def execute(self, sql, params=None):
        if sql.lstrip().upper().startswith("INSERT"):
            self.lastrowid += 1
            self.inserted.append(params)
            self._last = []
            return
        self._last = self._batches.pop(0) if self._batches else []

    def fetchall(self):
        return self._last


def _row(i, status="delivered", result=None, detail=""):
    return {"id": i, "status": status, "detail": detail, "result": result}


class CollectReadsTheRightRow(unittest.TestCase):
    def test_each_answer_lands_against_its_own_probe(self):
        """Two probes in flight must not read each other's results.

        The rows come back in the opposite order to the one they were asked in,
        which is what a real batched SELECT is free to do.
        """
        ids = {1: ("Grug", "state"), 2: ("Grug", "talents")}
        cur = FakeCursor(
            [
                [
                    _row(2, result=json.dumps({"spec_tab": 2})),
                    _row(1, result=json.dumps({"level": 11})),
                ]
            ]
        )
        out = probe.collect(cur, ids, deadline=probe.time.monotonic() + 5)
        self.assertEqual(2, out["Grug"]["talents"]["spec_tab"])
        self.assertEqual(11, out["Grug"]["state"]["level"])

    def test_a_row_still_running_is_not_read_as_an_answer(self):
        """`claimed` means in-flight. Reading it would report a half-done probe."""
        ids = {1: ("Grug", "state")}
        cur = FakeCursor(
            [
                [_row(1, status="claimed")],
                [_row(1, result=json.dumps({"level": 11}))],
            ]
        )
        out = probe.collect(cur, ids, deadline=probe.time.monotonic() + 5)
        self.assertEqual(11, out["Grug"]["state"]["level"])

    def test_an_unanswered_probe_is_reported_not_omitted(self):
        """Absent reads as 'nothing to say'; this has to read as 'nobody answered'."""
        ids = {1: ("Grog", "spells")}
        cur = FakeCursor([])
        out = probe.collect(cur, ids, deadline=probe.time.monotonic() - 1)
        self.assertIn("error", out["Grog"]["spells"])
        self.assertIn("timed out", out["Grog"]["spells"]["error"])

    def test_an_errored_probe_surfaces_the_reason(self):
        ids = {1: ("Bork", "gear")}
        cur = FakeCursor([[_row(1, status="error", detail="target not online")]])
        out = probe.collect(cur, ids, deadline=probe.time.monotonic() + 5)
        self.assertEqual("target not online", out["Bork"]["gear"]["error"])

    def test_malformed_json_is_an_error_not_a_crash(self):
        ids = {1: ("Og", "bags")}
        cur = FakeCursor([[_row(1, result="{not json")]])
        out = probe.collect(cur, ids, deadline=probe.time.monotonic() + 5)
        self.assertIn("invalid json", out["Og"]["bags"]["error"])


class PlaceholdersCarryNoData(unittest.TestCase):
    """The IN clause is the one place this builds SQL by formatting.

    ruff flags it (S608) and cannot tell that the formatted fragment is a run of
    markers rather than values. That is only true while placeholders() stays
    incapable of emitting anything else, so it is asserted here rather than
    claimed in a comment beside a noqa.
    """

    def test_it_emits_only_markers_and_commas(self):
        for n in (1, 2, 5, 50):
            got = probe.placeholders(n)
            self.assertEqual(
                set(got) - {"%", "s", ","}, set(), f"unexpected chars in {got!r}"
            )
            self.assertEqual(n, got.count("%s"))
            self.assertEqual(n - 1, got.count(","))

    def test_a_count_is_all_it_accepts(self):
        """It takes an int. There is no path for a caller to inject text."""
        with self.assertRaises(TypeError):
            probe.placeholders("1; DROP TABLE overseer_command")

    def test_an_empty_in_clause_is_refused_rather_than_malformed(self):
        with self.assertRaises(ValueError):
            probe.placeholders(0)


class CliKeepsRequestedProbes(unittest.TestCase):
    def test_all_asks_exactly_the_selected_probes_for_each_member(self):
        for selection in (("auras",), ("auras", "meter", "bags"), ()):
            with self.subTest(selection=selection):
                conn = MagicMock()
                with (
                    patch.object(sys, "argv", ["probe.py", "--all", *selection]),
                    patch.object(probe, "_connect", return_value=conn),
                    patch.object(probe, "roster", return_value=["Grug", "Ugga"]),
                    patch.object(probe, "ask", side_effect=range(1, 17)) as ask,
                    patch.object(probe, "collect", return_value={}),
                    redirect_stdout(StringIO()),
                ):
                    self.assertEqual(0, probe.main())
                self.assertEqual(
                    [
                        (n, p)
                        for n in ("Grug", "Ugga")
                        for p in selection or probe.PROBES
                    ],
                    [(c.args[1], c.args[2]) for c in ask.call_args_list],
                )

    def test_all_rejects_an_unknown_first_probe_before_connecting(self):
        with (
            patch.object(sys, "argv", ["probe.py", "--all", "unknown"]),
            patch.object(probe, "_connect") as connect,
            patch.object(sys, "stderr", StringIO()),
        ):
            self.assertEqual(2, probe.main())
        connect.assert_not_called()


MODULE = modsource.MODULE


def _probe_source() -> str:
    """Everything from the first probe function to the end of DoProbe."""
    src = modsource.read(MODULE, encoding="utf-8")
    start = src.index("static std::string ProbeState(")
    # The dot-command runner that used to follow DoProbe is gone from the
    # module, so the span ends where DoProbe itself ends (braces balanced).
    do_probe = src.index("static char const* DoProbe(", start)
    depth = 0
    end = 0
    for i in range(src.index("{", do_probe), len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    assert end > start
    return src[start:end]


# Anything that changes the world. A probe that mutates is a probe that can be
# the reason an experiment appeared to work, which destroys the only property
# that makes it trustworthy as an instrument.
MUTATORS = [
    "learnSpell",
    "LearnTalent",
    "removeSpell",
    "SetSkill",
    "resetTalents",
    "TeleportTo",
    "DurabilityRepair",
    "SetMoney",
    "DestroyItem",
    "AddItem",
    "HandleCommand",
    "addStrategy",
    "removeStrategy",
]


class ProbesAreReadOnly(unittest.TestCase):
    def test_every_module_probe_is_available_from_the_tool(self):
        handled = set(re.findall(r'\bwhat == "([^"]+)"', _probe_source()))
        self.assertSetEqual(set(probe.PROBES), handled)

    def test_no_probe_mutates_the_character(self):
        body = _probe_source()
        for call in MUTATORS:
            self.assertNotIn(
                call, body, f"a probe calls {call}, which changes the world"
            )

    def test_every_probe_the_tool_offers_is_handled_by_the_module(self):
        """A verb the tool sends and the module does not know is a silent gap."""
        body = _probe_source()
        for name in probe.PROBES:
            self.assertIn(f'"{name}"', body, f"module does not handle probe '{name}'")

    def test_the_probe_path_is_reachable_from_the_command_loop(self):
        """DoProbe nobody dispatches to is an instrument that never reads."""
        src = modsource.read(MODULE, encoding="utf-8")
        self.assertIn('kind == "probe"', src)
        self.assertIn("DoProbe(player, command, status, rowResult)", src)

    def test_the_result_is_actually_written_back(self):
        """A probe whose answer never reaches the row answers nobody."""
        src = modsource.read(MODULE, encoding="utf-8")
        self.assertIn("result = '{}'", src)
        self.assertIn("EscLong(rowResult)", src)


if __name__ == "__main__":
    unittest.main()
