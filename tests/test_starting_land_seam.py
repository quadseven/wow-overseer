"""Every planner asks one zone-aware question about where a member stands.

The Blood Elf and Draenei starting lands are on map 530 with Outland. A check
that reads the map alone calls a member levelling in Eversong Woods or on
Azuremyst Isle "in Outland" and leaves it out of the corps' posts, the
gathering assignments, the bag steps, the raid supply and the mailbox walks.
`classic.outside_at(map_id, zone_id)` and `classic.stands_outside(member)` are
the one question; these tests replay a member standing in each starting land
through every planner that used to ask the map alone.
"""

import pathlib
import re
import unittest

import auction
import classic
import farmassign
import guildbags
import guildcorps
import guildjobs
import guildroute
import modsource

ROOT = pathlib.Path(__file__).resolve().parents[1]

EVERSONG = 3430
AZUREMYST = 3524
NORTH_SEA = 3455
HELLFIRE = 3483
QUEL_DANAS = 4080

STARTING = (EVERSONG, AZUREMYST)


def _module_names_north_sea() -> bool:
    try:
        text = modsource.read(modsource.DECISIONS_H, encoding="utf-8")
    except Exception:  # noqa: BLE001 - an unread submodule names nothing
        return False
    return bool(re.search(r"constexpr uint32_t NORTH_SEA_ZONE_ID = 3455;", text))


class TheQuestion(unittest.TestCase):
    def test_a_starting_land_is_inside(self):
        for zone in STARTING:
            self.assertFalse(classic.outside_at(530, zone), zone)

    def test_outland_proper_and_northrend_are_outside(self):
        self.assertTrue(classic.outside_at(530, HELLFIRE))
        self.assertTrue(classic.outside_at(530, QUEL_DANAS))
        self.assertTrue(classic.outside_at(571, AZUREMYST))
        self.assertTrue(classic.outside_at(530, None))

    def test_azeroth_and_an_unread_map_are_not_judged_outside(self):
        self.assertFalse(classic.outside_at(0, 12))
        self.assertFalse(classic.outside_at(1, None))
        self.assertFalse(classic.outside_at(None, None))

    def test_stands_outside_reads_a_member_s_map_and_zone(self):
        class M:
            map_id, zone_id = 530, AZUREMYST

        class NoZone:
            map_id = 530

        self.assertFalse(classic.stands_outside(M()))
        self.assertTrue(classic.stands_outside(NoZone()))

    def test_the_note_names_the_land_for_a_member(self):
        class M:
            map_id, zone_id = 530, HELLFIRE

        self.assertEqual(
            classic.outside_note_for("Zora", M()),
            "Zora stands in Outland, outside the classic world",
        )

    @unittest.skipUnless(
        _module_names_north_sea(),
        "the pinned mod-overseer does not name The North Sea yet; 3455 joins "
        "classic.STARTING_LAND_ZONES with the pin move past mod-overseer#1528",
    )
    def test_the_north_sea_is_inside_once_the_module_says_so(self):
        self.assertFalse(classic.outside_at(530, NORTH_SEA))

    def test_the_north_sea_follows_the_list(self):
        """Until the pin moves, the bridge and the module agree 3455 is out."""
        self.assertEqual(
            classic.outside_at(530, NORTH_SEA),
            NORTH_SEA not in classic.STARTING_LAND_ZONES,
        )


def corps_member(name, zone, **kw):
    base = dict(
        name=name,
        guild="Cave",
        online=True,
        map_id=530,
        zone_id=zone,
        maintenance=True,
    )
    base.update(kw)
    return guildcorps.Member(**base)


class TheCorpsMember(unittest.TestCase):
    def test_the_corps_member_carries_its_zone(self):
        rows = [
            dict(
                guild_name="Cave",
                guid=1,
                name="Elfa",
                online=1,
                map_id=530,
                zone_id=EVERSONG,
                level=12,
            )
        ]
        (m,) = guildcorps.members_from_rows(rows, (), (), (), (), (), (), ())
        self.assertEqual(m.zone_id, EVERSONG)

    def test_a_tailor_in_a_starting_land_is_not_left_out(self):
        for zone in STARTING:
            notes = []
            post = guildcorps.Post("Elfa", "tailor", 197, 50, 75)
            t = corps_member("Elfa", zone)
            got = guildcorps._working_tailor(post, {"Elfa": t}, set(), notes)
            self.assertIs(got, t, zone)
            self.assertEqual(notes, [])

    def test_a_tailor_in_hellfire_still_is(self):
        notes = []
        post = guildcorps.Post("Orca", "tailor", 197, 50, 75)
        t = corps_member("Orca", HELLFIRE)
        self.assertIsNone(guildcorps._working_tailor(post, {"Orca": t}, set(), notes))
        self.assertIn("outside the classic world", notes[0])

    def test_places_keep_a_starting_land_trainer(self):
        rows = [
            {"map_id": 530, "zone_id": EVERSONG, "spell": 1},
            {"map_id": 530, "zone_id": HELLFIRE, "spell": 2},
        ]
        self.assertEqual(
            guildcorps.places_from_rows(rows, "spell"), {530: frozenset({1})}
        )


