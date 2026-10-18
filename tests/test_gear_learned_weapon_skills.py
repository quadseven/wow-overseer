"""Family gear judges a weapon by the skill the core checks, not the class (#393).

The dev realm, 2026-09-28: Og, a level 35 mage, wore no main hand and carried
Silithid Ripper, a one-hand sword of item level 36, with no Swords skill
(character_skills 43 absent). gear.wieldable_weapon decided by class alone, a
mage "can" wield a one-hand sword, so the sword was planned as Og's and the
equip pass asked three times; the core refuses to equip a weapon whose skill
is not learned. bridge._fetch_gearup_facts already read the real skills; the
family gear pass and the tidy pass did not. Pinned here on that family.
"""

import ast
import types
import unittest

from test_family_economy_parity import BRIDGE, _load  # noqa: F401 - sets up the pymysql stub

import gear  # noqa: E402
import tidy  # noqa: E402

WARRIOR, PRIEST, MAGE = 1, 5, 8
SWORD, STAFF, DAGGER, WAND, MACE = 7, 10, 15, 19, 4
INVTYPE_WEAPON, INVTYPE_CHEST = 13, 5
MAIN_HAND_SLOT = 15

# What each member has learned, as item_template.subclass values.
OG_SKILLS = (STAFF, DAGGER, WAND)  # no Swords
GRUG_SKILLS = (SWORD, MACE, STAFF, DAGGER)
UGGA_SKILLS = (MACE, STAFF, DAGGER, WAND)


def ripper(holder="Og", required=31, item_level=36):
    return gear.Holding(
        holder=holder,
        guid=7001,
        entry=7001,
        name="Silithid Ripper",
        quality=2,
        item_level=item_level,
        required_level=required,
        allowable_class=-1,
        inventory_type=INVTYPE_WEAPON,
        item_class=gear.ITEM_CLASS_WEAPON,
        item_subclass=SWORD,
    )


def member(name, class_id, level, main_hand=0, skills=None):
    equipped = {"main_hand": main_hand} if main_hand else {}
    return gear.CharacterState(
        name=name,
        class_id=class_id,
        level=level,
        equipped=equipped,
        weapon_skills=None if skills is None else frozenset(skills),
    )


class TheSkillDecidesOnceItIsRead(unittest.TestCase):
    def test_a_mage_without_swords_cannot_wield_the_ripper(self):
        og = member("Og", MAGE, 35, skills=OG_SKILLS)
        self.assertFalse(gear.wieldable_weapon(ripper(), og))
        self.assertTrue(gear.class_wields(ripper(), og))
        ok, why = gear.would_wear(ripper(), og)
        self.assertFalse(ok)
        self.assertIn("has not learned that weapon skill", why)

    def test_unread_skills_keep_the_class_judgement(self):
        og = member("Og", MAGE, 35)
        self.assertTrue(gear.wieldable_weapon(ripper(), og))
        self.assertTrue(gear.would_wear(ripper(), og)[0])

    def test_a_learned_skill_wields(self):
        grug = member("Grug", WARRIOR, 38, skills=GRUG_SKILLS)
        self.assertTrue(gear.wieldable_weapon(ripper(holder="Grug"), grug))

    def test_armour_is_not_a_weapon_skill_question(self):
        robe = gear.Holding(
            holder="Og", guid=1, entry=1, name="Robe", quality=2, item_level=30,
            required_level=25, allowable_class=-1, inventory_type=INVTYPE_CHEST,
            item_class=gear.ITEM_CLASS_ARMOR, item_subclass=1,
        )  # fmt: skip
        og = member("Og", MAGE, 35, skills=())
        self.assertTrue(gear.wieldable_weapon(robe, og))


class ThePlanHandsTheSwordToWhoeverHasSwords(unittest.TestCase):
    def test_the_warrior_with_swords_gets_the_ripper_not_the_mage(self):
        og = member("Og", MAGE, 35, skills=OG_SKILLS)
        grug = member("Grug", WARRIOR, 38, main_hand=20, skills=GRUG_SKILLS)
        plan = gear.plan([ripper()], [og, grug])
        self.assertEqual(["Grug"], [g.taker for g in plan.grants])
        self.assertEqual("Grug", gear.claimant(ripper(), [og, grug]))

    def test_no_sibling_with_the_skill_keeps_it_with_the_holder_unworn(self):
        # Kept for the weapon-master walk (#399), never asked to be put on.
        og = member("Og", MAGE, 35, skills=OG_SKILLS)
        ugga = member("Ugga", PRIEST, 35, skills=UGGA_SKILLS)
        family = [og, ugga]
        self.assertEqual("Og", gear.claimant(ripper(), family))
        self.assertEqual((), gear.equips([ripper()], family))
        self.assertEqual((), gear.plan([ripper()], family).grants)

    def test_a_trained_holder_still_puts_it_on(self):
        og = member("Og", MAGE, 35, skills=OG_SKILLS + (SWORD,))
        equips = gear.equips([ripper()], [og])
        self.assertEqual(["Og"], [e.holder for e in equips])

    def test_a_weapon_the_class_can_never_learn_is_nobodys(self):
        mace = ripper()
        mace = gear.Holding(**{**mace.__dict__, "item_subclass": MACE})
        og = member("Og", MAGE, 35, skills=OG_SKILLS)
        self.assertEqual(gear.NOBODY, gear.claimant(mace, [og]))


