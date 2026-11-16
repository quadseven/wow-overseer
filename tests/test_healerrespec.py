"""Three of Cave's level 60 paladins respec to Holy at a class trainer.

The first-kill quorum asks for eight healers and Cave had two at level 50 or
more, while all six of its level 60 paladins were seated Retribution. The owner
decided that three of them change trees by the natural path only: walk to a
paladin trainer, pay the talent reset from their own purse, spend the points in
Holy. The module already does the whole errand (`walk-to-trainer talents:<tree>`,
mod-overseer#692: the reset through the core's own handler, the premade Holy
build, then PlayerbotAI::ResetStrategies, which hands a Holy paladin the
healing strategy). Nothing wrote that row. healerrespec.py is the planner that
does.
"""

import unittest

import guildroute
import healerrespec
import raidlineup
import raidroles
import raidrun
import raidteams

PALADIN = 2
GOLD = 10000


def _spells(class_id, tree, points):
    """Spell ids that make `points` ranks of `tree` read as the played tree."""
    out = []
    for spell, (cid, name, rank) in sorted(raidroles._book().items()):
        if cid == class_id and name == tree and rank == 1 and len(out) < points:
            out.append(spell)
    return ",".join(str(s) for s in out)


RET = _spells(PALADIN, "Retribution", 8)
HOLY = _spells(PALADIN, "Holy", 8)


def row(name="Embo", **kw):
    base = {
        "name": name,
        "class_id": PALADIN,
        "level": 60,
        "money": 58 * GOLD,
        "online": 1,
        "resettalents_cost": 0,
        "talent_spells": RET,
    }
    base.update(kw)
    return base


def walker(name="Embo", **kw):
    return guildroute.Walker(name, map_id=0, by_row=True, **kw)


class TheSeats(unittest.TestCase):
    def test_the_fixture_reads_as_the_trees_it_names(self):
        self.assertEqual("Retribution", raidroles.tree_of(PALADIN, RET))
        self.assertEqual("Holy", raidroles.tree_of(PALADIN, HOLY))

    def test_three_cave_paladins_hold_holy_healer_seats(self):
        names = healerrespec.names("Cave")
        self.assertEqual(3, len(names))
        by_name = {s.name: s for s in raidteams.seats("Cave")}
        for name in names:
            seat = by_name[name]
            self.assertEqual(
                (PALADIN, "Holy", "healer"), (seat.class_id, seat.tree, seat.seat)
            )
            self.assertTrue(seat.fire_resistance, name)

    def test_the_other_guild_and_the_other_seats_are_untouched(self):
        self.assertEqual((), healerrespec.names("Bonkers"))
        retribution = [
            s.name for s in raidteams.seats("Cave") if s.tree == "Retribution"
        ]
        self.assertEqual(4, len(retribution))
        self.assertFalse(set(retribution) & set(healerrespec.names("Cave")))

    def test_no_picked_paladin_is_on_the_roster_family(self):
        family = {s.name for s in raidteams.GROUPS["Cave"][0]}
        self.assertFalse(family & set(healerrespec.names("Cave")))


class ThePrice(unittest.TestCase):
    def test_the_reset_price_follows_the_core(self):
        self.assertEqual(1 * GOLD, healerrespec.reset_price(0))
        self.assertEqual(5 * GOLD, healerrespec.reset_price(1 * GOLD))
        self.assertEqual(10 * GOLD, healerrespec.reset_price(5 * GOLD))
        self.assertEqual(15 * GOLD, healerrespec.reset_price(10 * GOLD))
        self.assertEqual(50 * GOLD, healerrespec.reset_price(48 * GOLD))
        self.assertEqual(50 * GOLD, healerrespec.reset_price(50 * GOLD))


