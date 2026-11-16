"""Pointing the Watcher at any character, stopping it, and the live-now list.

The page sends a run id, a character name or a stop, never a sentence. The
name goes through director.parse_watch's `character` grammar, a bound value in
SQL, and the same 90 second dwell as a run. The live list is a pure function of
the snapshot, the guild runs and the raid seats.
"""

import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import director as d
from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import map_server

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def row(spec="run 285", ttl=None, target="Tanky", note="Tanky: follow"):
    return {
        "spec": spec,
        "ttl": d.MANDATE_TTL if ttl is None else ttl,
        "target": target,
        "note": note,
    }


class TheCharacterOrder(unittest.TestCase):
    def test_a_name_becomes_the_character_order(self):
        got = d.spectate_character("Ugga")
        self.assertEqual(got.text(), "character Ugga")

    def test_only_a_plain_name_is_accepted(self):
        for bad in (
            None,
            5,
            "",
            " ",
            "Ug ga",
            "Ugga; DROP TABLE x",
            "Ugga\nrun 5",
            "x",
            "Abcdefghijklm",
            "Ug-ga",
            "off 5",
            "Ugga\n",
            "Ugga\n\n",
            " Ugga",
            ["Ugga"],
            {"n": "Ugga"},
        ):
            self.assertIsInstance(d.spectate_character(bad), d.SpecError, repr(bad))

    def test_the_watcher_cannot_be_pointed_at_itself(self):
        self.assertIsInstance(d.spectate_character(d.WATCHER_NAME), d.SpecError)
        self.assertIsInstance(d.spectate_character(d.WATCHER_NAME.upper()), d.SpecError)

    def test_the_live_payload_is_a_typed_record(self):
        self.assertEqual(
            sorted(d.LiveNow.__annotations__), ["battlegrounds", "dungeons", "raids"]
        )

    def test_stop_is_the_off_order(self):
        self.assertEqual(d.spectate_stop().text(), "off")


class TheStateNamesTheCharacter(unittest.TestCase):
    def test_a_character_order_reports_the_name(self):
        live = d.spectate_state(row("character Ugga", ttl=d.MANDATE_TTL - 5))
        self.assertEqual(live["character"], "Ugga")
        self.assertIsNone(live["run"])

    def test_a_run_order_or_no_order_has_no_character(self):
        self.assertEqual(d.spectate_state(row("run 3"))["character"], "")
        self.assertEqual(d.spectate_state(None)["character"], "")
        self.assertEqual(d.order_character("guild Bonkers"), "")
        self.assertEqual(d.order_character("character Grug"), "Grug")


class Handler(map_server.Handler):
    def __init__(self, body):
        raw = json.dumps(body).encode()
        self.rfile = io.BytesIO(raw)
        self.headers = {
            "Content-Length": str(len(raw)),
            "Content-Type": "application/json",
        }
        self.sent = []

    def _send(self, code, ctype, body):
        self.sent.append((code, json.loads(body)))