class TheGatherersAndCrafters(unittest.TestCase):
    def test_farmassign_takes_a_gatherer_in_a_starting_land(self):
        post = guildcorps.Post("Elfa", "miner", 186, 50, 75)
        for zone in STARTING:
            m = corps_member("Elfa", zone, skills={186: (50, 75)})
            self.assertEqual(
                [x.name for x in farmassign._online_gatherers([post], [m], 186, set())],
                ["Elfa"],
                zone,
            )
        far = corps_member("Elfa", HELLFIRE, skills={186: (50, 75)})
        self.assertEqual(farmassign._online_gatherers([post], [far], 186, set()), [])


def jobs_member(zone, **kw):
    base = dict(
        name="Elfa",
        guild="Cave",
        role=guildjobs.MAINTENANCE,
        eligible=True,
        online=True,
        alive=True,
        in_combat=False,
        map_id=530,
        zone_id=zone,
        x=1.0,
        y=1.0,
        free_slots=0,
    )
    base.update(kw)
    return guildjobs.Member(**base)


class TheBagSteps(unittest.TestCase):
    def test_a_member_in_a_starting_land_may_get_a_bag(self):
        for zone in STARTING:
            self.assertTrue(guildbags.eligible(jobs_member(zone)), zone)
            self.assertTrue(guildbags.equip_eligible(jobs_member(zone)), zone)
        self.assertFalse(guildbags.eligible(jobs_member(HELLFIRE)))
        self.assertFalse(guildbags.equip_eligible(jobs_member(HELLFIRE)))


class TheMailboxWalk(unittest.TestCase):
    def test_a_walker_in_a_starting_land_is_walked(self):
        for zone in STARTING:
            w = guildroute.Walker(
                name="Elfa", map_id=530, zone_id=zone, aim="mailbox", yards=40.0
            )
            self.assertEqual(guildroute.cannot_walk(w, "Elfa"), "", zone)
        w = guildroute.Walker(
            name="Elfa", map_id=530, zone_id=HELLFIRE, aim="mailbox", yards=40.0
        )
        self.assertIn("outside the classic world", guildroute.cannot_walk(w, "Elfa"))


class TheAuctioneer(unittest.TestCase):
    def test_a_starting_capital_s_house_is_open(self):
        self.assertTrue(auction.auctioneer_map_available(530, {530}, zone_id=EVERSONG))
        self.assertFalse(auction.auctioneer_map_available(530, {530}, zone_id=HELLFIRE))
        # Without a zone the map alone still refuses, as before.
        self.assertFalse(auction.auctioneer_map_available(530, {530}))


class NoMapOnlyChecksAreLeft(unittest.TestCase):
    """The planners that judge where a MEMBER stands ask the zone-aware
    question. dungeonplan judges instance maps (doors and destinations), and
    guildlevel's `_away` routes a team already known to be off the classic
    continents; both keep the map question on purpose."""

    ALLOWED = {"dungeonplan.py", "guildlevel.py", "classic.py"}

    def test_no_member_check_asks_the_map_alone(self):
        offenders = []
        for path in sorted(ROOT.glob("*.py")):
            if path.name in self.ALLOWED:
                continue
            text = path.read_text(encoding="utf-8")
            for n, line in enumerate(text.splitlines(), 1):
                if "classic.is_expansion_map(" in line:
                    offenders.append("%s:%d" % (path.name, n))
        self.assertEqual(offenders, [])

    def test_raidsupply_asks_the_member(self):
        text = (ROOT / "raidsupply.py").read_text(encoding="utf-8")
        self.assertNotIn("is_expansion_map", text)
        self.assertIn("classic.stands_outside(", text)


class TheBridgeReadsTheZone(unittest.TestCase):
    def test_the_corps_member_read_has_the_zone(self):
        bridge = (ROOT / "bridge.py").read_text(encoding="utf-8")
        sql = bridge.split("_CORPS_MEMBERS_SQL = (", 1)[1][:400]
        self.assertIn("c.zone AS zone_id", sql)


if __name__ == "__main__":
    unittest.main()
