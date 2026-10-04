"""Per-spec gear scoring and best-in-slot standing (#539).

Every test imports gearscore, so each fails without the module.
"""

import json
import unittest

import gearscore as gs

MAGE_HEAD = gs.slot_list("mage-dps", "preraid", "head")


class RatingConversionTests(unittest.TestCase):
    def test_level_60_values_come_from_the_server_table(self):
        self.assertEqual(gs.rating_per_pct("hit_melee", "mage"), 10.0)
        self.assertEqual(gs.rating_per_pct("hit_spell", "mage"), 8.0)
        self.assertEqual(gs.rating_per_pct("crit_spell", "mage"), 14.0)
        self.assertEqual(gs.rating_per_pct("dodge", "warrior"), 13.8)
        self.assertEqual(gs.rating_per_pct("defense", "warrior"), 1.5)

    def test_hybrid_melee_haste_is_cheaper(self):
        self.assertEqual(gs.rating_per_pct("haste_melee", "warrior"), 10.0)
        self.assertAlmostEqual(gs.rating_per_pct("haste_melee", "paladin"), 7.692)

    def test_rating_to_percent_at_60(self):
        self.assertAlmostEqual(gs.rating_to_pct("crit_rating", 28, "mage"), 2.0)
        self.assertAlmostEqual(gs.rating_to_pct("hit_spell_rating", 16, "mage"), 2.0)
        # Lionheart Helm: 28 crit and 20 hit rating are 2% each at 60.
        self.assertAlmostEqual(gs.rating_to_pct("hit_rating", 20, "warrior"), 2.0)

    def test_a_lower_level_needs_less_rating_per_percent(self):
        self.assertAlmostEqual(gs.level_scale(60), 1.0)
        self.assertAlmostEqual(gs.level_scale(34), 0.5)
        self.assertGreater(
            gs.rating_to_pct("crit_rating", 14, "mage", 34),
            gs.rating_to_pct("crit_rating", 14, "mage", 60),
        )
        self.assertEqual(gs.level_scale(70), 1.0)


class ScoreTests(unittest.TestCase):
    def test_mage_prefers_intellect_and_spell_power_over_strength_of_higher_ilvl(self):
        caster = {"intellect": 18, "spell_power": 24, "stamina": 10}
        warrior_piece = {"strength": 30, "stamina": 25, "agility": 12, "armor": 400}
        # item level is not an input: only stats count.
        self.assertGreater(
            gs.score(caster, "mage-dps"), gs.score(warrior_piece, "mage-dps")
        )
        self.assertGreater(
            gs.score(warrior_piece, "warrior-fury"), gs.score(caster, "warrior-fury")
        )

    def test_rating_scores_through_the_conversion(self):
        # 14 crit rating is 1% crit at 60; mage SpellCrit weight is 13.91.
        self.assertAlmostEqual(
            gs.score({"crit_spell_rating": 14}, "mage-dps"), 13.91, places=4
        )
        # The same rating is worth more at level 34 (half the rating per percent).
        self.assertAlmostEqual(
            gs.score({"crit_spell_rating": 14}, "mage-dps", level=34), 27.82, places=4
        )

    def test_generic_hit_rating_counts_melee_and_spell_sides(self):
        # Enhancement weighs both; fury weighs melee hit only.
        enh = gs.score({"hit_rating": 80}, "shaman-enhancement")
        fury = gs.score({"hit_rating": 80}, "warrior-fury")
        self.assertAlmostEqual(fury, 8.0 * 28.67, places=3)
        self.assertGreater(enh, 0)

    def test_healer_spell_power_is_scaled_for_the_server(self):
        w = gs.load_spec("priest-holy")["weights"]["values"]["SpellPower"]
        self.assertAlmostEqual(
            gs.score({"spell_power": 10}, "priest-holy"),
            10 * w * gs.HEALING_SPELL_POWER_SCALE,
        )

    def test_weapon_dps_uses_the_slot_weight(self):
        main = gs.score({"weapon_dps": 20}, "warrior-fury", slot="main_hand")
        off = gs.score({"weapon_dps": 20}, "warrior-fury", slot="off_hand")
        self.assertAlmostEqual(main, 20 * 11.92)
        self.assertAlmostEqual(off, 20 * 4.69)

    def test_unknown_spec_is_loud(self):
        with self.assertRaises(KeyError):
            gs.score({"strength": 1}, "mage-fire")

    def test_stats_from_item_template_row(self):
        row = {
            "stat_type1": 5,
            "stat_value1": 12,
            "stat_type2": 32,
            "stat_value2": 14,
            "stat_type3": 45,
            "stat_value3": 20,
            "stat_type4": 0,
            "stat_value4": 0,
            "armor": 60,
            "fire_res": 5,
            "dmg_min1": 40,
            "dmg_max1": 60,
            "delay": 2500,
        }
        self.assertEqual(
            gs.stats_from_row(row),
            {
                "intellect": 12,
                "crit_rating": 14,
                "spell_power": 20,
                "armor": 60,
                "fire_resistance": 5,
                "weapon_dps": 20.0,
            },
        )


