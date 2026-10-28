"""The post-run dungeon report (mod-overseer#152).

Every ended run row gets exactly one Discord message carrying its run id; the
report lists every loot_won row of the run; the family page shows the same
numbers as the Discord message; a wipe says wipe and lists its deaths.

The Discord half is bridge._post_run_reports, read out of bridge.py's source
and run against fakes (bridge.py imports discord and pymysql at module level,
so this suite cannot import it; tests/test_headless_bridge.py says why).
"""

import ast
import asyncio
import pathlib
import sys
import textwrap
import types
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import realmread  # noqa: E402
import runreport  # noqa: E402
import runtimeline  # noqa: E402

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

RUN = {
    "id": 412,
    "leader_name": "Ugga",
    "members": "Ugga,Og,Zug",
    "map_id": 36,
    "run_number": 3,
    "state": "ended",
    "outcome": "left",
    "ended_reason": "every boss down",
    "started_at": datetime(2026, 10, 20, 12, 0, 0),
    "ended_at": datetime(2026, 10, 20, 12, 41, 5),
    "duration_seconds": 2465,
}


def _event(name, kind, entry, subject, quality=None, detail=""):
    return {
        "character_name": name,
        "kind": kind,
        "subject_id": entry,
        "subject_name": subject,
        "detail": detail,
        "occurrences": 1,
        "quality": quality,
    }


EVENTS = [
    _event("Og", "boss_kill", 639, "Edwin VanCleef", detail="encounter Edwin VanCleef"),
    _event(
        "Zug", "boss_kill", 639, "Edwin VanCleef", detail="encounter Edwin VanCleef"
    ),
    _event("Ugga", "loot_won", 5191, "Cruel Barb", 3, "loot x1 from Edwin VanCleef"),
    _event("Ugga", "loot_won", 2589, "Linen Cloth", 1, "loot x1 from Defias Pirate"),
    _event("Og", "loot_won", 5193, "Cape of the Brotherhood", 3, "need x1"),
    _event("Zug", "loot_won", 1951, "Blackwater Cutlass", 2, "greed x1"),
    # Worn and won in this run: an upgrade.
    _event("Ugga", "item_equip", 5191, "Cruel Barb"),
    # Worn before the run and re-scanned inside it: not an upgrade.
    _event("Og", "item_equip", 2214, "Wooden Buckler"),
    _event("Zug", "quest_reward", 166, "The Defias Brotherhood"),
]


class EveryItemWonIsListed(unittest.TestCase):
    def test_each_loot_won_row_is_on_the_report_with_its_quality(self):
        report = runreport.build(RUN, EVENTS, [], "The Deadmines")
        text = runreport.render(report)
        loot_rows = [e for e in EVENTS if e["kind"] == "loot_won"]
        self.assertEqual(len(loot_rows), report["loot_count"])
        self.assertIn("Loot (%d):" % len(loot_rows), text)
        for row in loot_rows:
            with self.subTest(item=row["subject_name"]):
                self.assertIn(row["subject_name"], text)
        self.assertIn("Cruel Barb (rare)", text)
        self.assertIn("Blackwater Cutlass (uncommon)", text)

    def test_the_first_line_carries_the_run_id(self):
        text = runreport.render(runreport.build(RUN, EVENTS, [], "The Deadmines"))
        self.assertTrue(
            text.startswith("Run report #412: The Deadmines, run 3, 41m 05s")
        )

    def test_a_boss_seen_by_two_members_is_one_kill(self):
        report = runreport.build(RUN, EVENTS, [])
        self.assertEqual(["Edwin VanCleef"], report["bosses"])

    def test_an_upgrade_is_an_item_won_in_this_run_and_worn(self):
        report = runreport.build(RUN, EVENTS, [])
        self.assertEqual(1, report["upgrade_count"])
        self.assertEqual("Cruel Barb", report["upgrades"][0]["items"][0]["item"])

    def test_a_long_report_stays_one_message_and_keeps_every_count(self):
        many = [
            _event(
                "Ugga", "loot_won", 9000 + i, "Item Number %d With A Long Name" % i, 1
            )
            for i in range(120)
        ]
        report = runreport.build(RUN, many, [])
        text = runreport.render(report)
        self.assertLessEqual(len(text), runreport.DISCORD_LIMIT)
        self.assertIn("Loot (120):", text)
        self.assertIn("Quests completed (0): none", text)
        self.assertIn("more lines on the family page", text)


