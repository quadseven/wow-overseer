import pathlib
import unittest


PATCH = (
    pathlib.Path(__file__).parents[1]
    / "patches/mod-playerbots"
    / "0016-a-mage-only-conjures-food-at-a-usable-rank.patch"
)


class ConjureRankPatchTest(unittest.TestCase):
    def test_patch_rejects_products_above_the_casters_level(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("proto->RequiredLevel > bot->GetLevel()", source)
        self.assertIn("bot->CanUseItem(proto) != EQUIP_ERR_OK", source)

    def test_patch_keeps_the_lower_rank_selection_loop(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("if (spellInfo->Id > castId)", source)
        self.assertIn("continue;", source)


if __name__ == "__main__":
    unittest.main()
