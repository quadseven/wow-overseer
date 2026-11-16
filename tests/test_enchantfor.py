"""The enchant-for planner: who an enchanter enchants, with what, on which piece.

The module answers `kind='trade'` rows `enchant-for target:<guid> slot:<n>
spell:<id>`; `enchantfor.plan` decides what to ask. These tests pin the rule
on the real frozen recipe file (data/enchants.json) and small hand-built rows.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import enchantfor  # noqa: E402

GREATER_STRENGTH = 13939  # Enchant Bracer - Greater Strength, +7 Strength, enchant 927
STRENGTH_ENCHANT = 927
BRACER = 9  # inventory type
WARRIOR, PRIEST, SHAMAN = 1, 5, 7
STR, STA = 4, 7

# 2 Dream Dust, 1 Greater Nether Essence, and a Runed Truesilver Rod.
PAID = {11176: 2, 11175: 1, 11145: 1}


def member(name, guid, *, guild="Cave", online=True, map_id=0, x=0.0, y=0.0, z=0.0):
    return enchantfor.Member(name, guid, guild, online, map_id, x, y, z)


def enchanter(name="Aeda", *, guild="Cave", known=(GREATER_STRENGTH,), bags=None):
    return enchantfor.Enchanter(
        name, guild, frozenset(known), dict(PAID if bags is None else bags)
    )


def wearer(name, class_id, tree, level=60):
    return dict(
        name=name,
        class_id=class_id,
        level=level,
        race=1,
        talent_spells="",
        target_tree=tree,
        skills="",
    )


def bracer(holder, *, enchantments="", entry=5000, guid=1, stats=((STA, 10),)):
    row = dict(
        holder=holder,
        equipment_slot=8,
        item_guid=guid,
        entry=entry,
        name="Bracer of %s" % holder,
        quality=3,
        item_level=60,
        required_level=55,
        item_class=4,
        item_subclass=3,
        inventory_type=BRACER,
        allowable_class=-1,
        allowable_race=-1,
        required_skill=0,
        required_skill_rank=0,
        required_spell=0,
        required_reputation=0,
        max_count=0,
        item_flags=0,
        armor=100,
        block=0,
        dmg_min1=0,
        dmg_max1=0,
        delay=0,
        random_property_id=0,
        enchantments=enchantments,
    )
    for n, (kind, amount) in enumerate(stats, start=1):
        row["stat_type%d" % n] = kind
        row["stat_value%d" % n] = amount
    return row


class Book:
    """The one fact the planner reads of the item book: what an enchant does."""

    enchants = {927: ["+7 Strength", [[5, 7, STR]]], 66: ["+1 Strength", [[5, 1, STR]]]}


def plan(enchanters, members, wearers, worn, **kw):
    return enchantfor.plan(
        enchanters, {m.name: m for m in members}, wearers, worn, book=Book(), **kw
    )


class CatalogueTest(unittest.TestCase):
    def test_the_frozen_file_names_greater_strength_as_the_realm_measured_it(self):
        recipe = next(r for r in enchantfor.catalogue() if r.spell == GREATER_STRENGTH)
        self.assertEqual(STRENGTH_ENCHANT, recipe.enchant)
        self.assertEqual(((11176, 2), (11175, 1)), recipe.reagents)
        self.assertEqual((9,), recipe.tools)
        self.assertEqual(((5, 7, STR),), recipe.effects)

    def test_every_recipe_in_the_file_enchants_an_item(self):
        with open(enchantfor.CATALOGUE_PATH, encoding="utf-8") as handle:
            raw = json.load(handle)["recipes"]
        self.assertGreater(len(raw), 100)
        for r in enchantfor.catalogue():
            self.assertIn(r.item_class, (2, 4))
            self.assertGreater(r.enchant, 0)

    def test_a_bracer_fits_and_a_ring_does_not(self):
        recipe = next(r for r in enchantfor.catalogue() if r.spell == GREATER_STRENGTH)
        self.assertTrue(enchantfor.fits(recipe, bracer("X")))
        ring = dict(bracer("X"), inventory_type=11, item_subclass=0)
        self.assertFalse(enchantfor.fits(recipe, ring))


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.aeda = member("Aeda", 1)
        self.brom = member("Brom", 2)
        self.shaman = wearer("Brom", SHAMAN, "Enhancement")

    def test_a_bare_bracer_gets_the_enchant(self):
        jobs = plan(
            [enchanter()], [self.aeda, self.brom], [self.shaman], [bracer("Brom")]
        )
        self.assertEqual(1, len(jobs))
        job = jobs[0]
        self.assertEqual(
            ("Aeda", "Brom", 2, 8, GREATER_STRENGTH),
            (job.enchanter, job.member, job.member_guid, job.slot, job.spell),
        )
        self.assertEqual(
            "enchant-for target:2 slot:8 spell:13939", enchantfor.command(job)
        )
        self.assertGreater(job.gain, 0)

    def test_the_log_line_names_everything(self):
        jobs = plan(
            [enchanter()], [self.aeda, self.brom], [self.shaman], [bracer("Brom")]
        )
        line = enchantfor.lines(jobs)[0]
        for word in ("Aeda", "Brom", "Greater Strength", "13939", "slot 8", "11176x2"):
            self.assertIn(word, line)

    def test_a_recipe_the_enchanter_does_not_hold_is_never_asked_for(self):
        jobs = plan(
            [enchanter(known=())],
            [self.aeda, self.brom],
            [self.shaman],
            [bracer("Brom")],
        )
        self.assertEqual((), jobs)

    def test_short_reagents_are_never_asked_for(self):
        bags = {11176: 1, 11175: 1, 11145: 1}
        jobs = plan(
            [enchanter(bags=bags)],
            [self.aeda, self.brom],
            [self.shaman],
            [bracer("Brom")],
        )
        self.assertEqual((), jobs)

    def test_a_missing_rod_is_never_asked_for(self):
        bags = {11176: 2, 11175: 1}
        jobs = plan(
            [enchanter(bags=bags)],
            [self.aeda, self.brom],
            [self.shaman],
            [bracer("Brom")],
        )
        self.assertEqual((), jobs)

    def test_a_higher_rod_answers_a_lower_rung(self):
        bags = {11176: 2, 11175: 1, 16207: 1}
        jobs = plan(
            [enchanter(bags=bags)],
            [self.aeda, self.brom],
            [self.shaman],
            [bracer("Brom")],
        )
        self.assertEqual(1, len(jobs))

    def test_a_member_of_another_guild_is_left_alone(self):
        far = member("Brom", 2, guild="Bonkers")
        self.assertEqual(
            (), plan([enchanter()], [self.aeda, far], [self.shaman], [bracer("Brom")])
        )

    def test_a_member_out_of_reach_is_left_alone(self):
        far = member("Brom", 2, x=40.0)
        self.assertEqual(
            (), plan([enchanter()], [self.aeda, far], [self.shaman], [bracer("Brom")])
        )

    def test_a_member_on_another_map_is_left_alone(self):
        far = member("Brom", 2, map_id=1)
        self.assertEqual(
            (), plan([enchanter()], [self.aeda, far], [self.shaman], [bracer("Brom")])
        )

    def test_an_offline_member_is_left_alone(self):
        gone = member("Brom", 2, online=False)
        self.assertEqual(
            (), plan([enchanter()], [self.aeda, gone], [self.shaman], [bracer("Brom")])
        )

    def test_an_offline_enchanter_asks_nothing(self):
        gone = member("Aeda", 1, online=False)
        self.assertEqual(
            (), plan([enchanter()], [gone, self.brom], [self.shaman], [bracer("Brom")])
        )

    def test_an_enchanter_never_enchants_itself(self):
        mine = wearer("Aeda", SHAMAN, "Enhancement")
        self.assertEqual((), plan([enchanter()], [self.aeda], [mine], [bracer("Aeda")]))

    def test_the_same_enchant_is_not_asked_twice(self):
        row = bracer("Brom", enchantments="927 0 0")
        self.assertEqual(
            (), plan([enchanter()], [self.aeda, self.brom], [self.shaman], [row])
        )

    def test_an_enchant_enchanting_did_not_make_is_never_written_over(self):
        row = bracer("Brom", enchantments="1843 0 0")
        self.assertEqual(
            (), plan([enchanter()], [self.aeda, self.brom], [self.shaman], [row])
        )

    def test_a_weaker_enchanting_enchant_is_written_over(self):
        # Enchant 66 is not in the recipe file, so it is a foreign enchant and
        # stays; the recipe file's own minor strength rung is the weaker one.
        recipes = enchantfor.catalogue()
        weaker = next(
            r for r in recipes if r.effects == ((5, 5, STR),) and r.invtype_mask == 512
        )
        row = bracer("Brom", enchantments="%d 0 0" % weaker.enchant)

        class WeakBook:
            enchants = {weaker.enchant: ["+5 Strength", [[5, 5, STR]]]}

        jobs = enchantfor.plan(
            [enchanter()],
            {"Aeda": self.aeda, "Brom": self.brom},
            [self.shaman],
            [row],
            book=WeakBook(),
        )
        self.assertEqual(1, len(jobs))
        self.assertEqual(STRENGTH_ENCHANT, jobs[0].enchant)

    def test_an_enchant_that_helps_the_member_not_at_all_is_never_asked_for(self):
        healer = wearer("Brom", PRIEST, "Holy")
        self.assertEqual(
            (), plan([enchanter()], [self.aeda, self.brom], [healer], [bracer("Brom")])
        )

    def test_a_carried_piece_is_not_enchanted(self):
        row = bracer("Brom")
        row["equipment_slot"] = None
        self.assertEqual(
            (), plan([enchanter()], [self.aeda, self.brom], [self.shaman], [row])
        )

    def test_without_the_book_a_worn_enchant_cannot_be_judged(self):
        row = bracer("Brom", enchantments="927 0 0")
        jobs = enchantfor.plan(
            [enchanter()],
            {"Aeda": self.aeda, "Brom": self.brom},
            [self.shaman],
            [row],
            book=None,
        )
        self.assertEqual((), jobs)


class PriorityTest(unittest.TestCase):
    """Raid seats, then tanks and healers, then the rest; one cast per pair."""

    def setUp(self):
        self.members = [
            member("Aeda", 1),
            member("Seat", 2),
            member("Healer", 3),
            member("Rest", 4),
        ]
        self.wearers = [
            wearer("Seat", SHAMAN, "Enhancement"),
            wearer("Healer", WARRIOR, "Protection"),
            wearer("Rest", SHAMAN, "Enhancement"),
        ]
        self.worn = [
            bracer(n, guid=i) for i, n in enumerate(("Seat", "Healer", "Rest"), 1)
        ]

    def test_a_raid_seat_goes_first(self):
        jobs = plan(
            [enchanter()],
            self.members,
            self.wearers,
            self.worn,
            seat_names=frozenset({"Seat"}),
        )
        self.assertEqual(["Seat"], [j.member for j in jobs])
        self.assertEqual(enchantfor.PRIORITY_SEAT, jobs[0].priority)

    def test_a_tank_goes_before_the_rest_when_no_seat_wants_it(self):
        resto = [w for w in self.wearers if w["name"] != "Seat"]
        worn = [r for r in self.worn if r["holder"] != "Seat"]
        jobs = plan([enchanter()], self.members, resto, worn)
        self.assertEqual(["Healer"], [j.member for j in jobs])
        self.assertEqual(enchantfor.PRIORITY_ROLE, jobs[0].priority)

    def test_two_enchanters_serve_two_members_and_never_the_same_one_twice(self):
        e2 = enchanter("Bela")
        members = self.members + [member("Bela", 5)]
        jobs = plan(
            [enchanter(), e2],
            members,
            self.wearers,
            self.worn,
            seat_names=frozenset({"Seat"}),
        )
        self.assertEqual(2, len(jobs))
        self.assertEqual(2, len({j.member for j in jobs}))
        self.assertEqual(2, len({j.enchanter for j in jobs}))
        self.assertEqual("Seat", jobs[0].member)

    def test_the_bigger_gain_goes_first_inside_a_rank(self):
        big = wearer("Rest", SHAMAN, "Enhancement")
        small = wearer("Other", SHAMAN, "Enhancement")
        members = [member("Aeda", 1), member("Rest", 4), member("Other", 6)]
        rest = bracer("Rest", guid=1)
        other = bracer("Other", guid=2)
        # A cloak-less, strength-less comparison cannot differ for one spec, so
        # the bigger gain is the piece already holding the weaker enchant.
        other["enchantments"] = "66 0 0"
        jobs = plan([enchanter()], members, [big, small], [rest, other])
        self.assertEqual(["Rest"], [j.member for j in jobs])


FIRE_CLOAK = 13657  # Enchant Cloak - Fire Resistance, +7 fire resistance, enchant 2463
FIRE_ENCHANT = 2463
GREATER_DEFENSE = 13746  # Enchant Cloak - Greater Defense, +50 armor
BACK, CLOAK = 14, 16  # equipment slot, inventory type

# 1 Lesser Mystic Essence and 1 Elemental Fire (Fire Resistance); 3 Vision Dust
# and a Runed Truesilver Rod (Greater Defense).
CLOAK_BAGS = {11134: 1, 7068: 1, 11137: 3, 11145: 1}


def cloak(holder, *, fire=0, enchantments="", guid=3):
    row = bracer(holder, enchantments=enchantments, guid=guid, stats=((STA, 6),))
    row.update(
        equipment_slot=BACK,
        inventory_type=CLOAK,
        item_subclass=1,
        armor=40,
        name="Cloak of %s" % holder,
        fire_res=fire,
    )
    return row


class FireResistanceCloakTest(unittest.TestCase):
    """#481: the +7 Fire Resistance cloak, for the seats Molten Core asks fire
    resistance of, end to end through the planner to the row's command."""

    def setUp(self):
        self.aeda = member("Aeda", 1)
        self.brom = member("Brom", 2)
        self.tank = wearer("Brom", WARRIOR, "Protection")
        self.known = (FIRE_CLOAK, GREATER_DEFENSE)

    def run_plan(self, worn, targets, known=None, **kw):
        return enchantfor.plan(
            [enchanter(known=known or self.known, bags=CLOAK_BAGS)],
            {"Aeda": self.aeda, "Brom": self.brom},
            [self.tank],
            [worn],
            book=kw.pop("book", Book()),
            fire_targets=targets,
            **kw,
        )

    def test_the_main_tank_gets_the_fire_cloak_over_a_better_scoring_armor_enchant(
        self,
    ):
        (job,) = self.run_plan(cloak("Brom"), {"Brom": 200})
        self.assertEqual(FIRE_CLOAK, job.spell)
        self.assertEqual(FIRE_ENCHANT, job.enchant)
        self.assertEqual(BACK, job.slot)
        self.assertEqual(
            "enchant-for target:2 slot:14 spell:13657", enchantfor.command(job)
        )

    def test_the_credit_is_what_the_seat_is_short_of_its_target(self):
        (job,) = self.run_plan(
            cloak("Brom", fire=197), {"Brom": 200}, known=(FIRE_CLOAK,)
        )
        self.assertAlmostEqual(3 * enchantfor.MC_FIRE_WEIGHT, job.gain)

    def test_a_seat_at_its_target_is_not_given_more_fire_resistance(self):
        self.assertEqual(
            (),
            self.run_plan(cloak("Brom", fire=200), {"Brom": 200}, known=(FIRE_CLOAK,)),
        )

    def test_a_member_with_no_fire_target_is_not_given_it(self):
        self.assertEqual((), self.run_plan(cloak("Brom"), {}, known=(FIRE_CLOAK,)))

    def test_a_stronger_fire_enchant_replaces_a_weaker_one_when_short(self):
        class FireBook:
            enchants = {256: ["+5 Fire Resistance", [[4, 5, 2]]]}

        (job,) = self.run_plan(
            cloak("Brom", enchantments="256 0 0"),
            {"Brom": 200},
            known=(FIRE_CLOAK,),
            book=FireBook(),
        )
        self.assertEqual(FIRE_CLOAK, job.spell)
        self.assertAlmostEqual(2 * enchantfor.MC_FIRE_WEIGHT, job.gain)

    def test_the_fire_cloak_is_only_a_cloak_recipe(self):
        recipe = next(r for r in enchantfor.catalogue() if r.spell == FIRE_CLOAK)
        self.assertEqual(((4, 7, 2),), recipe.effects)
        self.assertTrue(enchantfor.fits(recipe, cloak("Brom")))
        self.assertFalse(enchantfor.fits(recipe, bracer("Brom")))

    def test_the_targets_come_from_the_molten_core_plan(self):
        targets = enchantfor.fire_targets({"Cave"})
        self.assertEqual(200, targets["Grug"])  # the main tank
        self.assertEqual(60, targets["Ugga"])  # a healer
        self.assertEqual(120, targets["Brug"])  # the second tank
        self.assertNotIn("Grog", targets)  # a damage seat is asked for none
        self.assertEqual({}, enchantfor.fire_targets({"Nowhere"}))

    def test_an_unrenamed_seat_is_keyed_under_its_current_name_too(self):
        targets = enchantfor.fire_targets({"Cave"})
        # Brug is the approved name; Aalall is the character until the rename.
        self.assertEqual(120, targets["Brug"])
        self.assertEqual(120, targets["Aalall"])

    def test_an_unrenamed_seat_still_gets_the_fire_cloak(self):
        targets = enchantfor.fire_targets({"Cave"})
        live = wearer("Aalall", WARRIOR, "Protection")
        members = {"Aeda": member("Aeda", 1), "Aalall": member("Aalall", 7)}
        (job,) = enchantfor.plan(
            [enchanter(known=(FIRE_CLOAK,), bags=CLOAK_BAGS)],
            members,
            [live],
            [cloak("Aalall")],
            book=Book(),
            fire_targets=targets,
        )
        self.assertEqual(
            "enchant-for target:7 slot:14 spell:13657", enchantfor.command(job)
        )
        self.assertGreater(job.gain, 0)


