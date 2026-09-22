"""The zone regions: the map's geometry, asserted rather than eyeballed.

shapes.json is a committed artifact built from another committed artifact
(zones.json, itself frozen 3.3.5a client data). The point of these tests is
that the committed file is re-derivable and that the derivation holds its
invariants - a checked-in blob nobody can reproduce is a fact with no source.
"""

import importlib.util
import json
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "gen_shapes", HERE / "tools" / "gen_shapes.py"
)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


class CommittedFileMatchesTheGenerator(unittest.TestCase):
    """The whole reason the output can be trusted."""

    @classmethod
    def setUpClass(cls):
        cls.committed = json.loads((HERE / "shapes.json").read_text())
        cls.fresh = gen.generate(str(HERE))

    def test_regenerating_reproduces_the_committed_bytes(self):
        """Byte-for-byte, through the same serialiser main() uses. If this
        fails, either the generator changed or shapes.json was hand-edited -
        both need the file regenerated, never patched."""
        dump = json.dumps(self.fresh, separators=(",", ":"), sort_keys=True)
        self.assertEqual((HERE / "shapes.json").read_text(), dump)

    def test_every_continent_the_dots_use_has_geometry(self):
        """The page tabs come from zones.json. A continent with no entry here
        renders as empty sea, which reads as a broken page, not an empty one."""
        zones = json.loads((HERE / "zones.json").read_text())["continents"]
        self.assertEqual(sorted(zones), sorted(self.committed))


class EveryZoneSurvives(unittest.TestCase):
    """A zone that vanishes between zones.json and shapes.json is a hole in
    the continent nobody would notice - the dots would still land on it."""

    @classmethod
    def setUpClass(cls):
        cls.zones = json.loads((HERE / "zones.json").read_text())["continents"]
        cls.shapes = json.loads((HERE / "shapes.json").read_text())

    def test_no_zone_is_silently_lost(self):
        for cid, cont in self.zones.items():
            got = (
                {z["name"] for z in self.shapes[cid]["zones"]}
                | {m["name"] for m in self.shapes[cid]["marks"]}
                | set(self.shapes[cid]["dropped"])
            )
            self.assertEqual({z["name"] for z in cont["zones"]}, got, cid)

    def test_anything_dropped_is_named_not_merely_absent(self):
        """Dalaran's WorldMapArea row is all zeros - the client's NULL, not a
        position. Dropping it is right; dropping it silently is how absent
        data becomes a fact. Every drop is listed in the output."""
        dropped = {n for c in self.shapes.values() for n in c["dropped"]}
        self.assertIn("Dalaran", dropped)

    def test_a_null_row_is_never_placed_at_the_projected_origin(self):
        """World (0,0) projects to a real-looking point on Northrend - just
        south of the coast. A gold capital marker bobbing offshore is a
        fabrication, so no mark may carry Dalaran's name."""
        for cid, c in self.shapes.items():
            self.assertNotIn("Dalaran", {m["name"] for m in c["marks"]}, cid)

    def test_every_zone_has_a_terrain_colour_chosen_on_purpose(self):
        """The default is a fallback, not a plan: a zone painted the default
        means the table missed it when the client data grew."""
        for cid, c in self.shapes.items():
            for z in c["zones"]:
                self.assertNotEqual(
                    gen.DEFAULT_TERRAIN,
                    z["fill"],
                    f"{cid}/{z['name']} has no terrain colour",
                )


