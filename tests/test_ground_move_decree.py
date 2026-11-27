"""Ground-move decree (#2937, #3279): master assignment, moved precondition, and verdicts."""

import contextlib
import math
import pathlib
import re
import sqlite3
import unittest

from ephemeral import anchors as anchors_mod
from ephemeral import dbschema, judge, lint
from ephemeral.miniyaml import loads

ROOT = pathlib.Path(__file__).resolve().parent.parent
DECREE_PATH = (
    ROOT / "data" / "decrees" / "ground-move-is-not-flown-in-a-straight-line.yaml"
)
START_X = -6632.0
START_Y = -2178.0
GO_XY_RE = re.compile(r"^go\s+(-?\d+(?:\.\d+)?);(-?\d+(?:\.\d+)?)$")


def _load_decree():
    return loads(DECREE_PATH.read_text(encoding="utf-8"))


def _eval_verdict(decree, start_xy, end_xy, go_rows=5, deaths=0):
    """Evaluate every SQL observation in the decree against an in-memory DB."""
    with contextlib.closing(sqlite3.connect(":memory:")) as db:
        db.create_function("SQRT", 1, math.sqrt)
        db.create_function("POW", 2, math.pow)
        db.execute(
            "CREATE TABLE overseer_snapshot "
            "(guid INTEGER, name TEXT, map_id INTEGER, pos_x REAL, pos_y REAL)"
        )
        db.execute(
            "CREATE TABLE overseer_command "
            "(target_name TEXT, kind TEXT, command TEXT, created_at INTEGER, status TEXT)"
        )
        db.execute(
            "CREATE TABLE overseer_death (character_name TEXT, created_at INTEGER)"
        )
        for i in range(go_rows):
            db.execute(
                "INSERT INTO overseer_command VALUES "
                "('Uzza', 'bot', 'go -7007.0;-2285.1', ?, 'delivered')",
                (1000 + i,),
            )
        for i in range(deaths):
            db.execute("INSERT INTO overseer_death VALUES ('Uzza', ?)", (1000 + i,))

        variables = {"Uzza": 42, "t0": 1000}
        preconditions_ok = True
        checks_ok = True
        failed_preconditions = []
        failed_checks = []

        for obs in decree["observe"]:
            if "online" in obs:
                continue
            pos_x, pos_y = start_xy if obs["when"] == "start" else end_xy
            db.execute("DELETE FROM overseer_snapshot")
            db.execute(
                "INSERT INTO overseer_snapshot VALUES (42, 'Uzza', 0, ?, ?)",
                (pos_x, pos_y),
            )
            rendered = judge.render_sql(obs["sql"], variables)
            rows = db.execute(rendered).fetchall()
            held, _ = judge.expectation_holds(obs["expect"], rows)
            if not held:
                if obs["role"] == "precondition":
                    preconditions_ok = False
                    failed_preconditions.append(obs["name"])
                else:
                    checks_ok = False
                    failed_checks.append(obs["name"])

    if not preconditions_ok:
        return "INVALID", failed_preconditions, failed_checks
    if not checks_ok:
        return "FAIL", failed_preconditions, failed_checks
    return "PASS", failed_preconditions, failed_checks


class GroundMoveDecreeTest(unittest.TestCase):
    def test_lints_strictly_without_errors_or_warnings(self):
        anchors = anchors_mod.Anchors.load()
        schema = dbschema.Schema.load()
        findings = lint.lint_path(DECREE_PATH, anchors, schema)
        self.assertEqual(findings, [])

    def test_cast_is_grouped_so_headless_bots_get_a_master(self):
        d = _load_decree()
        cast_whos = [entry["who"] for entry in d["cast"]]
        self.assertIn("family:zug", cast_whos)
        groups = [item["group"] for item in d.get("arrange") or [] if "group" in item]
        self.assertTrue(
            any(g.get("members") == "family:zug" for g in groups),
            "family:zug must be arranged in a group so KeepRosterFollowing sets master",
        )
        online_obs = [o for o in d["observe"] if o.get("online") == "cast"]
        self.assertEqual(len(online_obs), 1)

    def test_act_starts_with_on_mesh_probe_then_past_limit_moves(self):
        d = _load_decree()
        go_steps = []
        for step in d["act"]:
            cmd = step.get("command")
            if cmd and cmd.get("kind") == "bot":
                m = GO_XY_RE.match(cmd["text"])
                self.assertIsNotNone(m, f"unexpected bot command: {cmd['text']!r}")
                go_steps.append((step["at"], float(m.group(1)), float(m.group(2))))

        self.assertGreaterEqual(len(go_steps), 3)
        first_at, x1, y1 = go_steps[0]
        self.assertGreaterEqual(
            int(first_at.rstrip("s")),
            45,
            "first go must wait past one 30s PARTY_POLL_MS poll for master assignment",
        )
        probe_dist = math.hypot(x1 - START_X, y1 - START_Y)
        self.assertGreater(probe_dist, 20.0)
        self.assertLess(probe_dist, 100.0)

        for _, xf, yf in go_steps[1:]:
            far_dist_from_probe = math.hypot(xf - x1, yf - y1)
            self.assertGreater(
                far_dist_from_probe,
                300.0,
                "far go command must exceed the 74-point (~296 yd) navmesh limit",
            )

    def test_unmoved_bot_is_invalid_never_pass(self):
        d = _load_decree()
        verdict, failed_pre, _ = _eval_verdict(
            d, start_xy=(START_X, START_Y), end_xy=(START_X, START_Y)
        )
        self.assertEqual(verdict, "INVALID")
        self.assertTrue(
            any("moved" in name for name in failed_pre),
            f"expected a moved precondition to fail when Uzza never moved; got {failed_pre}",
        )

    def test_treatment_moves_on_probe_and_refuses_far_shortcut(self):
        d = _load_decree()
        go_steps = [
            GO_XY_RE.match(step["command"]["text"]).groups()
            for step in d["act"]
            if step.get("command", {}).get("kind") == "bot"
        ]
        probe_xy = (float(go_steps[0][0]), float(go_steps[0][1]))
        verdict, failed_pre, failed_checks = _eval_verdict(
            d, start_xy=(START_X, START_Y), end_xy=probe_xy
        )
        self.assertEqual(
            verdict,
            "PASS",
            f"failed_pre={failed_pre}, failed_checks={failed_checks}",
        )

    def test_control_carried_onto_far_point_is_fail(self):
        d = _load_decree()
        go_steps = [
            GO_XY_RE.match(step["command"]["text"]).groups()
            for step in d["act"]
            if step.get("command", {}).get("kind") == "bot"
        ]
        far_xy = (float(go_steps[-1][0]), float(go_steps[-1][1]))
        verdict, failed_pre, failed_checks = _eval_verdict(
            d, start_xy=(START_X, START_Y), end_xy=far_xy
        )
        self.assertEqual(verdict, "FAIL", f"failed_pre={failed_pre}")
        self.assertIn("uzza-was-not-carried-onto-the-point", failed_checks)


if __name__ == "__main__":
    unittest.main()