class ThePost(unittest.TestCase):
    def order(self, body, current=None):
        handler = Handler(body)
        cursor = mock.MagicMock()
        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cursor
        with (
            mock.patch.object(map_server, "_read_watch_order", return_value=current),
            mock.patch.object(map_server, "_connect", return_value=conn),
        ):
            handler._spectate_post()
        return handler.sent[-1], cursor

    def test_a_character_writes_a_bound_character_order(self):
        (code, body), cursor = self.order({"character": "Ugga"})
        self.assertEqual(
            (code, body["spec"], body["character"]), (200, "character Ugga", "Ugga")
        )
        cursor.execute.assert_called_once_with(
            d.SET_SQL, ("character Ugga", "web:spectate", d.MANDATE_TTL)
        )

    def test_bad_names_are_a_400_and_write_nothing(self):
        for bad in ("Ug ga", "x; --", "run 5", "", None, 7, d.WATCHER_NAME):
            (code, _body), cursor = self.order({"character": bad})
            self.assertEqual(code, 400, repr(bad))
            cursor.execute.assert_not_called()

    def test_exactly_one_of_run_character_stop(self):
        for both in (
            {"run": 5, "character": "Ugga"},
            {"run": 5, "stop": True},
            {"character": "Ugga", "stop": True},
            {},
            {"stop": False},
            {"stop": "yes"},
        ):
            (code, _body), cursor = self.order(both)
            self.assertEqual(code, 400, repr(both))
            cursor.execute.assert_not_called()

    def test_a_different_character_inside_the_dwell_is_a_409(self):
        current = row("character Grug", ttl=d.MANDATE_TTL - 20)
        (code, body), cursor = self.order({"character": "Ugga"}, current)
        self.assertEqual(code, 409)
        self.assertEqual(body["switch_in"], int(d.SPECTATE_DWELL - 20))
        cursor.execute.assert_not_called()

    def test_the_same_character_again_renews(self):
        current = row("character Ugga", ttl=d.MANDATE_TTL - 20)
        (code, _body), cursor = self.order({"character": "Ugga"}, current)
        self.assertEqual(code, 200)
        cursor.execute.assert_called_once()

    def test_a_run_over_a_character_inside_the_dwell_is_a_409(self):
        current = row("character Grug", ttl=d.MANDATE_TTL - 20)
        (code, _b), cursor = self.order({"run": 285}, current)
        self.assertEqual(code, 409)
        cursor.execute.assert_not_called()

    def test_stop_clears_the_order(self):
        current = row("character Grug", ttl=d.MANDATE_TTL - 200)
        (code, body), cursor = self.order({"stop": True}, current)
        self.assertEqual((code, body["stopped"]), (200, True))
        cursor.execute.assert_called_once_with(d.CLEAR_SQL)

    def test_stop_inside_the_dwell_is_a_409_like_any_switch(self):
        current = row("character Grug", ttl=d.MANDATE_TTL - 20)
        (code, _b), cursor = self.order({"stop": True}, current)
        self.assertEqual(code, 409)
        cursor.execute.assert_not_called()

    def test_stop_with_nothing_on_is_fine_and_writes_nothing(self):
        (code, body), cursor = self.order({"stop": True}, None)
        self.assertEqual((code, body["stopped"]), (200, True))
        cursor.execute.assert_not_called()


def spot(name, map_id, inst=1, combat=False, x=0.0):
    return {
        "name": name,
        "map_id": map_id,
        "instance_id": inst,
        "pos_x": x,
        "pos_y": 0,
        "pos_z": 0,
        "in_combat": combat,
        "group_leader": 0,
    }


def active_run():
    return {
        "id": 285,
        "guild": "Bonkers",
        "state": "inside",
        "title": "Bonkers - Scarlet Monastery",
        "place": "Scarlet Monastery",
        "bosses_done": 1,
        "bosses_total": 4,
        "deaths": 2,
        "seconds_inside": 1800,
        "members": [
            {"name": "Tanky", "seat": "tank"},
            {"name": "Heely", "seat": "healer"},
        ],
    }


NAMES = {409: "Molten Core", 489: "Warsong Gulch"}


