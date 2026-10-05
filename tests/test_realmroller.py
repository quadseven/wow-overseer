"""The realm roller's file formats and its pure tick (#590)."""

import copy
import json
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import realmroller as rr  # noqa: E402

EXAMPLE = pathlib.Path(__file__).resolve().parents[1] / "tools" / "realm_roller_example"
T0 = datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc)  # 23:00 New York


def _json(name):
    return json.loads((EXAMPLE / name).read_text())


def _channel_data(**over):
    d = _json("channel.json")
    d.update(over)
    return d


def _release_data(name):
    return _json("releases/%s.json" % name)


def _set(channel=None, extra=(), **chan_over):
    """The example channel and releases, parsed, with optional edits."""
    ch = rr.parse_channel(channel or _channel_data(**chan_over))
    rels = {}
    for n in ("r2026.10.03-3", "r2026.10.04-1", "r2026.10.04-2"):
        rels[n] = rr.parse_release(_release_data(n), ch)
    for data in extra:
        rel = rr.parse_release(data, ch)
        rels[rel.name] = rel
    return ch, rels


def _clear(**over):
    """A world where every gate is open."""
    base = dict(
        now=T0,
        family_in_instance=0,
        guild_groups_inside=0,
        out_since=T0 - timedelta(minutes=9),
        last_roll_started=T0 - timedelta(hours=2),
    )
    base.update(over)
    return rr.World(**base)


def _ev(at, to):
    return {"at": at.isoformat(), "to": to, "by": "roller", "note": ""}


def _release(
    name, state, sources_over=None, images=None, history_to=None, changes=None
):
    """A release derived from the proven example, moved to `state`."""
    d = copy.deepcopy(_release_data("r2026.10.04-2"))
    d["release"] = name
    # The current release's sources, so a test names exactly what it changes.
    d["sources"] = dict(_release_data("r2026.10.04-1")["sources"])
    d["sources"].update(sources_over or {})
    if images is not None:
        d["build"]["images"] = images
    if changes is not None:
        d["changes"] = changes
    path = {
        "proposed": [],
        "building": ["building"],
        "built": ["building", "built"],
        "proven": ["building", "built", "proven"],
        "rolling": ["building", "built", "proven", "rolling"],
        "live": ["building", "built", "proven", "rolling", "live"],
    }[state]
    times = history_to or {}
    start = T0 - timedelta(hours=6)
    d["history"] = [
        _ev(times.get(s, start + timedelta(minutes=i)), s) for i, s in enumerate(path)
    ]
    d["state"] = state
    return d


