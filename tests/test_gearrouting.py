"""The guild gear-routing pass (gearrouting.py), judged by equipscore.

The equip pass already puts a member's OWN best carried piece on them. What
nobody did: look across the guild. A bind-on-equip upgrade sits in one
member's bags while another member wears an antique in that slot, and the
two facts never meet. These pin the pass that meets them - the same spec
gear score the equip pass uses (equipscore.choose), the same ten percent
margin, bind-on-equip copies only, one physical piece promised once.
"""

import pathlib
import unittest

import gearrouting as gr

MAP_SERVER = pathlib.Path(__file__).resolve().parents[1] / "map_server.py"

WARRIOR, ROGUE = 1, 4
HUMAN = 1
# Talent spells of the Protection tree (raidroles' talent book), as
# tests/test_equip_score.py spells them.
PROTECTION = "12666,12753,12764,12803,12804,12809,12818"
# Skill lines: swords 43, two-hand swords 55, mail 413, leather 414,
# cloth 415, plate 293, shield 433, dual wield 118, daggers 173.
WARRIOR_SKILLS = "43,44,54,55,413,414,415,433"
ROGUE_SKILLS = "43,173,414,415,118"

_GUID = [9000]


def piece(name, inv, item_class=4, subclass=1, level=20, req=15, stats=(), **kw):
    """One item row as the scored-gear read returns it, plus the two binding
    facts the routing read adds (`bonding`, `instance_flags`). `slot` makes
    it worn; without one it sits in its holder's bags."""
    _GUID[0] += 1
    row = dict(
        holder=kw.pop("holder", "Grug"),
        guild=kw.pop("guild", "Cave"),
        equipment_slot=kw.pop("slot", None),
        item_guid=kw.pop("guid", _GUID[0]),
        entry=kw.pop("entry", _GUID[0]),
        name=name,
        quality=2,
        item_level=level,
        required_level=req,
        item_class=item_class,
        item_subclass=subclass,
        inventory_type=inv,
        allowable_class=-1,
        allowable_race=-1,
        required_skill=0,
        required_skill_rank=0,
        required_spell=0,
        required_reputation=0,
        max_count=0,
        item_flags=0,
        bonding=kw.pop("bonding", 2),
        instance_flags=kw.pop("instance_flags", 0),
        armor=0,
        block=0,
        dmg_min1=0,
        dmg_max1=0,
        delay=0,
        random_property_id=0,
        enchantments="",
    )
    for n, (kind, amount) in enumerate(stats, start=1):
        row["stat_type%d" % n] = kind
        row["stat_value%d" % n] = amount
    row.update(kw)
    return row


AGI, STR, INT, SPI, STA, DEFENSE = 3, 4, 5, 6, 7, 12


def member(name, class_id, level, talents="", tree="", skills="", guild="Cave"):
    return dict(
        name=name,
        class_id=class_id,
        level=level,
        race=HUMAN,
        talent_spells=talents,
        target_tree=tree,
        skills=skills,
        guild=guild,
    )


def tank(name="Grug", guild="Cave"):
    return member(name, WARRIOR, 43, PROTECTION, skills=WARRIOR_SKILLS, guild=guild)


def old_breastplate(holder):
    return piece(
        "Old Breastplate",
        5,
        4,
        3,
        level=35,
        req=30,
        stats=((STA, 6),),
        armor=300,
        slot=4,
        holder=holder,
    )


def symbolic_breastplate(holder, **kw):
    return piece(
        "Symbolic Breastplate",
        5,
        4,
        3,
        level=43,
        req=38,
        stats=((STA, 14), (STR, 9)),
        armor=420,
        holder=holder,
        **kw,
    )


class AcrossTheGuild(unittest.TestCase):
    def test_a_better_piece_in_a_guildmates_bags_is_routed(self):
        """Grug wears an antique chest; Bork, who cannot wear plate at all,
        carries the upgrade. The route names both, the piece, what it
        replaces and the gain."""
        rows = [tank("Grug"), member("Bork", ROGUE, 43, skills=ROGUE_SKILLS)]
        gear = [old_breastplate("Grug"), symbolic_breastplate("Bork")]
        report = gr.plan(rows, gear)
        self.assertEqual(len(report.routes), 1)
        route = report.routes[0]
        self.assertEqual(route.wearer, "Grug")
        self.assertEqual(route.holder, "Bork")
        self.assertEqual(route.item, "Symbolic Breastplate")
        self.assertEqual(route.worn, "Old Breastplate")
        self.assertEqual(route.slot, "chest")
        self.assertGreater(route.gain, 0.1)
        self.assertIn("gear score", route.reason)