class TheLiveList(unittest.TestCase):
    def live(self, spots=(), runs=(), seats=()):
        return d.live_now(
            list(spots), list(runs), list(seats), lambda m: NAMES.get(m, "map %s" % m)
        )

    def test_nothing_live_is_three_empty_lists(self):
        got = self.live()
        self.assertEqual(
            (got["dungeons"], got["raids"], got["battlegrounds"]), ([], [], [])
        )

    def test_a_run_inside_is_a_dungeon_with_seats_progress_and_a_run_order(self):
        got = self.live(runs=[active_run()])["dungeons"]
        self.assertEqual(len(got), 1)
        g = got[0]
        self.assertEqual(g["order"], {"run": 285})
        self.assertEqual([s["name"] for s in g["seats"]], ["Tanky", "Heely"])
        self.assertIn("1 of 4 bosses down", g["progress"])
        self.assertIn("2 deaths", g["progress"])

    def test_a_queued_or_ended_run_is_not_live(self):
        for state in ("queued", "ended"):
            r = dict(active_run(), state=state)
            self.assertEqual(self.live(runs=[r])["dungeons"], [], state)

    def test_unmeasured_bosses_are_said_not_invented(self):
        r = dict(active_run(), bosses_total=0)
        self.assertIn(
            "bosses not measured", self.live(runs=[r])["dungeons"][0]["progress"]
        )

    def test_a_crowd_on_a_raid_map_is_a_raid_jumped_into_by_a_tank(self):
        spots = [d.spot_from_row(spot("R%d" % i, 409, combat=i < 3)) for i in range(5)]
        got = self.live(spots=spots, seats=[("R4", "tank"), ("R2", "healer")])["raids"]
        self.assertEqual(len(got), 1)
        g = got[0]
        self.assertEqual((g["place"], g["count"], g["fighting"]), ("Molten Core", 5, 3))
        self.assertEqual(g["order"], {"character": "R4"})
        self.assertEqual((g["tanks"], g["healers"]), (1, 1))
        self.assertIn("5 inside", g["progress"])

    def test_a_battleground_is_listed_apart_from_raids(self):
        spots = [d.spot_from_row(spot(n, 489, combat=True)) for n in ("Aa", "Bb")]
        got = self.live(spots=spots)
        self.assertEqual(got["raids"], [])
        self.assertEqual(got["battlegrounds"][0]["place"], "Warsong Gulch")
        self.assertIn("order", got["battlegrounds"][0])

    def test_an_unresolved_instance_is_not_offered_as_a_jump_target(self):
        # The bridge refuses a target on an instance map whose instance id is
        # still 0 (R_UNRESOLVED), so a button for it could never move the camera.
        for map_id in (409, 489):
            spots = [
                d.spot_from_row(spot(n, map_id, inst=0)) for n in ("Aa", "Bb", "Cc")
            ]
            got = self.live(spots=spots)
            self.assertEqual((got["raids"], got["battlegrounds"]), ([], []), map_id)

    def test_resolved_members_still_list_when_an_unresolved_one_stands_beside(self):
        spots = [d.spot_from_row(spot(n, 409, inst=7)) for n in ("Aa", "Bb")]
        spots.append(d.spot_from_row(spot("Cc", 409, inst=0)))
        got = self.live(spots=spots)["raids"]
        self.assertEqual([(g["instance_id"], g["count"]) for g in got], [(7, 2)])

    def test_a_lone_character_or_the_watcher_does_not_make_a_group(self):
        lone = [d.spot_from_row(spot("Aa", 409))]
        self.assertEqual(self.live(spots=lone)["raids"], [])
        watcher = lone + [d.spot_from_row(spot(d.WATCHER_NAME, 409))]
        self.assertEqual(self.live(spots=watcher)["raids"], [])

    def test_two_copies_of_one_raid_are_two_groups_biggest_first(self):
        a = [d.spot_from_row(spot("A%d" % i, 409, inst=1)) for i in range(3)]
        b = [d.spot_from_row(spot("B%d" % i, 409, inst=2)) for i in range(5)]
        got = self.live(spots=a + b)["raids"]
        self.assertEqual([g["count"] for g in got], [5, 3])

    def test_every_order_is_one_the_post_accepts(self):
        spots = [d.spot_from_row(spot(n, 409)) for n in ("Aa", "Bb")]
        got = self.live(spots=spots, runs=[active_run()])
        run = got["dungeons"][0]["order"]["run"]
        self.assertNotIsInstance(d.spectate_spec(run), d.SpecError)
        who = got["raids"][0]["order"]["character"]
        self.assertNotIsInstance(d.spectate_character(who), d.SpecError)


class TheLiveRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "map_server.py"), encoding="utf8") as fh:
            cls.src = fh.read()

    def test_it_is_a_read_only_registered_route(self):
        self.assertIn('"/api/live": _live_now', self.src)
        self.assertNotIn("_live_now_post", self.src)
        self.assertIs(
            map_server.Handler.GET_ROUTES["/api/live"], map_server.Handler._live_now
        )

    def test_it_reads_the_snapshot_runs_and_seats_and_hands_them_to_director(self):
        body = self.src[self.src.index("def _live_now") :]
        body = body[: body.index("\n    @_get_route", 10)]
        self.assertIn("director.live_now(", body)
        self.assertIn("overseer_snapshot", body)
        self.assertIn("overseer_raid_seat", body)

    def test_the_post_takes_character_and_stop_through_director(self):
        body = self.src[
            self.src.index("def _spectate_post") : self.src.index("def _read_json_body")
        ]
        self.assertIn("director.spectate_character(", body)
        self.assertIn("director.spectate_stop(", body)
        self.assertNotIn("_DIRECTOR_TOKEN", body)


if __name__ == "__main__":
    unittest.main()
