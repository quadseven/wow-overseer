"""A roster step is an overseer_command row of kind job, never a roster write."""

import pathlib
import unittest

from ephemeral import acts
from ephemeral.miniyaml import loads

DECREES = pathlib.Path(__file__).resolve().parent.parent / "decrees"


class ActCommandsTest(unittest.TestCase):
    def test_roster_becomes_a_job_command(self):
        d = {"act": [{"at": "0s", "roster": {"who": "family:grug", "job": "quest"}}]}
        self.assertEqual(
            acts.act_commands(d),
            [{"at": "0s", "who": "family:grug", "kind": "job", "text": "quest"}],
        )

    def test_command_passes_through_and_when_is_kept(self):
        d = {
            "act": [
                {
                    "when": "seen",
                    "command": {"who": "cast[0]", "kind": "hearth", "text": "go"},
                }
            ]
        }
        self.assertEqual(
            acts.act_commands(d),
            [{"when": "seen", "who": "cast[0]", "kind": "hearth", "text": "go"}],
        )

    def test_no_act_is_no_rows(self):
        self.assertEqual(acts.act_commands({}), [])

    def test_guzzler_walks_out_with_a_job_command(self):
        d = loads(
            (DECREES / "brd-guzzler-exit-zero-patron-deaths.yaml").read_text(
                encoding="utf-8"
            )
        )
        rows = acts.act_commands(d)
        self.assertEqual([r["kind"] for r in rows], ["job", "job"])
        self.assertEqual(
            rows[1],
            {
                "when": "plugger-was-dead",
                "who": "family:grug",
                "kind": "job",
                "text": "quest",
            },
        )

    def test_the_acts_command_prints_the_rows(self):
        import contextlib
        import io
        import json

        from ephemeral.__main__ import main

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(
                ["acts", str(DECREES / "brd-guzzler-exit-zero-patron-deaths.yaml")]
            )
        self.assertEqual(rc, 0)
        rows = json.loads(buf.getvalue())
        self.assertEqual(
            rows[0],
            {
                "at": "0s",
                "who": "family:grug",
                "kind": "job",
                "text": "dungeon:blackrockdepths",
            },
        )


if __name__ == "__main__":
    unittest.main()