class ChannelFile(unittest.TestCase):
    def test_example_parses(self):
        ch, rels = _set()
        rr.check_set(ch, rels)
        self.assertEqual(ch.current, "r2026.10.04-1")
        self.assertEqual(len(ch.components), 2)

    def test_a_channel_without_paused_is_paused(self):
        d = _channel_data()
        del d["paused"]
        self.assertTrue(rr.parse_channel(d).paused)

    def test_only_a_literal_false_unpauses(self):
        self.assertFalse(rr.parse_channel(_channel_data(paused=False)).paused)
        with self.assertRaises(rr.Invalid) as e:
            rr.parse_channel(_channel_data(paused="false"))
        self.assertIn("paused must be true or false", str(e.exception))

    def test_every_problem_is_reported_at_once(self):
        d = _channel_data(current="latest", queue=["r2026.10.04-2", "r2026.10.04-2"])
        d["policy"]["settle"] = "five minutes"
        with self.assertRaises(rr.Invalid) as e:
            rr.parse_channel(d)
        self.assertEqual(len(e.exception.problems), 3, e.exception.problems)

    def test_a_source_in_two_components_is_refused(self):
        d = _channel_data()
        d["components"]["site"]["sources"].append("core")
        with self.assertRaises(rr.Invalid) as e:
            rr.parse_channel(d)
        self.assertIn("source core belongs to two components", str(e.exception))

    def test_previous_must_be_verified(self):
        ch = rr.parse_channel(_channel_data())
        rels = {
            n: rr.parse_release(_release_data(n), ch)
            for n in ("r2026.10.04-1", "r2026.10.04-2")
        }
        rels["r2026.10.03-3"] = rr.parse_release(_release("r2026.10.03-3", "live"), ch)
        with self.assertRaises(rr.Invalid) as e:
            rr.check_set(ch, rels)
        self.assertIn("rollback target must be verified", str(e.exception))

    def test_a_queued_release_needs_a_file(self):
        ch = rr.parse_channel(_channel_data(queue=["r2026.10.04-9"]))
        _, rels = _set()
        with self.assertRaises(rr.Invalid) as e:
            rr.check_set(ch, rels)
        self.assertIn("queued r2026.10.04-9 has no release file", str(e.exception))

    def test_a_built_release_without_db_import_is_refused(self):
        bad = _release(
            "r2026.10.04-3",
            "built",
            {"mod-overseer": "9" * 40},
            images={"worldserver": "sha256:" + "e" * 64},
        )
        ch, rels = _set(extra=[bad], queue=["r2026.10.04-2", "r2026.10.04-3"])
        with self.assertRaises(rr.Invalid) as e:
            rr.check_set(ch, rels)
        self.assertIn(
            "r2026.10.04-3 is built without the db-import digest", str(e.exception)
        )

    def test_a_site_only_release_needs_only_the_site_digest(self):
        site = _release(
            "r2026.10.04-3",
            "built",
            {"site": "9" * 40},
            images={"site": "sha256:" + "e" * 64},
        )
        ch, rels = _set(extra=[site], queue=["r2026.10.04-2", "r2026.10.04-3"])
        rr.check_set(ch, rels)


class ReleaseFile(unittest.TestCase):
    def setUp(self):
        self.ch = rr.parse_channel(_channel_data())

    def bad(self, data, needle):
        with self.assertRaises(rr.Invalid) as e:
            rr.parse_release(data, self.ch)
        self.assertIn(needle, str(e.exception))

    def test_every_source_every_time(self):
        d = _release_data("r2026.10.04-2")
        del d["sources"]["mod-ollama-chat"]
        self.bad(d, "sources lacks mod-ollama-chat")

    def test_a_fold_names_a_pr_and_is_a_boolean(self):
        ch = rr.parse_channel(_channel_data())
        d = _release_data("r2026.10.04-2")
        self.assertTrue(rr.parse_release(d, ch).changes[1].fold)
        self.assertEqual(rr.fold_number("#5010"), 5010)
        for bad_pr, bad_fold, want in (
            ("PR 104", True, "fold needs pr like"),
            ("#104", "yes", "fold must be true or false"),
        ):
            d = _release_data("r2026.10.04-2")
            d["changes"][1].update(pr=bad_pr, fold=bad_fold)
            with self.assertRaisesRegex(rr.Invalid, want):
                rr.parse_release(d, ch)

    def test_a_short_sha_is_refused(self):
        d = _release_data("r2026.10.04-2")
        d["sources"]["core"] = "47960183"
        self.bad(d, "sources.core must be a full 40-character SHA")

    def test_history_must_be_legal(self):
        d = _release_data("r2026.10.04-2")
        d["history"] = [_ev(T0, "built")]
        d["state"] = "built"
        self.bad(d, "proposed -> built, which is not a legal move")

    def test_history_must_end_at_state(self):
        d = _release_data("r2026.10.04-2")
        d["state"] = "rolling"
        self.bad(d, "history ends at proven but state is rolling")

    def test_a_naive_time_is_refused(self):
        d = _release_data("r2026.10.04-2")
        d["history"][0]["at"] = "2026-10-04T21:02:00"
        self.bad(d, "no UTC offset")

    def test_a_check_needs_exactly_one_of_grep_or_absent(self):
        d = _release_data("r2026.10.04-2")
        d["changes"][0]["verify"]["grep"] = "x"
        self.bad(d, "needs exactly one of grep or absent")

    def test_prove_must_name_an_image(self):
        d = _release_data("r2026.10.04-2")
        d["changes"][0]["prove"]["image"] = "mapserver"
        self.bad(d, "prove needs an image of a component")

    def test_an_unknown_digest_key_is_refused(self):
        d = _release_data("r2026.10.04-2")
        d["build"]["images"]["auth"] = "sha256:" + "a" * 64
        self.bad(d, "build.images.auth is not an image of any component")


