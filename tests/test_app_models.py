"""The app's read models: one module per payload the views share, and the one
clock they all read time in.

app/models/time.js reads every timestamp the server sends (unix seconds, or
the realm database's zoneless UTC text) as unix seconds, the one unit the
app works in. readState() in app/ui.js decides what state a read is in, for
pendingRead and the models alike. Each other module turns one endpoint's
payload into named accessors:

    roster.js     /api/v2/roster
    guildruns.js  /api/guildruns
    wall.js       /api/wall
    guild.js      /api/v2/guild

They are run under node through test_app_shell's runner, from canned
payloads, and their answers are checked against worked examples.
"""

import json
import shutil
import unittest

from test_app_shell import node_module

NODE = unittest.skipUnless(
    shutil.which("node"), "node is needed to run the app's modules"
)

# 2026-10-09 20:12:04 UTC, worked out apart from the app (calendar.timegm).
T = 1791576724
DB = "2026-10-09 20:12:04"


def run(module, script):
    return node_module(
        "models/" + module, "console.log(JSON.stringify(" + script + "));"
    )


@NODE
class TheClock(unittest.TestCase):
    def test_every_form_the_server_sends_reads_as_the_same_second(self):
        got = run(
            "time.js",
            '[M.toSeconds(%d), M.toSeconds("%s"), M.toSeconds("2026-10-09T20:12:04Z"),'
            ' M.toSeconds("2026-10-09T22:12:04+02:00"), M.toSeconds("2026-10-09T22:12:04+0200")]'
            % (T, DB),
        )
        self.assertEqual(got, [T] * 5)

    def test_nothing_or_nonsense_is_no_time(self):
        got = run(
            "time.js",
            '[M.toSeconds(null), M.toSeconds(undefined), M.toSeconds(""),'
            ' M.toSeconds("not a time"), M.toSeconds(NaN)]',
        )
        self.assertEqual(got, [None] * 5)

    def test_the_browsers_milliseconds_become_seconds(self):
        got = run(
            "time.js",
            "[M.fromClock(%d), M.fromClock(0), M.fromClock(null), M.fromClock(undefined)]"
            % (T * 1000),
        )
        self.assertEqual(got, [T, None, None, None])

    def test_an_age_is_counted_from_the_clock_given(self):
        got = run(
            "time.js",
            '[M.ageOf(%d, %d), M.ageOf("%s", %d), M.ageOf(%d, %d), M.ageOf(null, %d)]'
            % (T, T + 90, DB, T + 3600, T + 60, T, T),
        )
        # A time ahead of the clock is no age at all, never a negative one.
        self.assertEqual(got, [90, 3600, 0, None])

    def test_since_says_how_long_ago_or_not_measured(self):
        got = run(
            "time.js",
            '[M.since(%d, %d), M.since("%s", %d), M.since(null, %d), M.since("", %d),'
            " M.since(%d, %d)]" % (T, T + 42, DB, T + 7200, T, T, T + 5, T),
        )
        self.assertEqual(
            got, ["42s ago", "2h ago", "not measured", "not measured", "0s ago"]
        )

    def test_since_reads_the_real_clock_by_default(self):
        got = run("time.js", "[M.since(M.nowSeconds() - 120), M.nowSeconds() > %d]" % T)
        self.assertEqual(got, ["2m ago", True])

    def test_a_clock_time_is_hours_and_minutes_or_nothing(self):
        got = run(
            "time.js",
            '[M.clock(null), M.clock(""), M.clock(%d), M.clock("%s")]' % (T, DB),
        )
        self.assertEqual(got[:2], ["", ""])
        self.assertRegex(got[2], r"^\d\d:\d\d")
        self.assertEqual(got[2], got[3])


