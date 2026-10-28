"""Farming assignments (#479): connect the raid's consumable deficits to bots
that gather the missing materials and mail them to the crafters who need them.

Pure unit tests against farmassign.py. Fixtures are a small guild: an herbalist
and an alchemist on the corps, a member carrying stock, and a raid that is
short of dreamfoil and elemental earth.
"""

import types
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


def standing_task(bot="Hebus", baseline=()):
    return fa.Task(
        bot,
        DREAMFOIL,
        "Dreamfoil",
        "Eastern Plaguelands",
        EASTERN_KINGDOMS,
        fa.HERB_DURATION,
        frozenset(baseline),
    )


class TheMailSteps(unittest.TestCase):
    """Only a stack the assigned gatherer picked up since its task was given
    is posted to the crafter; stock already in the guild never is."""

    def test_a_new_assignment_posts_nothing_from_the_guilds_stock(self):
        members, posts = guild(
            [HERBALIST, ALCHEMIST, HOLDER], [HERBALIST_POST, ALCHEMIST_POST]
        )
        plan = fa.assign([deficit(DREAMFOIL, "Dreamfoil", 5)], members, posts)
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.steps, ())

    def test_the_task_remembers_the_gatherers_own_stock(self):
        hebus = member(
            "Hebus", skills={HERBALISM: (200, 300)}, carried=(held(4, DREAMFOIL, 9),)
        )
        members, posts = guild([hebus, ALCHEMIST], [HERBALIST_POST, ALCHEMIST_POST])
        plan = fa.assign([deficit(DREAMFOIL, "Dreamfoil", 5)], members, posts)
        self.assertEqual(plan.tasks[0].baseline, frozenset({4}))
        self.assertEqual(plan.steps, ())

    def test_a_gathered_stack_is_posted_to_the_crafter(self):
        hebus = member(
            "Hebus",
            skills={HERBALISM: (200, 300)},
            carried=(held(4, DREAMFOIL, 9), held(5, DREAMFOIL, 6)),
        )
        members, posts = guild(
            [hebus, ALCHEMIST, HOLDER], [HERBALIST_POST, ALCHEMIST_POST]
        )
        plan = fa.assign(
            [deficit(DREAMFOIL, "Dreamfoil", 5)],
            members,
            posts,
            standing=[standing_task(baseline={4})],
        )
        self.assertEqual(plan.tasks, ())
        self.assertEqual(len(plan.steps), 1)
        step = plan.steps[0]
        self.assertEqual(step.holder, "Hebus")
        self.assertEqual(step.rows[0].target_arg, "Oden")
        self.assertEqual(step.rows[0].command, "send item:5 subject:Dreamfoil")
        self.assertEqual(step.rows[0].source, "farmassign:post:%d" % DREAMFOIL)
        self.assertTrue(step.walk.command.startswith("walk-to-mailbox"))

    def test_a_gatherer_with_only_its_old_stock_posts_nothing(self):
        hebus = member(
            "Hebus", skills={HERBALISM: (200, 300)}, carried=(held(4, DREAMFOIL, 9),)
        )
        members, posts = guild(
            [hebus, ALCHEMIST, HOLDER], [HERBALIST_POST, ALCHEMIST_POST]
        )
        plan = fa.assign(
            [deficit(DREAMFOIL, "Dreamfoil", 5)],
            members,
            posts,
            standing=[standing_task(baseline={4})],
        )
        self.assertEqual(plan.steps, ())

    def test_a_standing_task_is_not_assigned_again(self):
        members, posts = guild([HERBALIST, ALCHEMIST], [HERBALIST_POST, ALCHEMIST_POST])
        plan = fa.assign(
            [deficit(DREAMFOIL, "Dreamfoil", 5)],
            members,
            posts,
            standing=[standing_task()],
        )
        self.assertEqual(plan.tasks, ())

    def test_gathered_material_is_posted_once_the_deficit_has_closed(self):
        hebus = member(
            "Hebus", skills={HERBALISM: (200, 300)}, carried=(held(5, DREAMFOIL, 6),)
        )
        members, posts = guild([hebus, ALCHEMIST], [HERBALIST_POST, ALCHEMIST_POST])
        plan = fa.assign([], members, posts, standing=[standing_task()])
        self.assertEqual([s.holder for s in plan.steps], ["Hebus"])

    def test_a_second_pass_inside_the_cooldown_posts_nothing(self):
        hebus = member(
            "Hebus", skills={HERBALISM: (200, 300)}, carried=(held(5, DREAMFOIL, 6),)
        )
        members, posts = guild([hebus, ALCHEMIST], [HERBALIST_POST, ALCHEMIST_POST])
        first = fa.assign([], members, posts, standing=[standing_task()])
        rows = [
            {"source": row.source, "target_name": step.holder, "age": 5}
            for step in first.steps
            for row in (step.walk, *step.rows)
        ]
        recent = gc.recent_from_rows(rows, prefix=fa.SOURCE)
        second = fa.assign(
            [], members, posts, recent=recent, standing=[standing_task()]
        )
        self.assertEqual(len(first.steps), 1)
        self.assertEqual(second.steps, ())


class TheReagentDeficits(unittest.TestCase):
    def test_a_short_potion_wants_its_herbs_less_what_the_guild_carries(self):
        # Major Mana Potion: 3 Dreamfoil and 2 Icecap each.
        line = types.SimpleNamespace(entry=13444, short=2)
        out = fa.reagent_deficits([line], [HOLDER])
        # The holder's 9 Dreamfoil cover the 6 wanted; no one carries Icecap.
        self.assertEqual(
            [(d.entry, d.name, d.short) for d in out], [(13467, "Icecap", 4)]
        )

    def test_a_bought_supply_wants_no_reagent(self):
        line = types.SimpleNamespace(entry=12451, short=4)  # Juju Power
        self.assertEqual(fa.reagent_deficits([line], []), [])


if __name__ == "__main__":
    unittest.main()