class RegionsAreDisjoint(unittest.TestCase):
    """Rule 1 of the rewrite: the smallest box containing a point wins, so a
    point belongs to exactly one zone. Overlap is the bug being fixed."""

    def _owner_map(self, cid="0"):
        zones = json.loads((HERE / "zones.json").read_text())["continents"][cid]
        return gen.build(cid, zones)

    def test_a_city_inside_a_zone_takes_the_ground_from_it(self):
        """Ironforge's box sits wholly inside Dun Morogh's. Drawn raw that is
        two stacked outlines; here the tighter claim wins the cells."""
        r = self._owner_map("0")
        by = {z["name"]: z for z in r["zones"]}
        self.assertIn("Ironforge", by)
        self.assertIn("DunMorogh", by)
        self.assertGreater(by["Ironforge"]["cells"], 0)
        self.assertGreater(by["DunMorogh"]["cells"], by["Ironforge"]["cells"])

    def test_the_cells_of_all_zones_sum_to_the_land(self):
        """Disjointness itself is structural - the owner map is keyed by
        cell, so nothing can be claimed twice. What this catches is the other
        half: land left unclaimed, and regions lost between assignment and
        tracing. Sorting the boxes the wrong way makes small zones lose every
        cell they had, and the total goes short."""
        cid = "0"
        cont = json.loads((HERE / "zones.json").read_text())["continents"][cid]
        r = gen.build(cid, cont)
        aspect = abs((cont["top"] - cont["bottom"]) / (cont["left"] - cont["right"]))
        gw = gen.GRID_W
        gh = int(round(gw * aspect))
        land = sum(
            1
            for j in range(gh)
            for i in range(gw)
            if any(
                gen.inside(ring, (i + 0.5) / gw, (j + 0.5) / gh)
                for ring in gen.COASTS[cid]
            )
        )
        self.assertEqual(land, sum(z["cells"] for z in r["zones"]))
        self.assertGreater(land, 0)


class LabelAnchors(unittest.TestCase):
    """Where a zone's name goes. The centroid is wrong for any region that
    wraps another, and the Barrens wraps two."""

    def test_the_deepest_point_beats_the_centroid_on_a_horseshoe(self):
        """A C-shape's centroid falls in the gap - outside the region. The
        pole of inaccessibility cannot, by construction."""
        cells = (
            {(i, 0) for i in range(9)}
            | {(i, 4) for i in range(9)}
            | {(0, j) for j in range(5)}
        )
        cx = sum(c[0] for c in cells) / len(cells)
        cy = sum(c[1] for c in cells) / len(cells)
        self.assertNotIn((round(cx), round(cy)), cells, "centroid escapes the shape")
        deep, room = gen.deepest(cells)
        self.assertIn(deep, cells)
        self.assertGreaterEqual(room, 1)

    def test_a_solid_block_anchors_near_its_middle(self):
        cells = {(i, j) for i in range(11) for j in range(11)}
        deep, room = gen.deepest(cells)
        self.assertEqual((5, 5), deep)
        self.assertEqual(5, room)

    def test_every_label_anchor_lies_on_its_own_ground(self):
        """An anchor outside its region puts the name over a neighbour."""
        shapes = json.loads((HERE / "shapes.json").read_text())
        zones = json.loads((HERE / "zones.json").read_text())["continents"]
        for cid, c in shapes.items():
            gw = gen.GRID_W
            aspect = c["aspect"]
            gh = int(round(gw * aspect))
            cont = zones[cid]
            r = gen.build(cid, cont)
            for z in r["zones"]:
                i = int(z["cx"] / 1000.0 * gw)
                j = int(z["cy"] / (1000.0 * aspect) * gh)
                self.assertTrue(
                    any(
                        gen.inside(ring, (i + 0.5) / gw, (j + 0.5) / gh)
                        for ring in gen.COASTS[cid]
                    ),
                    f"{cid}/{z['name']} anchors in the sea",
                )