@NODE
class TheReadState(unittest.TestCase):
    def test_a_read_is_loading_failed_refused_or_ready(self):
        got = node_module(
            "ui.js",
            "console.log(JSON.stringify([undefined, {data: undefined, error: null}, {data: undefined, error: {}},"
            " {data: null, error: null}, {data: {error: 'no such guild'}, error: null},"
            " {data: {members: []}, error: null}, {data: [], error: null},"
            " {data: {members: []}, error: {}}].map((r) => [M.readState(r), M.ready(r)])));",
        )
        self.assertEqual(
            got,
            [
                ["loading", False],
                ["loading", False],
                ["failed", False],
                ["refused", False],
                ["refused", False],
                ["ready", True],
                ["ready", True],
                # An answer held from before a failed poll is still drawn.
                ["ready", True],
            ],
        )

    def test_pending_read_draws_from_the_same_decision(self):
        got = node_module(
            "ui.js",
            "console.log(JSON.stringify([{data: undefined, error: null}, {data: undefined, error: {}},"
            " {data: null, error: null}, {data: {error: 'x'}, error: null}, {data: {}, error: null}]"
            ".map((r) => { const w = M.pendingRead(r, 1); return w === null ? null : /data-kind=\"error\"/.test(String(w)) ? 'error' : 'skeleton'; })));",
        )
        self.assertEqual(got, ["skeleton", "error", None, None, None])


def ready(data):
    return "{data: %s, at: 1, error: null}" % json.dumps(data)


LOADING = "{data: undefined, at: 0, error: null}"
REFUSED = ready({"error": "the realm is restarting"})


def row(name, **kw):
    out = {
        "name": name,
        "guild": "Cave",
        "level": 20,
        "online": False,
        "life": "alive",
        "stuck": False,
        "since": None,
    }
    out.update(kw)
    return out


ROSTER = {
    "checked_at": T,
    "members": [
        row("Grug", stuck=True, since=T - 5400, online=True),
        row("Ugga", life="ghost"),
        row("Oz", life="dead", guild="Bonkers"),
        row("Zug", guild="Bonkers", online=True),
        row("Bork", stuck=True),
    ],
}


@NODE
class TheRoster(unittest.TestCase):
    def test_a_member_is_ghost_stuck_online_or_offline(self):
        got = run(
            "roster.js",
            "[M.stateOf(null), M.stateOf({life: 'dead', stuck: true}), M.stateOf({life: 'ghost'}),"
            " M.stateOf({stuck: true, online: true}), M.stateOf({online: true}), M.stateOf({online: false})]",
        )
        self.assertEqual(
            got, ["offline", "ghost", "ghost", "stuck", "online", "offline"]
        )

    def test_stuck_for_counts_from_the_rosters_own_clock(self):
        got = run(
            "roster.js",
            "[M.stuckFor({stuck: true, since: %d}, %d), M.stuckFor({stuck: true, since: null}, %d),"
            " M.stuckFor({stuck: true, since: %d}, null), M.stuckFor({stuck: false, since: %d}, %d), M.stuckFor(null, %d)]"
            % (T - 5400, T, T, T, T - 60, T, T),
        )
        self.assertEqual(got, ["1h 30m", None, None, None, None])

    def test_by_name_skips_rows_without_one(self):
        got = run(
            "roster.js",
            "[...M.byName([{name: 'Grug'}, null, {}, {name: 'Zug'}]).keys(), M.byName(undefined).size]",
        )
        self.assertEqual(got, ["Grug", "Zug", 0])

    def test_a_ready_roster_names_its_members_and_its_clock(self):
        got = run(
            "roster.js",
            "(() => { const r = M.roster(%s); return [r.ready, r.members.length, r.checkedAt,"
            " r.member('Zug').guild, r.member('Nobody'), r.has('Oz'), r.has('Nobody')]; })()"
            % ready(ROSTER),
        )
        self.assertEqual(got, [True, 5, T, "Bonkers", None, True, False])

    def test_ghosts_are_the_dead_and_the_released(self):
        got = run(
            "roster.js",
            "(() => { const r = M.roster(%s); return [r.ghosts().map((m) => m.name), [...r.ghostNames()]]; })()"
            % ready(ROSTER),
        )
        self.assertEqual(got, [["Ugga", "Oz"], ["Ugga", "Oz"]])

    def test_ghosts_are_not_measured_when_no_life_was_read(self):
        blind = {
            "checked_at": T,
            "members": [{"name": "Grug", "life": None}, {"name": "Zug"}],
        }
        got = run(
            "roster.js",
            "[%s, %s, %s].map((x) => { const r = M.roster(x); return [r.ghosts(), r.ghostNames().size]; })"
            % (ready(blind), LOADING, REFUSED),
        )
        self.assertEqual(got, [[None, 0], [None, 0], [None, 0]])

    def test_a_guilds_members_or_not_measured(self):
        got = run(
            "roster.js",
            "[M.roster(%s).inGuild('Bonkers').map((m) => m.name), M.roster(%s).inGuild('Cave'), M.roster(%s).inGuild('Cave')]"
            % (ready(ROSTER), LOADING, REFUSED),
        )
        self.assertEqual(got, [["Oz", "Zug"], None, None])

    def test_a_roster_not_in_yet_holds_nobody(self):
        got = run(
            "roster.js",
            "[%s, %s].map((x) => { const r = M.roster(x); return [r.ready, r.members, r.checkedAt, r.member('Grug'), r.has('Grug')]; })"
            % (LOADING, REFUSED),
        )
        self.assertEqual(got, [[False, [], None, None, False]] * 2)


