"""The bridge uses the claims facade for each kind of hold (#1950)."""

import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")
TREE = ast.parse(BRIDGE)


def _path(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _path(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


class ClaimsFacadeWiring(unittest.TestCase):
    def test_bridge_routes_claims_through_one_facade(self):
        calls = [
            _path(node.func)
            for node in ast.walk(TREE)
            if isinstance(node, ast.Call)
        ]

        self.assertEqual(1, calls.count("claims.Claims"))
        for method in ("slot_for", "member_observe", "member_released", "release_ground"):
            self.assertTrue(
                any(path.endswith(f".{method}") for path in calls),
                f"bridge.py does not call Claims.{method}",
            )

        self.assertNotIn("claims.new_column_slot", calls)
        self.assertNotIn("claims.may_release_ground", calls)
        self.assertNotIn("townslot.Slot", calls)

    def test_hold_and_ground_release_reasons_are_logged(self):
        why_values = []
        for call in ast.walk(TREE):
            if not isinstance(call, ast.Call) or not _path(call.func).startswith("log."):
                continue
            for arg in call.args:
                why_values.extend(
                    _path(node)
                    for node in ast.walk(arg)
                    if isinstance(node, ast.Attribute) and node.attr == "why"
                )

        self.assertIn("hold.why", why_values)
        self.assertIn("release.why", why_values)


if __name__ == "__main__":
    unittest.main()