class StandingTests(unittest.TestCase):
    def setUp(self):
        self.best, self.alt = MAGE_HEAD[0], MAGE_HEAD[1]
        self.strong = {"intellect": 20, "spell_power": 40, "crit_rating": 14}
        self.weak = {"intellect": 10, "spell_power": 20}
        self.stats = {i: self.weak for i in MAGE_HEAD}
        self.stats[self.best] = self.strong

    def test_listed_best_ranks_first_in_the_preraid_list(self):
        s = gs.standing("mage-dps", "head", self.best, self.stats)
        self.assertEqual((s.phase, s.rank), ("preraid", 1))
        self.assertEqual(s.best_id, self.best)
        self.assertAlmostEqual(s.pct_of_best, 1.0)

    def test_list_item_with_weaker_server_stats_drops_below_an_alternative(self):
        # The guide names `best` first, but here it carries the weaker stats.
        stats = {i: self.weak for i in MAGE_HEAD}
        stats[self.alt] = self.strong
        s = gs.standing("mage-dps", "head", self.best, stats)
        self.assertEqual(s.rank, 2)
        self.assertEqual(s.best_id, self.alt)
        self.assertLess(s.pct_of_best, 1.0)
        top = gs.standing("mage-dps", "head", self.alt, stats)
        self.assertEqual(top.rank, 1)

    def test_item_only_in_the_raid_list_reports_raid(self):
        mc_only = next(
            i for i in gs.slot_list("mage-dps", "mc", "head") if i not in MAGE_HEAD
        )
        stats = dict(self.stats)
        stats[mc_only] = self.strong
        s = gs.standing("mage-dps", "head", mc_only, stats)
        self.assertEqual(s.phase, "raid")

    def test_unlisted_item_is_ranked_by_score_against_the_preraid_list(self):
        stats = dict(self.stats)
        stats[999999] = {"intellect": 30, "spell_power": 80}
        s = gs.standing("mage-dps", "head", 999999, stats)
        self.assertEqual((s.phase, s.rank), ("", 1))
        stats[999998] = {"strength": 50}
        s = gs.standing("mage-dps", "head", 999998, stats)
        self.assertEqual(s.rank, len(MAGE_HEAD) + 1)

    def test_entries_without_known_stats_are_skipped_not_zero(self):
        s = gs.standing("mage-dps", "head", self.best, {self.best: self.strong})
        self.assertEqual((s.rank, s.size), (1, 1))

    def test_upgrade_comparison(self):
        self.assertTrue(gs.is_upgrade("mage-dps", self.strong, self.weak))
        self.assertFalse(gs.is_upgrade("mage-dps", self.weak, self.strong))
        self.assertTrue(gs.is_upgrade("mage-dps", self.weak, None))
        self.assertFalse(gs.is_upgrade("mage-dps", self.weak, self.weak))

    def test_next_target_aims_preraid_then_raid(self):
        tgt = gs.next_target("mage-dps", "head", self.weak, self.stats)
        self.assertEqual(tgt[:2], ("preraid", self.best))
        # Wearing the best pre-raid piece, nothing pre-raid beats it: aim raid.
        mc = gs.slot_list("mage-dps", "mc", "head")
        stats = dict(self.stats)
        for i in mc:
            stats.setdefault(i, self.weak)
        stats[mc[0]] = {"intellect": 40, "spell_power": 90}
        tgt = gs.next_target("mage-dps", "head", self.strong, stats)
        self.assertEqual((tgt[0], tgt[1]), ("raid", mc[0]))
        self.assertIsNone(
            gs.next_target("mage-dps", "head", {"spell_power": 500}, self.stats)
        )


class DataTests(unittest.TestCase):
    def test_all_eighteen_specs_load_with_weights_and_both_lists(self):
        ids = gs.spec_ids()
        self.assertEqual(len(ids), 18)
        for spec in ids:
            d = gs.load_spec(spec)
            self.assertTrue(d["weights"]["values"], spec)
            for phase in ("preraid", "mc"):
                lst = d["lists"][phase]
                self.assertTrue(lst["source_url"].startswith("https://"), spec)
                self.assertTrue(lst["slots"], spec)
                for ids_ in lst["slots"].values():
                    self.assertTrue(all(isinstance(i, int) for i in ids_))

    def test_weights_keep_their_mit_attribution(self):
        notice = (gs.DATA_DIR / "NOTICE.txt").read_text(encoding="utf-8")
        self.assertIn("MIT", gs.load_spec("warrior-fury")["weights"]["source"])
        self.assertIn("wowsims team", notice)
        wowsims = json.loads((gs.DATA_DIR / "weights-wowsims.json").read_text())
        self.assertEqual(wowsims["license"], "MIT")

    def test_data_is_ascii_without_guide_prose(self):
        for p in gs.DATA_DIR.iterdir():
            p.read_bytes().decode("ascii")

    def test_pvp_honor_items_are_kept(self):
        sit = gs.load_situational()
        self.assertTrue(sit["pvp_honor_by_class"]["classes"])
        self.assertTrue(sit["battleground_reputation"]["slots"])


if __name__ == "__main__":
    unittest.main()