def run_row(rid, **kw):
    out = {
        "id": rid,
        "guild": "Cave",
        "place": "The Deadmines",
        "state": "done",
        "created_at": None,
        "ended_at": None,
    }
    out.update(kw)
    return out


RUNS = {
    "active": [
        run_row(
            515, run_state="inside", state="queued", created_at="2026-10-09 20:00:00"
        ),
        # The old fields say inside; run_state (guildrun.run_state) says not.
        run_row(
            514,
            run_state="queued",
            state="inside",
            status="inside",
            created_at="2026-10-09 19:00:00",
        ),
    ],
    "recent": [
        run_row(512, outcome="cleared", created_at="2026-10-09 18:00:00", ended_at=DB),
        run_row(
            509,
            outcome="wiped",
            created_at="2026-10-08 10:00:00",
            ended_at="2026-10-08 11:00:00",
        ),
    ],
}


@NODE
class TheGuildRuns(unittest.TestCase):
    def test_both_lists_are_one_list_and_a_run_is_found_by_id(self):
        got = run(
            "guildruns.js",
            "(() => { const g = M.guildRuns(%s); return [g.ready, g.all.map((r) => r.id), g.active.length, g.recent.length,"
            " g.find('512').outcome, g.find(509).outcome, g.find(1)]; })()"
            % ready(RUNS),
        )
        self.assertEqual(
            got, [True, [515, 514, 512, 509], 2, 2, "cleared", "wiped", None]
        )

    def test_runs_inside_are_the_active_ones_inside(self):
        got = run(
            "guildruns.js",
            "[%s, %s, %s].map((x) => { const r = M.guildRuns(x).insideNow(); return r && r.map((r) => r.id); })"
            % (ready(RUNS), LOADING, REFUSED),
        )
        self.assertEqual(got, [[515], None, None])

    def test_new_since_counts_runs_formed_or_back_after_a_second(self):
        # 515 formed 20:00, 512 came back 20:12:04; 514 formed 19:00.
        got = run(
            "guildruns.js",
            "(() => { const g = M.guildRuns(%s); return [g.newSince(%d), g.newSince(%d), g.newSince(%d), g.newSince(null),"
            " M.guildRuns(%s).newSince(%d)]; })()"
            % (ready(RUNS), T - 13 * 60, T - 60 * 60 - 13 * 60, T, LOADING, T),
        )
        self.assertEqual(got, [2, 3, 0, None, None])

    def test_a_runs_times_are_seconds(self):
        got = run(
            "guildruns.js",
            "[%s].map((r) => [M.formedAt(r), M.endedAt(r), M.lastAt(r)]).concat([%s].map((r) => [M.formedAt(r), M.endedAt(r), M.lastAt(r)]))"
            % (json.dumps(RUNS["recent"][0]), json.dumps(RUNS["active"][0])),
        )
        self.assertEqual(
            got,
            [
                [T - 2 * 3600 - 12 * 60 - 4, T, T],
                [T - 12 * 60 - 4, None, T - 12 * 60 - 4],
            ],
        )

    def test_the_boss_line_says_what_was_measured(self):
        got = run(
            "guildruns.js",
            "[{outcome: 'refused', seconds_inside: 0, bosses_total: 0}, {outcome: 'not entered', bosses_total: 0},"
            " {outcome: 'wiped', seconds_inside: 900, bosses_total: 0}, {outcome: 'refused', seconds_inside: 30},"
            " {bosses_done: 2, bosses_total: 5}, {bosses_total: 5}].map(M.bossText)",
        )
        self.assertEqual(
            got,
            [
                "never went in",
                "never went in",
                "bosses not measured",
                "bosses not measured",
                "2 of 5 bosses down",
                "0 of 5 bosses down",
            ],
        )

    def test_why_it_went_and_why_it_came_back(self):
        got = run(
            "guildruns.js",
            "[M.chose({lines: ['dungeon: Deadmines, the median level fits', 'Formed at 20:00', 'group: two healers']}),"
            " M.chose({}), M.cause({cause: 'Cause: the tank died'}), M.cause({why: 'out of time'}), M.cause({})]",
        )
        self.assertEqual(
            got,
            [
                "dungeon: Deadmines, the median level fits. group: two healers",
                "",
                "the tank died",
                "out of time",
                "",
            ],
        )


