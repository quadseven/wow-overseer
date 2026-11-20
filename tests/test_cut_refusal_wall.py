"""A crossing refusal cut short by the read still walls the map (#2994)."""

import unittest

import classquest
import guildjobs

CLAUSE = "'Ship (A)' boarding and landing both select stop 1 on map 1; "


def _row(result):
    return {
        "id": 1,
        "target_name": "Memb",
        "command": "cross-to-map map:0",
        "source": "guildjobs:train-cross:Memb",
        "status": "error",
        "target_arg": "",
        "result": result,
        "age": 5,
    }


class CutRefusal(unittest.TestCase):
    def test_a_result_cut_inside_the_reason_keeps_the_reason(self):
        head = '{"outcome":"refused","reason":"' + CLAUSE * 20
        cut = head[:400]
        (recent,) = guildjobs.recent_from_rows([_row(cut)])
        self.assertTrue(recent.refusal.startswith("'Ship (A)' boarding"))

    def test_a_cut_routeless_refusal_stands_as_a_wall(self):
        head = '{"outcome":"refused","reason":"' + CLAUSE * 20
        recent = guildjobs.recent_from_rows([_row(head[:400])])
        self.assertEqual(set(guildjobs.class_walls("Memb", recent)), {0})
        self.assertTrue(classquest.is_cross_wall(recent[0].refusal))

    def test_a_whole_result_still_ends_at_its_closing_quote(self):
        whole = (
            '{"outcome":"refused","reason":"the character is in combat",'
            '"retry":true}'
        )
        (recent,) = guildjobs.recent_from_rows([_row(whole)])
        self.assertEqual(recent.refusal, "the character is in combat")


if __name__ == "__main__":
    unittest.main()
