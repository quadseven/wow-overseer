"""Policy.acted's agreement branch honors can_act (#2134).

Agreement with the heuristic counted as acted (BOTH) at any confidence when the
policy set on_agreement, and the branch never looked at can_act, so a caller
that fenced what Jev may act on with can_act had no fence for an agreement.
Found while fixing the loot council's fit gates (#2124).
"""

import unittest

import jev


class AgreementHonorsCanAct(unittest.TestCase):
    def test_an_agreement_with_a_name_the_policy_may_not_act_on_does_not_act(self):
        for kind in ("loot_council", "route", "a_kind_nobody_wrote_yet"):
            for on_agreement in (False, True):
                rule = jev.Policy(kind, jev.ACT, 0.5, on_agreement=on_agreement)
                self.assertEqual(
                    jev.HEURISTIC,
                    rule.acted("a", "a", 0.9, can_act=False),
                    (kind, on_agreement),
                )

    def test_an_agreement_it_may_act_on_still_counts(self):
        rule = jev.Policy("k", jev.ACT, 0.8, on_agreement=True)
        self.assertEqual(jev.BOTH, rule.acted("a", "a", 0.4, can_act=True))
        self.assertEqual(jev.BOTH, rule.acted("a", "a", 0.4))
        confident = jev.Policy("k", jev.ACT, 0.8)
        self.assertEqual(jev.BOTH, confident.acted("a", "a", 0.9, can_act=True))

    def test_a_disagreement_is_fenced_as_before(self):
        rule = jev.Policy("k", jev.ACT, 0.5)
        self.assertEqual(jev.HEURISTIC, rule.acted("a", "b", 0.9, can_act=False))
        self.assertEqual(jev.JEV, rule.acted("a", "b", 0.9, can_act=True))


if __name__ == "__main__":
    unittest.main()