class AWipeSaysWipe(unittest.TestCase):
    WIPE = dict(RUN, outcome="wipe", ended_reason="everybody inside is dead")

    def test_a_wipe_lists_its_deaths_with_their_killers(self):
        deaths = [
            {"character_name": "Og", "killer_name": "Mr. Smite"},
            {"character_name": "Ugga", "killer_name": "Mr. Smite"},
            {"character_name": "Og", "killer_name": "Defias Pirate"},
        ]
        report = runreport.build(self.WIPE, [], deaths)
        text = runreport.render(report)
        self.assertTrue(report["wipe"])
        self.assertIn("outcome WIPE", text.split("\n")[0])
        self.assertIn("Deaths (3):", text)
        self.assertIn("Ugga: killed by Mr. Smite", text)
        self.assertIn("Og: killed by Mr. Smite, killed by Defias Pirate", text)
        self.assertNotIn("success", text.lower())

    def test_a_wipe_with_no_death_row_says_none_recorded(self):
        text = runreport.render(runreport.build(self.WIPE, [], []))
        self.assertIn("outcome WIPE", text)
        self.assertIn("Deaths (0): none recorded", text)

    def test_a_run_with_no_outcome_word_is_ended_not_a_success(self):
        text = runreport.render(runreport.build(dict(RUN, outcome=""), [], []))
        self.assertIn("outcome ended", text)


class TheDeathsReadIsBoundToTheRun(unittest.TestCase):
    def test_it_names_the_leader_and_each_member_once_and_the_window(self):
        sql, params = runreport.deaths_query(RUN)
        self.assertIn("character_name IN (%s, %s, %s)", sql)
        self.assertEqual(
            ("Ugga", "Og", "Zug", RUN["started_at"], RUN["ended_at"]), params
        )


def _fetcher(deaths=()):
    """A fetch that answers runreport's three reads, recording each."""
    asked = []

    def fetch(sql, params):
        asked.append(sql)
        if sql == runreport.RUN_SQL:
            return [RUN] if params == (412,) else []
        if sql == runreport.EVENTS_SQL:
            return list(EVENTS)
        if sql.startswith("SELECT character_name, killer_name FROM overseer_death"):
            return list(deaths)
        raise AssertionError(sql)

    return fetch, asked


class ThePageShowsWhatDiscordWasSent(unittest.TestCase):
    def test_the_run_card_carries_the_discord_lines_for_its_run_id(self):
        fetch, _ = _fetcher()
        report = runreport.read(fetch, 412)
        discord_text = runreport.render(report)
        rows = [
            {
                "id": 1,
                "family": "Ugga",
                "run_id": 0,
                "campaign_id": 7,
                "run_number": 3,
                "phase": "FORMING",
                "kind": "phase",
                "detail": "IDLE -> FORMING",
                "age_seconds": 3000,
            },
            {
                "id": 2,
                "family": "Ugga",
                "run_id": 412,
                "campaign_id": 7,
                "run_number": 3,
                "phase": "INSIDE",
                "kind": "ended",
                "detail": "left",
                "age_seconds": 100,
            },
        ]
        payload = runtimeline.build_run_timeline(
            rows,
            {"Ugga": ["Ugga", "Og", "Zug"]},
            now=datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc),
            reports={412: report},
        )
        card = payload["families"][0]["runs"][0]["report"]
        self.assertEqual(412, card["run_id"])
        self.assertEqual(discord_text, "\n".join(card["lines"]))
        self.assertEqual(
            {"bosses": 1, "deaths": 0, "loot": 4, "upgrades": 1, "quests": 1},
            card["counts"],
        )

    def test_both_readers_go_through_runreport_read(self):
        bridge = BRIDGE.read_text(encoding="utf-8")
        server = (BRIDGE.parent / "map_server.py").read_text(encoding="utf-8")
        self.assertIn("runreport.read(rd.must, run_id)", bridge)
        self.assertIn("runreport.read(rd.must, run_id)", server)

    def test_a_run_still_under_way_has_no_report_card(self):
        fetch, _ = _fetcher()
        report = runreport.read(fetch, 412)
        report["ended"] = False
        rows = [
            {
                "id": 2,
                "family": "Ugga",
                "run_id": 412,
                "campaign_id": 7,
                "run_number": 3,
                "phase": "INSIDE",
                "kind": "phase",
                "detail": "FORMING -> INSIDE",
                "age_seconds": 100,
            }
        ]
        payload = runtimeline.build_run_timeline(
            rows, {"Ugga": ["Ugga"]}, reports={412: report}
        )
        self.assertNotIn("report", payload["families"][0]["runs"][0])


def _post_run_reports():
    """Bridge._post_run_reports, compiled out of bridge.py's source."""
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    bridge = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Bridge"
    )
    fn = next(
        n
        for n in bridge.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_post_run_reports"
    )
    return textwrap.dedent(
        ast.get_source_segment(BRIDGE.read_text(encoding="utf-8"), fn)
    )