WALL = {
    "members": [
        {"name": "Ugga", "family": "Grug"},
        {"name": "Grug", "family": "Grug"},
        {"name": "Oz", "family": "Zug", "leader": True},
        {"name": "Bigzug", "family": "Zug"},
        {"name": "Lone", "family": "Mog"},
        {"name": "Drifter"},
    ],
    "wall": {"tiles": [{"name": "Grug", "url": "https://example.com/grug"}]},
}


@NODE
class TheWall(unittest.TestCase):
    def test_members_are_grouped_by_family(self):
        got = run(
            "wall.js",
            "[...M.wall(%s).families()].map(([k, v]) => [k, v.map((m) => m.name)])"
            % ready(WALL),
        )
        self.assertEqual(
            got,
            [
                ["Grug", ["Ugga", "Grug"]],
                ["Zug", ["Oz", "Bigzug"]],
                ["Mog", ["Lone"]],
                ["", ["Drifter"]],
            ],
        )

    def test_the_head_is_named_like_the_family_else_its_leader_else_the_first(self):
        got = run(
            "wall.js",
            "(() => { const w = M.wall(%s); return [w.head('Grug').name, w.head('Zug').name, w.head('Mog').name, w.head('Nobody')]; })()"
            % ready(WALL),
        )
        self.assertEqual(got, ["Grug", "Oz", "Lone", None])

    def test_heads_skip_a_family_with_nobody_and_are_not_measured_unread(self):
        got = run(
            "wall.js",
            "[M.wall(%s).heads(['Grug', 'Nobody', 'Zug']).map((m) => m.name), M.wall(%s).heads(['Grug']), M.wall(%s).heads(['Grug'])]"
            % (ready(WALL), LOADING, REFUSED),
        )
        self.assertEqual(got, [["Grug", "Oz"], None, None])

    def test_a_tile_is_found_by_name(self):
        got = run(
            "wall.js",
            "[M.wall(%s).tile('Grug').url, M.wall(%s).tile('Oz'), M.wall(%s).tile('Grug'), M.wall(%s).tile('Grug')]"
            % (ready(WALL), ready(WALL), ready({"members": []}), LOADING),
        )
        self.assertEqual(got, ["https://example.com/grug", None, None, None])

    def test_head_of_reads_any_list_of_members(self):
        got = run(
            "wall.js",
            "[M.headOf([{name: 'A'}, {name: 'B', leader: true}], 'Zug').name, M.headOf([], 'Zug')]",
        )
        self.assertEqual(got, ["B", None])


GUILD = {
    "guild": "Cave",
    "members": [
        {"name": "Grug", "level": 23, "class": "Warrior"},
        {"name": "Ugga", "level": 18, "class": "Priest", "ghost": True},
        {"name": "Bork", "level": 20, "class": "Rogue"},
        {"name": "Grog", "level": 21, "class": "Mage", "ghost": True},
        {"name": "Fresh", "level": 0, "class": "Hunter"},
    ],
    "dungeons": [
        {"keyword": "rfc", "runs": 3},
        {"keyword": "wc", "runs": 0},
        {"keyword": "dm", "runs": 1},
    ],
}


