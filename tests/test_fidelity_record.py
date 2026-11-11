"""The fidelity suite's recorder (#2281).

It runs a surface over a real reader, guards every statement as a single
read-only SELECT (the liveproof guard), keeps the reads in order, derives the
expected claims from the capture, and accepts the fixture only after the
verifier agrees. The source here is the in-memory reader fed SYNTHETIC rows:
these test the machinery and are not realm captures.
"""

import contextlib
import datetime
import decimal
import io
import json
import pathlib
import sys
import tempfile
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import realmread
    from fidelity import fixture, record, replay, verify
    from liveproof import run as liveproof
    from test_fidelity_replay import GUILD, NOT_A_FULL_CLEAR, run_row, scenario


def source_of(doc: dict) -> realmread.Memory:
    """An in-memory realm that answers the reads of a scenario document."""
    return realmread.Memory({r["sql"]: r["rows"] for r in doc["reads"]})


ARGS = NOT_A_FULL_CLEAR["args"]


class RecordingReader(unittest.TestCase):
    def test_reads_are_kept_in_order_with_their_params_and_rows(self):
        inner = source_of(NOT_A_FULL_CLEAR)
        rd = record.RecordingReader(inner)
        rd.must(NOT_A_FULL_CLEAR["reads"][0]["sql"], (GUILD,))
        rd.must(NOT_A_FULL_CLEAR["reads"][1]["sql"], (7, 7, 20000))
        self.assertEqual(
            [r["params"] for r in rd.reads], [[GUILD], [7, 7, 20000]]
        )
        self.assertEqual(rd.reads[0]["rows"], [{"guildid": 7, "name": GUILD}])

    def test_a_statement_that_is_not_one_select_never_reaches_the_realm(self):
        inner = realmread.Memory({"DELETE FROM guild": []})
        rd = record.RecordingReader(inner)
        with self.assertRaises(liveproof.UnsafeStatement):
            rd.must("DELETE FROM guild", None)
        self.assertEqual(inner.asked, [])

    def test_placeholders_do_not_trip_the_guard(self):
        sql = "SELECT id FROM guild WHERE name IN (%s, %s) LIMIT %s"
        inner = realmread.Memory({sql: [{"id": 1}]})
        rd = record.RecordingReader(inner)
        self.assertEqual(rd.must(sql, ("a", "b", 5)), [{"id": 1}])

    def test_a_missing_table_is_kept_as_a_gap(self):
        sql = "SELECT id FROM overseer_clip WHERE 1 = %s"
        rd = record.RecordingReader(realmread.Memory({sql: realmread.MISSING_TABLE}))
        self.assertEqual(rd.rows(sql, (1,)), [])
        self.assertEqual(rd.reads[0]["gap"], realmread.MISSING_TABLE)


class Codec(unittest.TestCase):
    def test_times_and_decimals_survive_a_file(self):
        when = datetime.datetime(2026, 1, 2, 3, 4, 5)
        rows = [{"at": when, "gold": decimal.Decimal("1.50"), "n": 3}]
        text = json.dumps(fixture.encode(rows))
        self.assertEqual(fixture.decode(json.loads(text)), rows)


class Record(unittest.TestCase):
    def record(self, doc=NOT_A_FULL_CLEAR, alias=None):
        return record.record(
            "chronicle",
            ARGS,
            source_of(doc),
            name="synthetic-recorded",
            kind=fixture.SYNTHETIC,
            source="recorder unit test",
            alias=alias,
        )

    def test_the_recorded_fixture_is_verified_and_replays_green(self):
        doc = self.record()
        fx = fixture.parse(json.loads(json.dumps(doc)))
        self.assertEqual(verify.problems(fx), [])
        self.assertEqual(replay.run(fx).problems, [])
        self.assertEqual(
            doc["expect"],
            {"runs": [{"run": 41, "credited": 18, "of": 19, "clear": False}]},
        )

    def test_expected_claims_come_from_the_capture_not_the_code_under_test(self):
        doc = self.record(
            scenario([run_row(51, "cleared", 18, 19)], [], "synthetic-x")
        )
        self.assertFalse(doc["expect"]["runs"][0]["clear"])

    def test_a_capture_with_no_credited_tally_is_not_accepted(self):
        bad = scenario([run_row(52, "cleared", 0, 19)], [])
        with self.assertRaises(record.Refused) as caught:
            self.record(bad)
        self.assertIn("run 52", str(caught.exception))

    def test_names_can_be_aliased_everywhere_in_the_capture(self):
        row = dict(run_row(53, "cleared", 18, 19), members="Zorg:tank:warrior:60")
        doc = self.record(
            scenario([row], []), alias={"Zorg": "Alpha", GUILD: "Guild One"}
        )
        text = json.dumps(doc)
        self.assertNotIn("Zorg", text)
        self.assertNotIn(GUILD, text)
        self.assertIn("Alpha:tank", text)
        self.assertEqual(replay.run(fixture.parse(doc)).problems, [])

    def test_a_realm_fixture_must_name_its_source(self):
        with self.assertRaises(record.Refused):
            record.record(
                "chronicle",
                ARGS,
                source_of(NOT_A_FULL_CLEAR),
                name="x",
                kind=fixture.REALM,
                source="",
            )


def quietly(call):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
        io.StringIO()
    ):
        return call()


class Command(unittest.TestCase):
    def test_it_writes_the_accepted_fixture_to_the_named_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "scenario.json"
            code = quietly(
                lambda: record.main(
                    [
                        "--surface", "chronicle",
                        "--guild", GUILD,
                        "--name", "synthetic-cli",
                        "--kind", "synthetic",
                        "--source", "recorder unit test",
                        "--out", str(out),
                    ],
                    reader=source_of(NOT_A_FULL_CLEAR),
                )
            )
            self.assertEqual(code, 0)
            fx = fixture.load(out)
        self.assertEqual(replay.run(fx).problems, [])

    def test_a_refused_capture_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "scenario.json"
            code = quietly(
                lambda: record.main(
                    [
                        "--surface", "chronicle", "--guild", GUILD,
                        "--name", "x", "--kind", "synthetic",
                        "--source", "recorder unit test", "--out", str(out),
                    ],
                    reader=source_of(
                        scenario([run_row(54, "cleared", 0, 19)], [])
                    ),
                )
            )
            self.assertEqual(code, 1)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