class TheCandidates(unittest.TestCase):
    def test_a_retribution_paladin_on_a_holy_seat_is_a_candidate(self):
        found, notes = healerrespec.candidates("Cave", [row()], roster=set())
        self.assertEqual(["Embo"], [c.name for c in found])
        self.assertEqual("Retribution", found[0].played)
        self.assertEqual(1 * GOLD, found[0].price)
        self.assertEqual([], notes)

    def test_the_name_it_has_until_the_rename_matches_too(self):
        was = next(s.was for s in raidteams.seats("Cave") if s.name == "Embo")
        found, _ = healerrespec.candidates("Cave", [row(was)], roster=set())
        self.assertEqual([was], [c.name for c in found])

    def test_a_paladin_already_playing_holy_is_not(self):
        found, _ = healerrespec.candidates(
            "Cave", [row(talent_spells=HOLY)], roster=set()
        )
        self.assertEqual([], found)

    def test_a_paladin_with_no_spent_talents_is_not(self):
        found, _ = healerrespec.candidates(
            "Cave", [row(talent_spells="")], roster=set()
        )
        self.assertEqual([], found)

    def test_a_purse_below_the_price_saves_up_and_says_so(self):
        found, notes = healerrespec.candidates(
            "Cave", [row(money=GOLD - 1)], roster=set()
        )
        self.assertEqual([], found)
        self.assertEqual(1, len(notes))
        self.assertIn("Embo", notes[0])
        self.assertIn("saves", notes[0])

    def test_the_price_is_the_characters_own_reset_count(self):
        found, notes = healerrespec.candidates(
            "Cave", [row(money=9 * GOLD, resettalents_cost=5 * GOLD)], roster=set()
        )
        self.assertEqual([], found)
        self.assertIn("10", notes[0])

    def test_a_roster_character_is_left_to_the_roster_drive(self):
        found, _ = healerrespec.candidates("Cave", [row()], roster={"Embo"})
        self.assertEqual([], found)

    def test_a_character_the_decision_does_not_name_is_never_picked(self):
        found, _ = healerrespec.candidates("Cave", [row("Frakk")], roster=set())
        self.assertEqual([], found)


class ThePlan(unittest.TestCase):
    def _cand(self, name="Embo"):
        found, _ = healerrespec.candidates("Cave", [row(name)], roster=set())
        return found

    def test_the_walk_is_the_modules_talents_row_to_the_seats_tab(self):
        walks, notes = healerrespec.plan(
            self._cand(), {"Embo": walker()}, recent=set(), busy=set()
        )
        self.assertEqual(1, len(walks))
        tab = raidroles.tree_tab(PALADIN, "Holy")  # the paladin's Holy page is 0
        self.assertRegex(
            walks[0].command, r"^walk-to-trainer talents:%d( max:\d+)?$" % tab
        )
        self.assertEqual("cast", walks[0].kind)
        self.assertEqual("healerrespec:Embo", walks[0].source)
        self.assertEqual([], notes)

    def test_a_member_on_another_guild_walk_waits(self):
        walks, notes = healerrespec.plan(
            self._cand(), {"Embo": walker()}, recent=set(), busy={"Embo"}
        )
        self.assertEqual([], walks)
        self.assertIn("another guild walk", notes[0])

    def test_a_member_walked_inside_the_cooldown_waits_quietly(self):
        walks, notes = healerrespec.plan(
            self._cand(), {"Embo": walker()}, recent={"Embo"}, busy=set()
        )
        self.assertEqual(([], []), (walks, notes))

    def test_a_member_the_walk_cannot_reach_waits_with_the_reason(self):
        walks, notes = healerrespec.plan(self._cand(), {}, recent=set(), busy=set())
        self.assertEqual([], walks)
        self.assertIn("not in the world", notes[0])

    def test_recent_reads_the_command_log_by_source(self):
        rows = [
            {"source": "healerrespec:Embo", "age": 30, "target_name": "Embo"},
            {"source": "healerrespec:Bonk", "age": 9999, "target_name": "Bonk"},
            {"source": "guildtrain:Clobba", "age": 1, "target_name": "Clobba"},
        ]
        self.assertEqual({"Embo"}, healerrespec.recent_walkers(rows))