class BridgeSeamTest(unittest.TestCase):
    """The bridge writes the row, once, and only behind the module's own fact."""

    def setUp(self):
        from unittest import mock

        from test_itemplan_vendor import import_bridge

        self.mock = mock
        self.bridge = import_bridge()
        self.job = enchantfor.Job(
            "Aeda",
            "Brom",
            2,
            8,
            GREATER_STRENGTH,
            "Greater Strength",
            STRENGTH_ENCHANT,
            5000,
            "Bracer",
            12.0,
            0,
            ((11176, 2),),
        )

    def write(self, existing=0, keep=False):
        b = self.bridge
        cursor = self.mock.MagicMock()
        cursor.fetchone.return_value = {"n": existing}
        conn = self.mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cursor
        with (
            self.mock.patch.object(b._KEEP, "blocks", return_value=keep),
            self.mock.patch.object(b, "_connect", return_value=conn),
        ):
            wrote = b._carry_out_enchant_for((self.job,))
        inserts = [
            c
            for c in cursor.execute.call_args_list
            if "INSERT INTO overseer_command" in c.args[0]
        ]
        return wrote, inserts

    def test_it_writes_one_trade_row_for_the_enchanter_naming_the_member(self):
        wrote, inserts = self.write()
        self.assertEqual(1, wrote)
        self.assertEqual(
            ("Aeda", "enchant-for target:2 slot:8 spell:13939", "Brom", "enchant-for"),
            inserts[0].args[1],
        )
        self.assertIn("'trade'", inserts[0].args[0])

    def test_an_ask_already_standing_or_recent_is_not_written_again(self):
        self.assertEqual((0, []), self.write(existing=1))

    def test_a_kept_member_is_not_written(self):
        self.assertEqual((0, []), self.write(keep=True))

    def test_the_pass_is_gated_on_the_module_fact_and_the_switch(self):
        text = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
            encoding="utf-8"
        )
        start = text.index("async def _enchant_for_once")
        body = text[start : start + 1500]
        self.assertIn("enchantfor.enabled()", body)
        self.assertIn("_fetch_module_enchant_for", body)
        self.assertIn("!= enchantfor.CAPABILITY", body)
        self.assertLess(
            body.index("_fetch_module_enchant_for"),
            body.index("_fetch_enchant_for_facts"),
        )
        self.assertIn("self._enchant_for_once", text)

    def test_the_member_read_uses_the_snapshots_own_map_and_position(self):
        sql = self.bridge._ENCHANT_FOR_MEMBERS_SQL
        for column in ("s.map_id", "s.pos_x", "s.pos_y", "s.pos_z"):
            self.assertIn(column, sql)
        for stale in ("c.map ", "c.position_x", "c.position_y", "c.position_z"):
            self.assertNotIn(stale, sql)
        self.assertIn("s.updated_at", sql)

    def test_the_member_read_hands_the_snapshot_position_to_the_planner(self):
        b = self.bridge
        snapshot = {
            "guid": 2,
            "name": "Brom",
            "guild": "Cave",
            "map_id": 1,
            "x": 10.5,
            "y": -3.0,
            "z": 40.0,
        }
        cursor = self.mock.MagicMock()
        cursor.fetchall.side_effect = [[snapshot], []]
        conn = self.mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cursor
        with self.mock.patch.object(b, "_connect", return_value=conn):
            members, enchanters = b._fetch_enchant_for_facts(["Aeda"])
        self.assertEqual([], enchanters)
        brom = members["Brom"]
        self.assertEqual((1, 10.5, -3.0, 40.0), (brom.map_id, brom.x, brom.y, brom.z))
        self.assertEqual(2, brom.guid)
        near = enchantfor.Member("Aeda", 1, "Cave", True, 1, 12.0, -3.0, 40.0)
        self.assertTrue(enchantfor.together(near, brom))
        elsewhere = enchantfor.Member("Aeda", 1, "Cave", True, 0, 12.0, -3.0, 40.0)
        self.assertFalse(enchantfor.together(elsewhere, brom))

    def test_the_pass_hands_the_fire_targets_to_the_planner(self):
        text = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("fire_targets=enchantfor.fire_targets(", text)

    def test_the_fact_name_is_the_one_the_module_reports(self):
        self.assertEqual("enchant_for", enchantfor.CAPABILITY_FACT)
        self.assertEqual("trade", enchantfor.CAPABILITY)


class SwitchTest(unittest.TestCase):
    def test_on_unless_switched_off(self):
        self.assertTrue(enchantfor.enabled({}))
        self.assertTrue(enchantfor.enabled({"ENCHANT_FOR": "on"}))
        for off in ("off", "0", "false", "no"):
            self.assertFalse(enchantfor.enabled({"ENCHANT_FOR": off}))


if __name__ == "__main__":
    unittest.main()