class BoundPiecesStayPut(unittest.TestCase):
    def _report(self, **kw):
        rows = [tank("Grug"), member("Bork", ROGUE, 43, skills=ROGUE_SKILLS)]
        gear = [old_breastplate("Grug"), symbolic_breastplate("Bork", **kw)]
        return gr.plan(rows, gear)

    def test_a_bind_on_pickup_piece_is_never_routed(self):
        self.assertEqual(self._report(bonding=1).routes, ())

    def test_a_soulbound_copy_of_a_bind_on_equip_piece_is_never_routed(self):
        """The template says bind-on-equip; the instance was worn once and
        is bound forever. The template reading alone would route it."""
        self.assertEqual(self._report(bonding=2, instance_flags=1).routes, ())

    def test_a_piece_whose_binding_cannot_be_read_is_never_routed(self):
        rows = [tank("Grug"), member("Bork", ROGUE, 43, skills=ROGUE_SKILLS)]
        carried = symbolic_breastplate("Bork")
        del carried["bonding"], carried["instance_flags"]
        report = gr.plan(rows, [old_breastplate("Grug"), carried])
        self.assertEqual(report.routes, ())


class TheMarginIsTheEquipPasssOwn(unittest.TestCase):
    def test_a_sidegrade_inside_the_margin_is_not_routed(self):
        """The same pair equipscore refuses as a sidegrade when the wearer
        carries it themselves: ten percent is the margin, here too."""
        rows = [tank("Grug"), member("Bork", ROGUE, 43, skills=ROGUE_SKILLS)]
        worn = piece(
            "Cloak A", 16, 4, 1, level=38, stats=((STA, 10),), slot=14, holder="Grug"
        )
        carried = piece(
            "Cloak B",
            16,
            4,
            1,
            level=45,
            stats=((STA, 10),),
            armor=5,
            holder="Bork",
        )
        self.assertEqual(gr.plan(rows, [worn, carried]).routes, ())


class OnePieceOnePromise(unittest.TestCase):
    def test_a_single_piece_is_promised_to_one_member_only(self):
        """Two tanks wear the same antique and one upgrade exists. Members
        are considered in name order, so the piece is promised once, to
        the first of them, and the second is not promised air."""
        rows = [
            tank("Grug"),
            tank("Zug"),
            member("Bork", ROGUE, 43, skills=ROGUE_SKILLS),
        ]
        gear = [
            old_breastplate("Grug"),
            old_breastplate("Zug"),
            symbolic_breastplate("Bork"),
        ]
        report = gr.plan(rows, gear)
        self.assertEqual(len(report.routes), 1)
        self.assertEqual(report.routes[0].wearer, "Grug")


class AHoldersOwnUpgradeStaysWithThem(unittest.TestCase):
    def test_a_piece_its_holder_would_wear_is_never_routed_away(self):
        """Zug carries the upgrade and wears the antique himself: his own
        equip pass puts it on him, so there is nothing to route - taking
        it for Grug would trade one antique for another."""
        rows = [tank("Grug"), tank("Zug")]
        gear = [
            old_breastplate("Grug"),
            old_breastplate("Zug"),
            symbolic_breastplate("Zug"),
        ]
        self.assertEqual(gr.plan(rows, gear).routes, ())