class Gates(unittest.TestCase):
    def setUp(self):
        self.ch, self.rels = _set(paused=False)

    def tick(self, w, ch=None, rels=None):
        return rr.tick(ch or self.ch, rels or self.rels, w)

    def test_clear_rolls_the_proven_release(self):
        a = self.tick(_clear())
        self.assertEqual((a.kind, a.release), ("roll", "r2026.10.04-2"))
        self.assertIn("worldserver digests + banner + deployed_dev", a.why)

    def test_paused_waits(self):
        ch, rels = _set()  # the example is paused
        a = self.tick(_clear(), ch, rels)
        self.assertEqual(a.kind, "wait")
        self.assertIn("channel paused", a.why)

    def test_one_roll_start_an_hour(self):
        a = self.tick(_clear(last_roll_started=T0 - timedelta(minutes=20)))
        self.assertEqual(a.kind, "wait")
        self.assertIn("one roll start per 1h; next at 03:40Z", a.why)

    def test_unreachable_family_api_counts_as_inside(self):
        a = self.tick(_clear(family_in_instance=None))
        self.assertEqual(
            (a.kind, a.why), ("wait", "family API unreachable: treat as inside")
        )

    def test_family_inside_waits(self):
        a = self.tick(_clear(family_in_instance=3))
        self.assertEqual((a.kind, a.why), ("wait", "3 family member(s) in an instance"))

    def test_guild_group_inside_waits(self):
        a = self.tick(_clear(guild_groups_inside=1))
        self.assertEqual((a.kind, a.why), ("wait", "1 guild group(s) in an instance"))

    def test_unreadable_guild_runs_count_as_inside(self):
        a = self.tick(_clear(guild_groups_inside=None))
        self.assertEqual(a.kind, "wait")

    def test_just_out_settles(self):
        a = self.tick(_clear(out_since=T0 - timedelta(minutes=2)))
        self.assertEqual((a.kind, a.why), ("wait", "everyone out, settling for 5m"))
        self.assertEqual(self.tick(_clear(out_since=None)).kind, "wait")

    def test_newest_proven_coalesces_the_older(self):
        newer = _release("r2026.10.04-3", "proven", {"mod-overseer": "9" * 40})
        ch, rels = _set(
            extra=[newer], paused=False, queue=["r2026.10.04-2", "r2026.10.04-3"]
        )
        rr.check_set(ch, rels)
        a = self.tick(_clear(), ch, rels)
        self.assertEqual(
            (a.kind, a.release, a.supersedes),
            ("roll", "r2026.10.04-3", ("r2026.10.04-2",)),
        )

    def test_a_site_only_release_skips_the_worldserver_gates(self):
        site = _release(
            "r2026.10.04-3",
            "proven",
            {"site": "9" * 40},
            images={"site": "sha256:" + "e" * 64},
        )
        ch, rels = _set(extra=[site], paused=False, queue=["r2026.10.04-3"])
        a = self.tick(_clear(family_in_instance=4, last_roll_started=T0), ch, rels)
        self.assertEqual((a.kind, a.gated), ("roll", False))
        self.assertIn("restarts site only", a.why)

    def test_a_site_only_release_still_honours_pause(self):
        site = _release(
            "r2026.10.04-3",
            "proven",
            {"site": "9" * 40},
            images={"site": "sha256:" + "e" * 64},
        )
        ch, rels = _set(extra=[site], queue=["r2026.10.04-3"])
        self.assertEqual(self.tick(_clear(), ch, rels).kind, "wait")

    def test_build_and_prove_run_while_paused(self):
        for state, kind in (
            ("proposed", "build"),
            ("building", "watch_build"),
            ("built", "prove"),
        ):
            rel = _release(
                "r2026.10.04-3",
                state,
                {"mod-overseer": "9" * 40},
                images={} if state in ("proposed", "building") else None,
            )
            ch, rels = _set(extra=[rel], queue=["r2026.10.04-3"])
            self.assertTrue(ch.paused)
            self.assertEqual(
                self.tick(_clear(family_in_instance=5), ch, rels).kind, kind, state
            )

    def test_nothing_proven_waits(self):
        ch, rels = _set(paused=False, queue=[])
        self.assertEqual(self.tick(_clear(), ch, rels).why, "nothing proven")

    def test_a_failed_release_is_skipped(self):
        d = _release("r2026.10.04-3", "built", {"mod-overseer": "9" * 40})
        d["history"].append(_ev(T0, "prove_failed"))
        d["state"] = "prove_failed"
        ch, rels = _set(
            extra=[d], paused=False, queue=["r2026.10.04-3", "r2026.10.04-2"]
        )
        self.assertEqual(self.tick(_clear(), ch, rels).release, "r2026.10.04-2")