@NODE
class TheGuild(unittest.TestCase):
    def test_the_median_is_the_upper_middle_level(self):
        got = run(
            "guild.js",
            "[M.guild(%s).medianLevel(), M.guild(%s).medianLevel(), M.guild(%s).medianLevel()]"
            % (ready(GUILD), ready({"members": []}), LOADING),
        )
        # Levels 0, 18, 20, 21, 23: the middle one is 20.
        self.assertEqual(got, [20, None, None])

    def test_the_level_spread_bins_two_levels_a_bar_without_the_unread(self):
        got = run("guild.js", "M.guild(%s).levelSpread()" % ready(GUILD))
        # Level 0 is no level read; 18, 20, 21, 23 have the median 21.
        self.assertEqual(
            got,
            {
                "lo": 18,
                "hi": 23,
                "median": 21,
                "bins": [
                    {"from": 18, "to": 19, "n": 1, "median": False},
                    {"from": 20, "to": 21, "n": 2, "median": True},
                    {"from": 22, "to": 23, "n": 1, "median": False},
                ],
            },
        )

    def test_an_odd_lowest_level_starts_its_even_bar(self):
        got = run(
            "guild.js",
            "M.guild(%s).levelSpread().bins.map((b) => [b.from, b.to, b.n])"
            % ready({"members": [{"level": 7}, {"level": 10}]}),
        )
        self.assertEqual(got, [[6, 7, 1], [8, 9, 0], [10, 11, 1]])

    def test_no_level_read_is_no_spread(self):
        got = run(
            "guild.js",
            "[M.guild(%s).levelSpread(), M.guild(%s).levelSpread()]"
            % (ready({"members": [{"level": 0}]}), LOADING),
        )
        self.assertEqual(got, [None, None])

    def test_ghosts_learned_dungeons_and_a_members_class(self):
        got = run(
            "guild.js",
            "(() => { const g = M.guild(%s); return [g.ghostsNow(), g.learned().map((d) => d.keyword), g.classOf('Bork'), g.classOf('Nobody') === undefined]; })()"
            % ready(GUILD),
        )
        self.assertEqual(got, [2, ["rfc", "dm"], "Rogue", True])


@NODE
class TheStuckList(unittest.TestCase):
    """/api/v2/stuck, read by the Now view: `since` is unix seconds."""

    def test_the_longest_wait_is_counted_from_the_earliest_since(self):
        got = node_module(
            "views/now/data.js",
            "const s = M.stuck(%s, %d); console.log(JSON.stringify([s.list.length, s.longest]));"
            % (
                ready(
                    {
                        "members": [
                            {"since": T - 60},
                            {"since": T - 600},
                            {"since": None},
                        ]
                    }
                ),
                T,
            ),
        )
        self.assertEqual(got, [3, 600])

    def test_no_known_since_is_no_longest_and_an_unread_list_is_none(self):
        got = node_module(
            "views/now/data.js",
            "console.log(JSON.stringify([M.stuck(%s, %d).longest, M.stuck(%s, %d), M.stuck(%s, %d), M.stuck(%s, %d)]));"
            % (
                ready({"members": [{"since": None}]}),
                T,
                LOADING,
                T,
                REFUSED,
                T,
                ready({"members": "x"}),
                T,
            ),
        )
        self.assertEqual(got, [None, None, None, None])


@NODE
class TheChronicleBadge(unittest.TestCase):
    """badges.js counts what is newer than the last visit, read by the clock."""

    def test_items_and_loot_newer_than_the_last_visit_are_counted(self):
        chronicle = {
            "guilds": ["Cave", "Bonkers"],
            "items": [
                {"guild": "Cave", "at": T + 60},
                {"guild": "Cave", "at": T - 60},
                {"guild": "Bonkers", "at": T + 1},
            ],
        }
        loot = {
            "stories": [
                {"guild": "Cave", "at": "2026-10-09 20:13:04"},
                {"guild": "Cave", "at": "2026-10-09 20:11:04"},
                {"guild": "Cave", "at": None},
                {"guild": "Elsewhere", "at": "2026-10-09 20:13:04"},
            ]
        }
        got = node_module(
            "badges.js",
            "const reads = {'/api/v2/chronicle': %s, '/api/loot': %s};"
            " const p = M.default.find((b) => b.section === 'guilds');"
            " const get = (path) => ({data: reads[path]});"
            " console.log(JSON.stringify([p.compute(get, {previousVisit: %d}), p.compute(get, {previousVisit: 0})]));"
            % (json.dumps(chronicle), json.dumps(loot), T * 1000),
        )
        self.assertEqual(
            got,
            [
                {
                    "n": 3,
                    "tone": "accent",
                    "label": "3 new in the chronicle since your last visit",
                    "href": "#/guilds/cave/chronicle",
                },
                None,
            ],
        )


if __name__ == "__main__":
    unittest.main()
