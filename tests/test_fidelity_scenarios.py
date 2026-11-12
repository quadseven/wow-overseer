"""Every scenario under fidelity/scenarios replays green, verified, offline
(#2281), and the provenance rules keep synthetic data from standing as realm
truth.

Scenarios named `synthetic-*` are rows written to exercise the machinery. They
are not realm captures and may not name the tickets they prove. A realm
capture (provenance kind `realm`) says where and when it was taken.
"""

import contextlib
import copy
import io
import json
import pathlib
import socket
import sys
import tempfile
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import guildrun
    from fidelity import fixture, replay, verify
    from test_fidelity_replay import NOT_A_FULL_CLEAR

SCENARIOS = sorted((HERE / "fidelity" / "scenarios").glob("*.json"))


class Scenarios(unittest.TestCase):
    def test_there_are_scenarios(self):
        self.assertTrue(SCENARIOS)

    def test_each_scenario_verifies_and_replays_green_with_no_network(self):
        def refuse(*args, **kwargs):
            raise AssertionError("the replay opened a socket")

        for path in SCENARIOS:
            with self.subTest(scenario=path.name):
                fx = fixture.load(path)
                self.assertEqual(fx.name, path.stem)
                with mock.patch.object(socket, "socket", refuse):
                    self.assertEqual(verify.problems(fx), [])
                    self.assertEqual(replay.run(fx).problems, [])

    def test_a_synthetic_scenario_says_so_in_its_name(self):
        for path in SCENARIOS:
            fx = fixture.load(path)
            if fx.kind == fixture.SYNTHETIC:
                self.assertTrue(path.name.startswith("synthetic-"), path.name)

    def test_a_realm_scenario_says_where_it_came_from(self):
        for path in SCENARIOS:
            fx = fixture.load(path)
            if fx.kind == fixture.REALM:
                self.assertTrue(fx.source.strip(), path.name)

    def test_the_not_a_full_clear_scenario_goes_red_on_a_completion_flag_shortcut(
        self,
    ):
        path = HERE / "fidelity" / "scenarios" / "synthetic-not-a-full-clear.json"
        fx = fixture.load(path)
        self.assertFalse(fx.expect["runs"][0]["clear"])
        with mock.patch.object(guildrun, "every_boss_fell", lambda done, total: True):
            result = replay.run(fx)
        self.assertTrue(result.problems)


class Provenance(unittest.TestCase):
    def doc(self, **provenance):
        doc = copy.deepcopy(NOT_A_FULL_CLEAR)
        doc["provenance"].update(provenance)
        return doc

    def test_a_synthetic_fixture_cannot_name_tickets_it_proves(self):
        doc = self.doc()
        doc["proves"] = [2000]
        with self.assertRaises(fixture.FixtureError):
            fixture.parse(doc)

    def test_a_realm_fixture_can_name_the_tickets_it_proves(self):
        doc = self.doc(kind="realm", source="a capture, with its date")
        doc["proves"] = [2000]
        self.assertEqual(fixture.parse(doc).proves, (2000,))

    def test_a_realm_fixture_with_no_source_is_refused(self):
        with self.assertRaises(fixture.FixtureError):
            fixture.parse(self.doc(kind="realm", source=""))


if __name__ == "__main__":
    unittest.main()


class Command(unittest.TestCase):
    def run_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = replay.main(argv)
        return code, out.getvalue()

    def test_it_verifies_and_replays_every_scenario_by_default(self):
        code, said = self.run_main([])
        self.assertEqual(code, 0)
        self.assertIn("synthetic-not-a-full-clear", said)

    def test_it_exits_nonzero_and_names_the_run_when_a_claim_is_wrong(self):
        doc = copy.deepcopy(NOT_A_FULL_CLEAR)
        doc["expect"]["runs"][0]["clear"] = True
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "synthetic-wrong.json"
            path.write_text(json.dumps(doc))
            code, said = self.run_main([str(path)])
        self.assertEqual(code, 1)
        self.assertIn("run 41", said)