class Watch(unittest.TestCase):
    """A release on the realm: forward, or roll back (and pause)."""

    def on_realm(self, state, changes=None, rolled=None, live=None):
        if rolled is None:
            rolled = (live or T0) - timedelta(minutes=5)
        times = {"rolling": rolled}
        if live:
            times["live"] = live
        rel = _release(
            "r2026.10.04-3",
            state,
            {"mod-overseer": "9" * 40},
            history_to=times,
            changes=changes,
        )
        ch = rr.parse_channel(
            _channel_data(current="r2026.10.04-3", previous="r2026.10.04-1", queue=[])
        )
        rels = {n: rr.parse_release(_release_data(n), ch) for n in ("r2026.10.04-1",)}
        rels["r2026.10.04-3"] = rr.parse_release(rel, ch)
        rr.check_set(ch, rels)
        return ch, rels

    def test_the_watch_ignores_pause_and_gates(self):
        ch, rels = self.on_realm("rolling")
        self.assertTrue(ch.paused)
        a = rr.tick(ch, rels, _clear(family_in_instance=None, ready=True))
        self.assertEqual(a.kind, "mark_live")

    def test_not_ready_in_time_rolls_back_and_pauses(self):
        ch, rels = self.on_realm("rolling", rolled=T0 - timedelta(minutes=16))
        a = rr.tick(ch, rels, _clear(ready=False))
        self.assertEqual(
            (a.kind, a.target, a.pause), ("rollback", "r2026.10.04-1", True)
        )
        self.assertEqual(a.why, "not Ready within 15m")

    def test_the_ready_window_counts_from_the_merge_when_known(self):
        # The roll PR opened 40 minutes ago and merged 5 minutes ago: the
        # restart has had 5 minutes, not 40.
        ch, rels = self.on_realm("rolling", rolled=T0 - timedelta(minutes=40))
        w = _clear(ready=False, rolled_at=T0 - timedelta(minutes=5))
        self.assertEqual(rr.tick(ch, rels, w).why, "restarting")
        w = _clear(ready=False, rolled_at=T0 - timedelta(minutes=16))
        self.assertEqual(rr.tick(ch, rels, w).kind, "rollback")

    def test_still_starting_waits(self):
        ch, rels = self.on_realm("rolling")
        self.assertEqual(rr.tick(ch, rels, _clear(ready=False)).why, "restarting")

    def test_a_fatal_signature_rolls_back(self):
        ch, rels = self.on_realm("rolling")
        a = rr.tick(ch, rels, _clear(ready=True, bad_signature="Segmentation fault"))
        self.assertEqual(
            (a.kind, a.why), ("rollback", "log signature: Segmentation fault")
        )

    def test_too_many_restarts_roll_back(self):
        ch, rels = self.on_realm("rolling")
        self.assertEqual(
            rr.tick(ch, rels, _clear(ready=True, restarts=3)).kind, "rollback"
        )
        self.assertEqual(
            rr.tick(ch, rels, _clear(ready=True, restarts=2)).kind, "mark_live"
        )

    def live(self, changes, minutes):
        return self.on_realm(
            "live", changes=changes, live=T0 - timedelta(minutes=minutes)
        )

    GREP = {
        "pr": "#1",
        "what": "w",
        "verify": {"log": "worldserver", "grep": "answered the trade", "within": "45m"},
    }
    ABSENT = {
        "pr": "#2",
        "what": "w",
        "verify": {
            "log": "worldserver",
            "absent": "casting worldbuff",
            "within": "30m",
        },
    }

    def test_all_checks_pass_verifies(self):
        ch, rels = self.live([self.GREP, self.ABSENT], 31)
        a = rr.tick(ch, rels, _clear(seen={'"answered the trade"': True}))
        self.assertEqual((a.kind, a.why), ("mark_verified", "every check passed"))

    def test_an_absent_check_waits_out_its_window(self):
        ch, rels = self.live([self.GREP, self.ABSENT], 10)
        a = rr.tick(ch, rels, _clear(seen={'"answered the trade"': True}))
        self.assertEqual((a.kind, a.why), ("wait", "verifying: 1 check(s) open"))

    def test_a_missing_grep_after_its_window_rolls_back(self):
        ch, rels = self.live([self.GREP], 46)
        a = rr.tick(ch, rels, _clear())
        self.assertEqual(
            (a.kind, a.why, a.pause),
            ("rollback", 'never seen "answered the trade"', True),
        )

    def test_a_soft_missing_grep_is_flagged_not_rolled_back(self):
        soft = copy.deepcopy(self.GREP)
        soft["verify"]["soft"] = True
        ch, rels = self.live([soft], 46)
        a = rr.tick(ch, rels, _clear())
        self.assertEqual(a.kind, "mark_verified")
        self.assertIn('soft check(s) flagged: "answered the trade"', a.why)

    def test_an_absent_text_seen_rolls_back_at_once(self):
        ch, rels = self.live([self.ABSENT], 2)
        a = rr.tick(ch, rels, _clear(seen={'absent "casting worldbuff"': True}))
        self.assertEqual(
            (a.kind, a.why), ("rollback", 'seen absent "casting worldbuff"')
        )

    def test_bots_halved_for_ten_minutes_rolls_back(self):
        ch, rels = self.live([self.GREP], 20)
        self.assertEqual(
            rr.tick(ch, rels, _clear(bots_low_since=T0 - timedelta(minutes=9))).kind,
            "wait",
        )
        a = rr.tick(ch, rels, _clear(bots_low_since=T0 - timedelta(minutes=10)))
        self.assertEqual((a.kind, a.why), ("rollback", "bots online under 50% for 10m"))


