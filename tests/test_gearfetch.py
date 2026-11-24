"""The gear fetch planner brings a holder and wearer to one mailbox (#2503)."""

import unittest

import gearfetch as gf
import gearrouting as gr
import keep


def route(holder="Cowpoke", wearer="Bigmon", guid=501):
    return gr.Route(
        wearer=wearer,
        holder=holder,
        guid=guid,
        entry=7001,
        item="Fez",
        slot="head",
        worn="Rags",
        worn_entry=1,
        gain=0.4,
        reason="beats worn",
    )


def member(name, x=0.0, y=0.0, **kw):
    return gf.Member(name, kw.pop("map_id", 0), x, y, **kw)


BOX = gf.Mailbox(0, 77, 100.0, 0.0)


def two(**kw):
    return {
        "Cowpoke": member("Cowpoke", 200.0, 0.0, **kw.get("holder", {})),
        "Bigmon": member("Bigmon", 120.0, 0.0, **kw.get("wearer", {})),
    }


class MeetPlan(unittest.TestCase):
    def test_two_guild_bots_walk_to_the_mailbox_nearest_the_wearer(self):
        far = gf.Mailbox(0, 78, 400.0, 0.0)
        plan = gf.plan([route()], two(), [far, BOX])
        (fetch,) = plan.fetches
        self.assertEqual(fetch.kind, gf.MEET)
        self.assertEqual(fetch.mailbox, 77)
        cmd = "walk-to-spawn gameobject:77 max:600 stay:%d" % gf.MEET_STAY_SECONDS
        self.assertEqual(fetch.walks, (("Cowpoke", cmd), ("Bigmon", cmd)))

    def test_a_family_wearer_goes_through_the_mailbox_run_with_no_row(self):
        members = two(wearer={"roster": True})
        (fetch,) = gf.plan([route()], members, [BOX]).fetches
        self.assertEqual((fetch.kind, fetch.walks), (gf.MAILBOX, ()))


class Refusals(unittest.TestCase):
    def refused(self, members=None, routes=None, boxes=(BOX,), **kw):
        plan = gf.plan(routes or [route()], members or two(), list(boxes), **kw)
        self.assertEqual(plan.fetches, ())
        (note,) = plan.notes
        return note

    def test_each_refusal_says_why(self):
        cases = [
            ("family member", two(holder={"roster": True}), {}),
            ("combat", two(wearer={"in_combat": True}), {}),
            ("instance", two(holder={"in_instance": True}), {}),
            ("another walk", two(), {"busy": {"Bigmon"}}),
            ("operator hold", two(wearer={"family": "F"}), {"held_families": {"F"}}),
            ("different maps", two(wearer={"map_id": 1}), {}),
            ("no mailbox", two(), {"boxes": ()}),
            ("avoid disc", two(), {"discs": [(0, 100.0, 0.0, 30.0)]}),
            ("within 600", two(), {"boxes": [gf.Mailbox(0, 9, 900.0, 0.0)]}),
        ]
        for words, members, kw in cases:
            with self.subTest(words):
                self.assertIn(words, self.refused(members, **kw))

    def test_the_bank_and_a_kept_piece_are_not_walked(self):
        self.assertIn("bank", self.refused(routes=[route(holder=gr.BANK_HOLDER)]))
        kept = keep.Reservations(guids={("cowpoke", 501)}, entries=set())
        self.assertIn("kept", self.refused(kept=kept))

    def test_a_holder_off_the_world_is_named(self):
        members = {"Bigmon": member("Bigmon")}
        self.assertIn("not in the world", self.refused(members))


class Bounds(unittest.TestCase):
    def many(self):
        routes, members = [], {}
        for i in range(4):
            h, w = "H%d" % i, "W%d" % i
            routes.append(route(h, w, 600 + i))
            members[h] = member(h, 200.0)
            members[w] = member(w, 120.0)
        return routes, members

    def test_per_pass_per_day_and_at_once(self):
        routes, members = self.many()
        got = gf.plan(routes, members, [BOX])
        self.assertEqual(len(got.fetches), gf.PER_PASS)
        self.assertEqual(len(got.notes), 4 - gf.PER_PASS)
        day = gf.plan(routes, members, [BOX], spent=gf.PER_DAY - 1)
        self.assertEqual(len(day.fetches), 1)
        self.assertIn("a day", day.notes[0])
        once = gf.plan(routes, members, [BOX], running=gf.AT_ONCE)
        self.assertEqual(once.fetches, ())
        self.assertIn("under way", once.notes[0])

    def test_a_member_is_walked_for_one_route_only(self):
        members = two()
        plan = gf.plan([route(), route(guid=502)], members, [BOX])
        self.assertEqual(len(plan.fetches), 1)
        self.assertIn("another walk", plan.notes[0])


if __name__ == "__main__":
    unittest.main()