class TheGuildBankAndTheGuildLine(unittest.TestCase):
    def test_a_guild_bank_piece_is_routed_under_the_bank_label(self):
        bank = [symbolic_breastplate(gr.BANK_HOLDER)]
        report = gr.plan([tank("Grug")], [old_breastplate("Grug")], bank_rows=bank)
        self.assertEqual(len(report.routes), 1)
        self.assertEqual(report.routes[0].holder, "guild bank")
        self.assertEqual(report.routes[0].wearer, "Grug")

    def test_another_guilds_bags_are_not_a_source(self):
        rows = [
            tank("Grug", guild="Cave"),
            member("Bork", ROGUE, 43, skills=ROGUE_SKILLS, guild="Bonkers"),
        ]
        gear = [
            old_breastplate("Grug"),
            symbolic_breastplate("Bork", guild="Bonkers"),
        ]
        self.assertEqual(gr.plan(rows, gear).routes, ())

    def test_a_bank_piece_belongs_to_its_own_guild_only(self):
        bank = [symbolic_breastplate(gr.BANK_HOLDER, guild="Bonkers")]
        report = gr.plan(
            [tank("Grug", guild="Cave")],
            [old_breastplate("Grug")],
            bank_rows=bank,
        )
        self.assertEqual(report.routes, ())


class CoverageIsSaidOutLoud(unittest.TestCase):
    def test_a_member_the_scorer_cannot_judge_is_named_not_skipped(self):
        rows = [tank("Grug"), member("Nameless", 0, 40)]
        gear = [old_breastplate("Grug"), symbolic_breastplate("Nameless")]
        report = gr.plan(rows, gear)
        self.assertEqual(report.members, 2)
        self.assertEqual(report.judged, 1)
        self.assertEqual(report.unjudged, ("Nameless",))
        # And their bags are not a source: the pass cannot prove the
        # piece is spare to somebody it cannot score.
        self.assertEqual(report.routes, ())

    def test_a_holder_with_no_member_row_is_named_and_left_alone(self):
        gear = [old_breastplate("Grug"), symbolic_breastplate("Ghost")]
        report = gr.plan([tank("Grug")], gear)
        self.assertEqual(report.unjudged, ("Ghost",))
        self.assertEqual(report.routes, ())


class TheReportReads(unittest.TestCase):
    def _report(self):
        rows = [tank("Grug"), member("Bork", ROGUE, 43, skills=ROGUE_SKILLS)]
        gear = [old_breastplate("Grug"), symbolic_breastplate("Bork")]
        return gr.plan(rows, gear)

    def test_build_carries_the_audit_fields(self):
        payload = gr.build(self._report())
        self.assertEqual(payload["judged"], 2)
        self.assertEqual(payload["candidates"], 1)
        self.assertEqual(payload["min_gain"], 0.1)
        (route,) = payload["routes"]
        self.assertEqual(route["wearer"], "Grug")
        self.assertEqual(route["holder"], "Bork")
        self.assertEqual(route["item"], "Symbolic Breastplate")
        self.assertEqual(route["worn"], "Old Breastplate")
        self.assertEqual(route["slot"], "chest")
        self.assertGreater(route["gain"], 0.1)

    def test_a_line_names_giver_piece_taker_and_what_it_replaces(self):
        (line,) = gr.lines(self._report())
        self.assertIn("Bork", line)
        self.assertIn("Symbolic Breastplate", line)
        self.assertIn("Grug", line)
        self.assertIn("Old Breastplate", line)

    def test_the_headline_counts_the_routes(self):
        self.assertIn("1 upgrade", gr.headline(self._report()))

    def test_an_empty_pass_says_which_kind_of_empty(self):
        report = gr.plan([tank("Grug")], [old_breastplate("Grug")])
        self.assertIn("no bind-on-equip gear", gr.headline(report))
        nobody = gr.plan([member("Nameless", 0, 40)], [])
        self.assertIn("nobody in either guild could be scored", gr.headline(nobody))


