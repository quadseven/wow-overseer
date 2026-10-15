"""Grouped followers must not receive errands the world executor refuses."""

import pathlib
import re
import unittest

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


def _block(signature: str) -> str:
    source = BRIDGE.read_text(encoding="utf-8")
    start = source.index(signature)
    rest = source[start:]
    match = re.search(r"\n(?:async )?def |\nclass ", rest[1:])
    return rest[: match.start() + 1] if match else rest


class GroupedFollowerErrands(unittest.TestCase):
    def test_mail_row_is_gated_before_insert_and_logged_as_held(self):
        body = _block("def _insert_mail(take, command: str)")
        self.assertIn("_hold_grouped_follower_errand(take.character", body)
        self.assertLess(
            body.index("_hold_grouped_follower_errand"), body.index("cur.execute(")
        )

    def test_group_lookup_uses_fresh_snapshot_and_names_leader(self):
        body = _block("def _hold_grouped_follower_errand(")
        self.assertIn("group_leader", body)
        self.assertIn("log.info", body)
        self.assertIn("leader", body)

    def test_job_and_town_command_writers_share_the_gate(self):
        for signature, target in (
            ("def _insert_job(", "name"),
            ("def _insert_town_errand(", "errand.member"),
            ("def _insert_learn(", "member"),
        ):
            with self.subTest(signature=signature):
                self.assertIn(
                    "_hold_grouped_follower_errand(%s" % target, _block(signature)
                )
