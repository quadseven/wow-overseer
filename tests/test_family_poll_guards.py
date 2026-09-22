"""The family-scoped polls compare replies by the family the server drew.

Same text seam as test_lineup_tab.py. #143 guarded the quest and needs polls
by the key they ASKED for, so a bare load (key "") threw both replies away the
moment /api/family resolved the key to a name, leaving the board empty for a
whole 30 second tick. #156 left the agenda poll with no guard at all, so a
family switch mid-request could draw the family just left as the banner.

Tickets: #161, #143, #156.
"""
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")


def _fn(name):
    body = PAGE[PAGE.index("async function " + name + "()"):]
    return body[:body.index("\n}\n")]


class TheRepliesAreJudgedByTheFamilyDrawn(unittest.TestCase):

    def test_needs_compares_the_family_the_server_drew(self):
        self.assertIn("if ((p.family || asked) !== familyKey", _fn("pollNeeds"))

    def test_quests_compares_the_family_the_server_drew(self):
        self.assertIn("if ((p.family || asked) !== familyKey", _fn("pollQuests"))

    def test_agenda_drops_a_reply_for_a_family_left_behind(self):
        body = _fn("pollAgenda")
        guard = "if (familyKey && (p.family || asked) !== familyKey) return;"
        self.assertIn(guard, body)
        self.assertLess(body.index(guard), body.index("renderAgenda(p);"))

    def test_a_pasted_family_link_moves_the_banner_at_once(self):
        body = PAGE[PAGE.index("function applyHash()"):]
        body = body[:body.index("\n}\n")]
        self.assertIn("if (familyKey !== before) pollAgenda();", body)


if __name__ == "__main__":
    unittest.main()