class LastRollStart(unittest.TestCase):
    def test_the_latest_of_history_and_the_deploy_repo_mark(self):
        _, rels = _set()
        from_history = rels["r2026.10.04-1"].entered("rolling")
        self.assertEqual(rr.last_roll_start(rels, None), from_history)
        later = from_history + timedelta(hours=1)
        self.assertEqual(rr.last_roll_start(rels, later), later)
        self.assertEqual(rr.last_roll_start({}, None), None)

    def test_a_rollback_is_not_a_roll_start(self):
        d = _release(
            "r2026.10.04-3",
            "live",
            {"mod-overseer": "9" * 40},
            history_to={
                "rolling": T0 - timedelta(hours=1),
                "live": T0 - timedelta(minutes=50),
            },
        )
        d["history"].append(_ev(T0, "rolled_back"))
        d["state"] = "rolled_back"
        ch, rels = _set()
        rels["r2026.10.04-3"] = rr.parse_release(d, ch)
        self.assertEqual(rr.last_roll_start(rels, None), T0 - timedelta(hours=1))


class Durations(unittest.TestCase):
    def test_units(self):
        self.assertEqual(rr.duration("90s"), timedelta(seconds=90))
        self.assertEqual(rr.duration("5m"), timedelta(minutes=5))
        self.assertEqual(rr.duration("6h"), timedelta(hours=6))
        for bad in ("0m", "5", "1d", "", None, "-5m"):
            with self.assertRaises(ValueError):
                rr.duration(bad)


if __name__ == "__main__":
    unittest.main()
