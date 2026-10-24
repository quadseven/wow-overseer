"""Farming assignments (#479): connect the raid's consumable deficits to bots
that gather the missing materials and mail them to the crafters who need them.

Pure unit tests against farmassign.py. Fixtures are a small guild: an herbalist
and an alchemist on the corps, a member carrying stock, and a raid that is
short of dreamfoil and elemental earth.
"""

import unittest

import farmassign as fa
import guildcorps as gc

KALIMDOR = 1
EASTERN_KINGDOMS = 0
HERBALISM = gc.HERBALISM
MINING = gc.MINING
ALCHEMY = gc.ALCHEMY
DREAMFOIL = 13463
ELEMENTAL_EARTH = 7067


def member(name, guild="Cave", **over):
    base = dict(
        name=name,
        guild=guild,
        class_id=8,
        level=60,
        online=True,
        map_id=KALIMDOR,
        maintenance=True,
    )
    base.update(over)
    return gc.Member(**base)


def held(guid, entry, count):
    return gc.Held(guid, entry, count)


def post(name, role, skill, value, cap):
    return gc.Post(name, role, skill, value, cap)


def deficit(entry, name, short):
    return fa.Deficit(entry, name, short)


def guild(members=None, posts=None):
    return (tuple(members or ()), tuple(posts or ()))


HERBALIST = member("Hebus", skills={HERBALISM: (200, 300)}, map_id=KALIMDOR)
HERBALIST_POST = post("Hebus", "herbalist", HERBALISM, 200, 300)

ALCHEMIST = member("Oden", skills={ALCHEMY: (300, 375)}, map_id=KALIMDOR)
ALCHEMIST_POST = post("Oden", "alchemist", ALCHEMY, 300, 375)

HOLDER = member("Behodiir", carried=(held(1, DREAMFOIL, 9),), map_id=KALIMDOR)

MINER = member("Grug", skills={MINING: (200, 300)}, map_id=EASTERN_KINGDOMS)
MINER_POST = post("Grug", "miner", MINING, 200, 300)


class TheAssignments(unittest.TestCase):
    def test_a_short_herb_is_assigned_to_a_free_herbalist(self):
        members, posts = guild(
            [HERBALIST, ALCHEMIST, HOLDER], [HERBALIST_POST, ALCHEMIST_POST]
        )
        plan = fa.assign([deficit(DREAMFOIL, "Dreamfoil", 5)], members, posts)
        self.assertEqual(len(plan.tasks), 1)
        task = plan.tasks[0]
        self.assertEqual(task.bot, "Hebus")
        self.assertEqual(task.material, DREAMFOIL)
        self.assertEqual(task.name, "Dreamfoil")
        self.assertEqual(task.zone, "Eastern Plaguelands")
        self.assertEqual(task.map_id, EASTERN_KINGDOMS)
        self.assertEqual(task.duration, fa.HERB_DURATION)

    def test_the_assignment_is_loggable_as_farmassign(self):
        members, posts = guild([HERBALIST], [HERBALIST_POST])
        plan = fa.assign([deficit(DREAMFOIL, "Dreamfoil", 5)], members, posts)
        task = plan.tasks[0]
        self.assertEqual(
            "farmassign: assigned %s to %s" % (task.bot, task.name),
            "farmassign: assigned Hebus to Dreamfoil",
        )

    def test_a_short_ore_is_assigned_to_a_free_miner(self):
        members, posts = guild([MINER, ALCHEMIST], [MINER_POST, ALCHEMIST_POST])
        plan = fa.assign(
            [deficit(ELEMENTAL_EARTH, "Elemental Earth", 3)], members, posts
        )
        self.assertEqual(len(plan.tasks), 1)
        task = plan.tasks[0]
        self.assertEqual(task.bot, "Grug")
        self.assertEqual(task.material, ELEMENTAL_EARTH)
        self.assertEqual(task.zone, "Arathi Highlands")
        self.assertEqual(task.map_id, EASTERN_KINGDOMS)
        self.assertEqual(task.duration, fa.ORE_DURATION)

    def test_nothing_is_assigned_for_a_material_that_is_not_short(self):
        members, posts = guild([HERBALIST], [HERBALIST_POST])
        plan = fa.assign([deficit(DREAMFOIL, "Dreamfoil", 0)], members, posts)
        self.assertEqual(plan.tasks, ())
        self.assertEqual(plan.notes, ())

    def test_an_untracked_material_is_named_in_the_notes(self):
        members, posts = guild([HERBALIST], [HERBALIST_POST])
        plan = fa.assign([deficit(99999, "No Such Herb", 4)], members, posts)
        self.assertEqual(plan.tasks, ())
        self.assertIn("No Such Herb", plan.notes[0])

    def test_no_free_gatherer_means_no_task_and_a_note(self):
        members, posts = guild([HERBALIST], [HERBALIST_POST])
        plan = fa.assign(
            [deficit(DREAMFOIL, "Dreamfoil", 5)], members, posts, busy={"Hebus"}
        )
        self.assertEqual(plan.tasks, ())
        self.assertIn("no herbalism is free to farm Dreamfoil", plan.notes[0])

    def test_collected_material_is_routed_to_the_crafter_by_mail(self):
        members, posts = guild(
            [HERBALIST, ALCHEMIST, HOLDER], [HERBALIST_POST, ALCHEMIST_POST]
        )
        plan = fa.assign([deficit(DREAMFOIL, "Dreamfoil", 5)], members, posts)
        posts_steps = [s for s in plan.steps if s.action == "post"]
        self.assertEqual(len(posts_steps), 1)
        step = posts_steps[0]
        self.assertEqual(step.holder, "Behodiir")
        self.assertEqual(step.rows[0].target_arg, "Oden")
        self.assertTrue(
            step.rows[0].command.startswith("send item:1 subject:Dreamfoil")
        )
        self.assertTrue(step.walk.command.startswith("walk-to-mailbox"))

    def test_the_gatherer_is_not_also_the_holder(self):
        # Hebus both farms and carries dreamfoil: the stock must go to the
        # alchemist from someone else, so no holder is found and no mail step.
        hebus = member(
            "Hebus", skills={HERBALISM: (200, 300)}, carried=(held(1, DREAMFOIL, 9),)
        )
        members, posts = guild([hebus, ALCHEMIST], [HERBALIST_POST, ALCHEMIST_POST])
        plan = fa.assign([deficit(DREAMFOIL, "Dreamfoil", 5)], members, posts)
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.steps, ())

    def test_a_recent_post_cools_down_the_mail_step(self):
        members, posts = guild(
            [HERBALIST, ALCHEMIST, HOLDER], [HERBALIST_POST, ALCHEMIST_POST]
        )
        recent = {("Behodiir", "post", DREAMFOIL): 1}
        plan = fa.assign(
            [deficit(DREAMFOIL, "Dreamfoil", 5)], members, posts, recent=recent
        )
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.steps, ())

    def test_multiple_deficits_are_assigned_in_entry_order(self):
        members, posts = guild(
            [HERBALIST, MINER, ALCHEMIST], [HERBALIST_POST, MINER_POST, ALCHEMIST_POST]
        )
        plan = fa.assign(
            [
                deficit(ELEMENTAL_EARTH, "Elemental Earth", 3),
                deficit(DREAMFOIL, "Dreamfoil", 5),
            ],
            members,
            posts,
        )
        self.assertEqual([t.material for t in plan.tasks], [ELEMENTAL_EARTH, DREAMFOIL])
        self.assertEqual([t.bot for t in plan.tasks], ["Grug", "Hebus"])


if __name__ == "__main__":
    unittest.main()
