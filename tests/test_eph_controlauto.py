"""submit --control auto: the pure choice and the dropped-keys computation."""

import unittest

from ephemeral import controlauto

D = "@sha256:" + "a" * 64
SHA = lambda c: c * 40  # noqa: E731


def entry(pin, name, **kw):
    return {
        "worldserver": f"ws-{name}{D}",
        "dbimport": f"db-{name}{D}",
        "pin": SHA(pin),
        **kw,
    }


class Pick(unittest.TestCase):
    def presence(self, fixed):
        return lambda sha: "present" if sha in fixed else "absent"

    def test_newest_set_without_the_fix_wins(self):
        h = [entry("1", "new"), entry("2", "mid"), entry("3", "old")]
        got = controlauto.pick_control(h, self.presence({SHA("1")}), lambda r: True)
        self.assertEqual(got["pin"], SHA("2"))

    def test_refuses_when_every_set_has_the_fix(self):
        h = [entry("1", "a"), entry("2", "b")]
        with self.assertRaisesRegex(controlauto.AutoError, "lacks the fix"):
            controlauto.pick_control(h, lambda s: "present", lambda r: True)

    def test_refuses_when_digests_do_not_resolve(self):
        h = [entry("1", "a")]
        with self.assertRaisesRegex(controlauto.AutoError, "do not resolve"):
            controlauto.pick_control(h, lambda s: "absent", lambda r: False)

    def test_skips_a_set_whose_digest_is_gone_for_an_older_one(self):
        h = [entry("1", "gone"), entry("2", "kept")]
        got = controlauto.pick_control(h, lambda s: "absent", lambda r: "gone" not in r)
        self.assertEqual(got["pin"], SHA("2"))

    def test_unchecked_is_not_absent(self):
        with self.assertRaises(controlauto.AutoError):
            controlauto.pick_control(
                [entry("1", "a")], lambda s: "unchecked", lambda r: True
            )

    def test_empty_history_refuses(self):
        with self.assertRaisesRegex(controlauto.AutoError, "empty"):
            controlauto.pick_control([], lambda s: "absent", lambda r: True)

    def test_bridge_fix_judges_by_bridge_commit_and_needs_the_bridge_image(self):
        h = [
            entry("1", "a", bridge=f"br-a{D}", bridge_commit=SHA("9")),
            entry("2", "b", bridge=f"br-b{D}", bridge_commit=SHA("8")),
            entry("3", "c", bridge_commit=SHA("7")),
        ]
        got = controlauto.pick_control(
            h, self.presence({SHA("9")}), lambda r: True, bridge_fix=True
        )
        self.assertEqual(got["bridge_commit"], SHA("8"))


class Dropped(unittest.TestCase):
    DIST = (
        "Overseer.Old = 1\n# Overseer.Commented = 0\n#    Overseer.DocOnly\nOther = 2\n"
    )
    OVERRIDE = (
        "Overseer.Old = 5\nOverseer.Commented = 1\nOverseer.New = 3\n"
        "Overseer.DocOnly = 4\n# Overseer.Skipped = 9\n"
    )

    def test_keys_the_dist_predates_are_dropped(self):
        self.assertEqual(
            controlauto.dropped_keys(self.DIST, self.OVERRIDE),
            ["Overseer.DocOnly", "Overseer.New"],
        )

    def test_nothing_dropped_when_the_dist_knows_all(self):
        self.assertEqual(
            controlauto.dropped_keys("A = 1\nB = 2\n", "A = 3\nB = 4\n"), []
        )

    def test_a_missing_dist_or_override_is_empty(self):
        self.assertEqual(controlauto.dropped_keys(None, "A = 1\n"), ["A"])
        self.assertEqual(controlauto.dropped_keys("A = 1\n", None), [])


if __name__ == "__main__":
    unittest.main()