class TheLineup(unittest.TestCase):
    def test_cave_wants_fourteen_healers_and_eighteen_damage(self):
        seats = [s.seat for s in raidteams.seats("Cave")]
        self.assertEqual(8, seats.count(raidroles.SEAT_TANK))
        self.assertEqual(14, seats.count(raidroles.SEAT_HEALER))
        self.assertEqual(18, seats.count(raidroles.SEAT_DAMAGE))

    def test_a_seat_still_in_its_old_tree_is_marked_as_a_respec(self):
        seat = next(s for s in raidteams.seats("Cave") if s.name == "Embo")
        member = {"name": "Embo", "class_id": PALADIN, "spec": "Retribution"}
        placed = raidlineup._approved_seat(member, seat, 5)
        self.assertTrue(placed["respec"])
        self.assertEqual("Holy", placed["target_spec"])
        self.assertIn("now Retribution", placed["label"])

    def test_a_seat_already_in_its_tree_is_not(self):
        seat = next(s for s in raidteams.seats("Cave") if s.name == "Embo")
        member = {"name": "Embo", "class_id": PALADIN, "spec": "Holy"}
        self.assertFalse(raidlineup._approved_seat(member, seat, 5)["respec"])

    def test_an_unread_tree_is_unproven_and_marked_too(self):
        seat = next(s for s in raidteams.seats("Cave") if s.name == "Embo")
        for spec in ("", None):
            member = {"name": "Embo", "class_id": PALADIN, "spec": spec}
            placed = raidlineup._approved_seat(member, seat, 5)
            self.assertTrue(placed["respec"], repr(spec))
            self.assertIn("unread", placed["label"])

    def test_an_unread_tree_keeps_the_seat_out_of_the_first_kill_count(self):
        seat = next(s for s in raidteams.seats("Cave") if s.name == "Embo")
        placed = raidlineup._approved_seat(
            {"name": "Embo", "class_id": PALADIN, "spec": ""}, seat, 5
        )
        lineup = {"groups": [{"number": 1, "members": [placed]}]}
        out = raidrun.first_kill_roster(
            "moltencore",
            lineup,
            [{"name": "Embo", "level": 60, "online": 1}],
            quorum=(1, 0, 1),
        )
        self.assertNotIn("Embo", out.seats)
        self.assertIn("respec", dict(out.left_out)["Embo"])

    def test_an_ordinary_seat_is_never_marked(self):
        seat = next(s for s in raidteams.seats("Cave") if s.name == "Frakk")
        member = {"name": "Frakk", "class_id": PALADIN, "spec": "Holy"}
        self.assertFalse(raidlineup._approved_seat(member, seat, 6)["respec"])


class TheFirstKill(unittest.TestCase):
    def _lineup(self, healer_respec):
        members = [
            {"name": "Ugga", "role": "healer", "respec": False},
            {"name": "Embo", "role": "healer", "respec": healer_respec},
            {"name": "Grug", "role": "tank", "respec": False},
        ]
        return {"groups": [{"number": 1, "members": members}]}

    def _rows(self):
        return [{"name": n, "level": 60, "online": 1} for n in ("Ugga", "Embo", "Grug")]

    def test_a_healer_seat_still_in_its_old_tree_does_not_count_as_a_healer(self):
        out = raidrun.first_kill_roster(
            "moltencore", self._lineup(True), self._rows(), quorum=(3, 1, 2)
        )
        self.assertNotIn("Embo", out.seats)
        self.assertIn("respec", dict(out.left_out)["Embo"])
        self.assertTrue(out.refusal)

    def test_once_it_plays_holy_it_counts(self):
        out = raidrun.first_kill_roster(
            "moltencore", self._lineup(False), self._rows(), quorum=(3, 1, 2)
        )
        self.assertIn("Embo", out.seats)
        self.assertEqual("", out.refusal)


class TheBridge(unittest.TestCase):
    def _text(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_the_guild_train_loop_runs_the_respec_pass_for_every_family(self):
        text = self._text("bridge.py")
        loop = text[
            text.index("async def _guild_train_loop") : text.index(
                "async def _guild_train_once"
            )
        ]
        self.assertIn("_guild_respec_once", loop)
        self.assertIn('_for_other_families("guild respec"', loop)
        once = text[
            text.index("async def _guild_respec_once") : text.index(
                "def _guild_walkers_busy"
            )
        ]
        self.assertIn("healerrespec.plan(", once)
        self.assertIn("_start_train_walk", once)


if __name__ == "__main__":
    unittest.main()
