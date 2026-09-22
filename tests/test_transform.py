"""Coordinate-transform tests pinned to real, known places.

Orgrimmar and Stormwind world coordinates are common knowledge for 3.3.5
(any GM `.gps` in those cities reproduces them within a few yards). The
assertions are positional truths - which half of which continent - so a
sign flip or axis swap in the transform fails loudly, while small numeric
drift does not.
"""

import unittest

from transform import Geometry

# .gps readings, city centers, 3.3.5a
ORGRIMMAR = (1573.0, -4399.0)  # map 1  (x north+, y west+)
STORMWIND = (-8842.0, 626.0)  # map 0
STOCKADE_MAP = 34  # instance inside Stormwind


class TransformTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geo = Geometry.load(".")

    def test_regions_present(self):
        self.assertEqual(
            set(self.geo.continents),
            {"0", "1", "530", "571", "quelthalas", "azuremyst"},
        )

    def test_every_zone_fits_inside_its_region(self):
        # THE invariant the first review caught being violated: a zone
        # rectangle outside its region's extent renders characters
        # off-canvas, invisibly and uncounted.
        for key, region in self.geo.continents.items():
            for z in region["zones"]:
                self.assertLessEqual(z["left"], region["left"], (key, z["name"]))
                self.assertGreaterEqual(z["right"], region["right"], (key, z["name"]))
                self.assertLessEqual(z["top"], region["top"], (key, z["name"]))
                self.assertGreaterEqual(z["bottom"], region["bottom"], (key, z["name"]))

    def test_blood_elves_route_to_quelthalas_not_outland(self):
        # Silvermoon City, physically map 530: .gps ~ (9738, -7454)
        placed = self.geo.place(530, 9738.0, -7454.0)
        self.assertIsNotNone(placed)
        key, u, v = placed
        self.assertEqual(key, "quelthalas")
        self.assertTrue(0.0 <= u <= 1.0 and 0.0 <= v <= 1.0, (u, v))
        self.assertEqual(self.geo.zone_name(530, 9738.0, -7454.0), "SilvermoonCity")

    def test_outland_proper_still_routes_to_outland(self):
        # Shattrath: .gps ~ (-1863, 5419)
        key, u, v = self.geo.place(530, -1863.0, 5419.0)
        self.assertEqual(key, "530")
        self.assertTrue(0.0 < u < 1.0 and 0.0 < v < 1.0, (u, v))

    def test_point_outside_every_region_clamps_instead_of_vanishing(self):
        key, u, v = self.geo.place(1, 99999.0, 99999.0)
        self.assertEqual(key, "1")
        self.assertTrue(0.0 <= u <= 1.0 and 0.0 <= v <= 1.0, (u, v))

    def test_orgrimmar_lands_in_east_kalimdor(self):
        u, v = self.geo.to_fraction(1, *ORGRIMMAR)
        self.assertTrue(0.0 < u < 1.0 and 0.0 < v < 1.0, (u, v))
        self.assertGreater(u, 0.5, "Orgrimmar is on Kalimdor's eastern side")
        self.assertLess(v, 0.55, "Orgrimmar is in Kalimdor's northern half")

    def test_stormwind_lands_in_southwest_ek(self):
        u, v = self.geo.to_fraction(0, *STORMWIND)
        self.assertTrue(0.0 < u < 1.0 and 0.0 < v < 1.0, (u, v))
        self.assertLess(u, 0.5, "Stormwind is on EK's western side")
        self.assertGreater(v, 0.6, "Stormwind is in EK's southern half")

    def test_axis_orientation_is_wow_not_screen(self):
        # +y is WEST: a more-westerly point must have a SMALLER u.
        u_west, _ = self.geo.to_fraction(0, 0.0, 2000.0)
        u_east, _ = self.geo.to_fraction(0, 0.0, -2000.0)
        self.assertLess(u_west, u_east)
        # +x is NORTH: a more-northerly point must have a SMALLER v.
        _, v_north = self.geo.to_fraction(0, 2000.0, 0.0)
        _, v_south = self.geo.to_fraction(0, -2000.0, 0.0)
        self.assertLess(v_north, v_south)

    def test_instance_dwellers_surface_at_their_entrance(self):
        placed = self.geo.place(STOCKADE_MAP, 0.0, 0.0)  # inside coords irrelevant
        self.assertIsNotNone(placed)
        continent, u, v = placed
        self.assertEqual(continent, "0")
        su, sv = self.geo.to_fraction(0, *STORMWIND)
        self.assertLess(
            abs(u - su) + abs(v - sv), 0.05, "Stockade surfaces beside Stormwind"
        )

    def test_continent_dwellers_place_directly(self):
        self.assertEqual(
            self.geo.place(1, *ORGRIMMAR), ("1", *self.geo.to_fraction(1, *ORGRIMMAR))
        )

    def test_unknown_instance_places_nowhere(self):
        self.assertIsNone(self.geo.place(99999, 0.0, 0.0))

    def test_zone_lookup_names_the_right_zone(self):
        # "Ogrimmar" is not a bug here: WorldMapArea.dbc genuinely spells its
        # internal name that way (a well-known Blizzard typo). We pin the
        # client's own data, not the display spelling.
        self.assertEqual(self.geo.zone_name(1, *ORGRIMMAR), "Ogrimmar")
        self.assertEqual(self.geo.zone_name(0, *STORMWIND), "Stormwind")


class ZoneById(unittest.TestCase):
    def setUp(self):
        from transform import Geometry

        self.geo = Geometry.load(".")

    def test_a_zone_id_names_its_zone(self):
        self.assertEqual(self.geo.zone_by_id(618), "Winterspring")
        self.assertEqual(self.geo.zone_by_id("361"), "Felwood")

    def test_nothing_usable_is_none(self):
        for bad in (None, 0, "", "x", 999999):
            self.assertIsNone(self.geo.zone_by_id(bad), bad)