class TheRowsCarryTheSkills(unittest.TestCase):
    def rows(self, **extra):
        return [
            dict(name="Og", class_id=MAGE, level=35, equipment_slot=4,
                 inventory_type=INVTYPE_CHEST, item_level=16, **extra),
            dict(name="Og", class_id=MAGE, level=35, equipment_slot=None,
                 inventory_type=None, item_level=None, **extra),
        ]  # fmt: skip

    def test_characters_from_rows_reads_weapon_skills(self):
        (og,) = gear.characters_from_rows(self.rows(weapon_skills=OG_SKILLS), ["Og"])
        self.assertEqual(frozenset(OG_SKILLS), og.weapon_skills)

    def test_a_row_without_the_key_leaves_skills_unread(self):
        (og,) = gear.characters_from_rows(self.rows(), ["Og"])
        self.assertIsNone(og.weapon_skills)

    def test_tidy_members_read_weapon_skills(self):
        members = tidy.members_from_rows(self.rows(weapon_skills=OG_SKILLS))
        self.assertEqual(frozenset(OG_SKILLS), members["Og"].weapon_skills)
        self.assertIsNone(tidy.members_from_rows(self.rows())["Og"].weapon_skills)


def tidy_row(required):
    return {
        "holder": "Ugga", "item_guid": 7002, "entry": 7002,
        "name": "Future Sword", "quality": 2, "item_level": required + 5,
        "required_level": required, "allowable_class": -1,
        "inventory_type": INVTYPE_WEAPON, "item_class": gear.ITEM_CLASS_WEAPON,
        "item_subclass": SWORD, "instance_flags": 0,
    }  # fmt: skip


class TidyPrefersAMemberWhoHasTheSkill(unittest.TestCase):
    def family(self, og_skills=OG_SKILLS):
        return {
            "Og": tidy.Member("Og", MAGE, 39, frozenset(og_skills)),
            "Grug": tidy.Member("Grug", WARRIOR, 38, frozenset(GRUG_SKILLS)),
            "Ugga": tidy.Member("Ugga", PRIEST, 35, frozenset(UGGA_SKILLS)),
        }

    def test_the_warrior_with_swords_beats_a_nearer_mage_without(self):
        owner, why = tidy.future_owner(tidy_row(40), self.family())
        self.assertEqual("Grug", owner)
        self.assertNotIn("weapon master", why)

    def test_a_mage_who_has_swords_is_the_nearer_home(self):
        owner, _ = tidy.future_owner(tidy_row(40), self.family(OG_SKILLS + (SWORD,)))
        self.assertEqual("Og", owner)

    def test_with_nobody_trained_the_untrained_member_is_still_a_home(self):
        family = self.family()
        del family["Grug"]
        owner, why = tidy.future_owner(tidy_row(40), family)
        self.assertEqual("Og", owner)
        self.assertIn("weapon master", why)


class _Cursor:
    def __init__(self, results, fail_skills=None):
        self.results = list(results)
        self.fail_skills = fail_skills
        self.sql = []

    def execute(self, sql, args=None):
        self.sql.append(sql)
        if "character_skills" in sql and self.fail_skills is not None:
            raise self.fail_skills

    def fetchall(self):
        return self.results.pop(0)


def _constant(name):
    for node in ast.parse(BRIDGE).body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise KeyError(name)


class _MySQLError(Exception):
    pass


def _bridge(cur):
    namespace = {
        "_connect": lambda: _ConnCtx(cur),
        "pymysql": types.SimpleNamespace(
            err=types.SimpleNamespace(MySQLError=_MySQLError)
        ),
        "log": types.SimpleNamespace(warning=lambda *a, **k: None),
        "_WEAPON_SKILL_SUBCLASS": _constant("_WEAPON_SKILL_SUBCLASS"),
        "_FAMILY_EQUIPPED_SQL": _constant("_FAMILY_EQUIPPED_SQL"),
        "_FAMILY_EQUIPPED_ROLES_SQL": _constant("_FAMILY_EQUIPPED_ROLES_SQL"),
    }
    return _load(
        ["_read_weapon_skills", "_attach_weapon_skills", "_fetch_family_equipped"],
        namespace,
    )


class _ConnCtx:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _CurCtx(self.cur)


class _CurCtx:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return self.cur

    def __exit__(self, *exc):
        return False


class TheBridgeReadsTheSkillsWithTheWornRows(unittest.TestCase):
    WORN = [{"name": "Og", "class_id": MAGE, "level": 35}]

    def test_each_worn_row_carries_its_members_weapon_subclasses(self):
        skills = [{"name": "Og", "skill": 136}, {"name": "Og", "skill": 173},
                  {"name": "Og", "skill": 228}, {"name": "Og", "skill": 162}]  # fmt: skip
        cur = _Cursor([self.WORN, skills])
        rows = _bridge(cur)["_fetch_family_equipped"](["Og"])
        self.assertEqual((STAFF, DAGGER, WAND), rows[0]["weapon_skills"])
        (og,) = gear.characters_from_rows(rows, ["Og"])
        self.assertFalse(gear.wieldable_weapon(ripper(), og))

    def test_a_world_without_character_skills_leaves_them_unread(self):
        cur = _Cursor([self.WORN], fail_skills=_MySQLError(1146, "no table"))
        rows = _bridge(cur)["_fetch_family_equipped"](["Og"])
        self.assertNotIn("weapon_skills", rows[0])
        (og,) = gear.characters_from_rows(rows, ["Og"])
        self.assertIsNone(og.weapon_skills)


if __name__ == "__main__":
    unittest.main()