class OneDiscordMessagePerEndedRun(unittest.TestCase):
    def _harness(self, owed, send_fails=False, unreadable=(), owed_fails=None):
        marked: list = []
        sent: list = []
        self.warnings: list = []
        self.infos: list = []
        fetch, _ = _fetcher()

        async def to_thread(fn, *args):
            return fn(*args)

        class Channel:
            async def send(self, text):
                if send_fails:
                    raise RuntimeError("discord said no")
                sent.append(text)
                return types.SimpleNamespace(id=900 + len(sent))

        def read(run_id):
            if run_id in unreadable:
                raise realmread.Gap(1146, "SELECT ...")
            return runreport.read(fetch, run_id)

        state = {"owed": list(owed), "owed_fails": owed_fails}

        def fetch_owed():
            if state["owed_fails"]:
                raise state["owed_fails"]
            # The marker is what takes a run off the owed list.
            return [r for r in state["owed"] if r not in {m[0] for m in marked}]

        ns = {
            "asyncio": types.SimpleNamespace(to_thread=to_thread),
            "runreport": runreport,
            "log": types.SimpleNamespace(
                info=lambda *a: self.infos.append(a),
                warning=lambda *a: self.warnings.append(a),
            ),
            "_fetch_owed_run_reports": fetch_owed,
            "_read_run_report": read,
            "_mark_run_reported": lambda run_id, message_id, outcome: marked.append(
                (run_id, message_id)
            ),
        }
        exec(_post_run_reports(), ns)  # noqa: S102 - bridge.py's own source
        bot = types.SimpleNamespace(
            get_channel=lambda channel_id: Channel(),
            _unreadable_runs=set(),
            _run_reports_down=False,
        )
        self.state = state
        return ns["_post_run_reports"], bot, sent, marked

    def test_an_ended_run_is_posted_once_with_its_run_id_and_marked_after(self):
        post, bot, sent, marked = self._harness([412])
        self.assertEqual(1, asyncio.run(post(bot, 1)))
        self.assertEqual(0, asyncio.run(post(bot, 1)))
        self.assertEqual(1, len(sent))
        self.assertTrue(sent[0].startswith("Run report #412:"))
        self.assertEqual([(412, 901)], marked)

    def test_a_failed_send_marks_nothing_so_the_next_tick_retries(self):
        post, bot, sent, marked = self._harness([412], send_fails=True)
        with self.assertRaises(RuntimeError):
            asyncio.run(post(bot, 1))
        self.assertEqual([], marked)

    def test_an_unreadable_run_does_not_hold_the_runs_behind_it(self):
        # #1602: one run whose read fails is skipped, the next is posted.
        post, bot, sent, marked = self._harness([411, 412], unreadable={411})
        self.assertEqual(1, asyncio.run(post(bot, 1)))
        self.assertEqual([(412, 901)], marked)
        self.assertTrue(sent[0].startswith("Run report #412:"))

    def test_an_unreadable_run_is_logged_once_not_every_tick(self):
        post, bot, sent, marked = self._harness([411], unreadable={411})
        for _ in range(3):
            self.assertEqual(0, asyncio.run(post(bot, 1)))
        self.assertEqual([], marked)
        self.assertEqual(1, len(self.warnings))
        self.assertEqual(411, self.warnings[0][1])

    def test_a_failed_owed_read_logs_once_when_it_starts_and_once_when_it_clears(
        self,
    ):
        post, bot, sent, marked = self._harness(
            [412], owed_fails=ConnectionError("lost connection")
        )
        for _ in range(3):
            self.assertEqual(0, asyncio.run(post(bot, 1)))
        self.assertEqual(1, len(self.warnings))
        self.state["owed_fails"] = None
        self.assertEqual(1, asyncio.run(post(bot, 1)))
        self.assertEqual(1, len([a for a in self.infos if "again" in a[0]]))

    def test_the_owed_read_skips_reported_runs_and_old_history(self):
        sql = runreport.PENDING_SQL
        self.assertIn("p.run_id IS NULL", sql)
        self.assertIn("r.state = 'ended'", sql)
        self.assertIn("INTERVAL %s MINUTE", sql)

    def test_the_poll_is_well_inside_the_sixty_second_promise(self):
        src = BRIDGE.read_text(encoding="utf-8")
        self.assertIn(
            'RUN_REPORT_SECONDS = float(os.environ.get("RUN_REPORT_SECONDS", "20"))',
            src,
        )
        self.assertIn('_Pass("_run_report_loop", headless=False)', src)


if __name__ == "__main__":
    unittest.main()