class Geometry(unittest.TestCase):
    """The pure helpers, on shapes small enough to reason about."""

    def test_inside_is_true_within_and_false_without(self):
        square = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
        self.assertTrue(gen.inside(square, 0.5, 0.5))
        self.assertFalse(gen.inside(square, 0.1, 0.5))
        self.assertFalse(gen.inside(square, 0.5, 0.9))

    def test_inside_handles_a_concave_ring(self):
        """A ray through a C-shape crosses twice; even-odd must say outside."""
        c = [(0, 0), (3, 0), (3, 1), (1, 1), (1, 2), (3, 2), (3, 3), (0, 3)]
        self.assertTrue(gen.inside(c, 0.5, 1.5))
        self.assertFalse(gen.inside(c, 2.0, 1.5))

    def test_simplifying_a_straight_run_keeps_only_its_ends(self):
        line = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]
        self.assertEqual([(0, 0), (4, 0)], gen.rdp(line, 0.5))

    def test_simplifying_keeps_a_corner_worth_keeping(self):
        bend = [(0, 0), (2, 0), (2, 4)]
        self.assertEqual(3, len(gen.rdp(bend, 0.5)))

    def test_smoothing_cuts_corners_without_leaving_the_hull(self):
        square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        out = gen.chaikin(square, 1)
        self.assertEqual(8, len(out))
        for x, y in out:
            self.assertGreaterEqual(x, 0.0)
            self.assertLessEqual(x, 1.0)
            self.assertGreaterEqual(y, 0.0)
            self.assertLessEqual(y, 1.0)

    def test_paths_are_emitted_at_the_continent_aspect_not_in_a_square(self):
        """Emitting into 1000x1000 squashed every continent to half height -
        the first cut of this shipped and the map came out flattened."""
        d = gen.path([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], 1000.0, 1972.0)
        self.assertIn("1000.0 1972.0", d)
        self.assertTrue(d.endswith("Z"))

    def test_tracing_a_block_yields_one_closed_loop(self):
        loops = gen.trace({(i, j) for i in range(6) for j in range(6)}, 6, 6)
        self.assertEqual(1, len(loops))
        self.assertEqual(24, len(loops[0]))


class Names(unittest.TestCase):
    """WorldMapArea names are directory names; the map should read like the
    game, not like a folder listing."""

    def test_camel_case_becomes_words(self):
        self.assertEqual("Searing Gorge", gen.pretty("SearingGorge"))

    def test_the_client_s_own_misspellings_are_corrected(self):
        self.assertEqual("Orgrimmar", gen.pretty("Ogrimmar"))
        self.assertEqual("Azshara", gen.pretty("Aszhara"))
        self.assertEqual("Darnassus", gen.pretty("Darnassis"))
        self.assertEqual("Hillsbrad Foothills", gen.pretty("Hilsbrad"))


class TheMapIsWiredToTheGeometry(unittest.TestCase):
    """Asserted against the source: map_server imports pymysql and index.html
    is a browser page, so neither can be imported here. Every link in this
    chain fails SILENTLY - the pod starts, the page loads, the sea is empty."""

    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text()
        cls.page = (HERE / "index.html").read_text()

    def test_the_server_serves_the_geometry(self):
        table = self.server[self.server.index("GET_ROUTES = {") :]
        table = table[: table.index("}")]
        self.assertIn('"/shapes.json": _shapes_file', table)

    def test_the_page_asks_for_it(self):
        self.assertIn('fetch(u("/shapes.json"))', self.page)

    def test_the_page_no_longer_squashes_a_continent_to_fit(self):
        """The old height clamp (360..760px) flattened a 2:1 continent into a
        1.4:1 blob. Its return would look like a styling nit and read as the
        map being wrong again."""
        self.assertNotIn("Math.min(760", self.page)
        self.assertIn("fitContinent", self.page)

    def test_hit_testing_scales_to_the_device_pixel_ratio(self):
        """isPointInPath takes the point UNAFFECTED by the current transform
        while transforming the path by it, so passing CSS pixels never hits on
        a retina screen - and never throws, either."""
        fn = self.page[self.page.index("function zoneAt") :]
        fn = fn[: fn.index("\n}")]
        self.assertIn("devicePixelRatio", fn)


class EveryContinentHasACoast(unittest.TestCase):
    def test_a_continent_without_one_stops_the_build(self):
        """Rendering it as empty sea instead would look exactly like an
        outage, so the generator refuses rather than shipping a blank tab."""
        saved = dict(gen.COASTS)
        try:
            gen.COASTS.pop("530")
            with self.assertRaises(SystemExit) as caught:
                gen.generate(str(HERE))
            self.assertIn("530", str(caught.exception))
        finally:
            gen.COASTS.clear()
            gen.COASTS.update(saved)


if __name__ == "__main__":
    unittest.main()