class PairsAndHandsAndEmptySlots(unittest.TestCase):
    def test_a_routed_ring_displaces_the_weaker_of_the_pair(self):
        rows = [tank("Grug"), member("Bork", ROGUE, 43, skills=ROGUE_SKILLS)]
        gear = [
            piece(
                "Band A", 11, 4, 0, level=30, stats=((STA, 4),), slot=10, holder="Grug"
            ),
            piece(
                "Band B", 11, 4, 0, level=30, stats=((STA, 5),), slot=11, holder="Grug"
            ),
            # Bork's own pair is full of agility rings a rogue scores over
            # the tank's ring, so the ring is spare in his bags.
            piece(
                "Band of the Monkey",
                11,
                4,
                0,
                level=40,
                stats=((AGI, 12),),
                slot=10,
                holder="Bork",
            ),
            piece(
                "Band of the Monkey",
                11,
                4,
                0,
                level=40,
                stats=((AGI, 12),),
                slot=11,
                holder="Bork",
            ),
            piece(
                "Engraved Truesilver Ring",
                11,
                4,
                0,
                level=40,
                req=35,
                stats=((STA, 12), (STR, 6)),
                holder="Bork",
            ),
        ]
        (route,) = gr.plan(rows, gear).routes
        self.assertEqual(route.slot, "finger")
        self.assertEqual(route.worn, "Band A")

    def test_an_empty_slot_is_filled_and_names_no_gain(self):
        rows = [tank("Grug"), member("Bork", ROGUE, 43, skills=ROGUE_SKILLS)]
        # Bork already wears a neck his spec scores over the chain, so the
        # chain is spare in his bags and Grug's empty neck is the route.
        borks = piece(
            "Amulet of Agility",
            2,
            4,
            0,
            level=40,
            stats=((AGI, 12),),
            slot=1,
            holder="Bork",
        )
        chain = piece(
            "Kaleidoscope Chain", 2, 4, 0, level=35, stats=((STA, 6),), holder="Bork"
        )
        report = gr.plan(rows, [borks, chain])
        (route,) = report.routes
        self.assertEqual(route.slot, "neck")
        self.assertEqual(route.worn, "")
        self.assertIsNone(route.gain)
        self.assertIn("filling an empty slot", gr.lines(report)[0])

    def test_a_main_hand_routes_as_a_hand(self):
        rows = [tank("Grug"), member("Bork", ROGUE, 43, skills=ROGUE_SKILLS)]
        # Bork's own sword out-damages the carried blade for him, so the
        # blade is spare; for Grug's worn blade it is a clear upgrade.
        borks = piece(
            "Assassination Blade",
            13,
            2,
            7,
            level=40,
            req=35,
            stats=((AGI, 5),),
            slot=15,
            holder="Bork",
            dmg_min1=24,
            dmg_max1=44,
            delay=1700,
        )
        # And a second blade in his off hand: a dual-wielder's set is
        # judged whole, so the carried blade has to lose to the pair he
        # already holds before it is spare.
        borks_off = piece(
            "Assassination Blade",
            13,
            2,
            7,
            level=40,
            req=35,
            stats=((AGI, 5),),
            slot=16,
            holder="Bork",
            dmg_min1=22,
            dmg_max1=40,
            delay=1600,
        )
        worn = piece(
            "Worn Blade",
            13,
            2,
            7,
            level=20,
            req=15,
            slot=15,
            holder="Grug",
            dmg_min1=8,
            dmg_max1=14,
            delay=2000,
        )
        carried = piece(
            "Thief's Blade",
            13,
            2,
            7,
            level=22,
            req=17,
            stats=((AGI, 7),),
            holder="Bork",
            dmg_min1=18,
            dmg_max1=34,
            delay=1800,
        )
        (route,) = gr.plan(rows, [borks, borks_off, worn, carried]).routes
        self.assertEqual(route.slot, "main_hand")
        self.assertEqual(route.worn, "Worn Blade")
        self.assertGreater(route.gain, 0.1)


class TheSiteServesIt(unittest.TestCase):
    def setUp(self):
        self.src = MAP_SERVER.read_text(encoding="utf-8")

    def test_the_route_is_registered(self):
        self.assertIn('"/api/guildrouting": _guild_routing', self.src)
        self.assertIn("def _guild_routing", self.src)

    def test_the_read_carries_the_binding_facts(self):
        """A routing read without the template's bonding and the
        instance's flags cannot tell a movable copy from a bound one,
        which is the whole safety of the pass."""
        block = self.src[
            self.src.index("_ROUTING_WEARERS = (") : self.src.index(
                "def _fetch_guild_routing"
            )
        ]
        self.assertIn("it.bonding AS bonding", block)
        self.assertIn("ii.flags AS instance_flags", block)

    def test_the_read_covers_every_guild_member_not_only_the_families(self):
        block = self.src[
            self.src.index("_ROUTING_WEARERS = (") : self.src.index(
                "def _fetch_guild_routing"
            )
        ]
        self.assertIn("guild_member", block)


if __name__ == "__main__":
    unittest.main()
