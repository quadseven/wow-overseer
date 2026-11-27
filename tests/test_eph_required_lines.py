"""A decree that requires a log line is pinned to the code that writes the line.

Since #2767 a log check can require a line (`at_least`) or cap one (`at_most`).
A pattern that no code emits makes such a check useless in the worst way: a
required line that is never written fails every run, and a capped line that is
never written passes every run. So every bounded log check in a shipped decree
is listed here beside the format string of each call that writes its line, and:

- the format string must still be in the pinned source, at that level and on
  that logger, so a reworded line turns this file red before it turns a
  proving run red;
- the line must reach a log the judge reads, at a level that keeps it: the
  file appender that `submit.BASELINE` adds for a module or playerbots line,
  and the bridge sidecar's log (read on a bridge-on decree only, see
  `judge.log_reader`) for a bridge line;
- the pattern must match the line as the source formats it, and must not match
  the sibling line the same code writes when the thing did not happen.

The pinned sources are the mod-overseer submodule at its pinned commit, the
test copies of the playerbots patches under patches/, and the bridge
(bridge.py and the modules it formats with). A bounded check whose line is
written by none of them (a core line, a dungeon module line, or a module line
from a commit newer than the pin) is listed in UNPINNABLE with that reason, so
a new check is either pinned or named there, never silently neither.
Decrees whose header still says a criterion was narrowed are listed in
STILL_NARROWED.
"""

import pathlib
import re
import unittest
import tempfile
from typing import NamedTuple

import flightlearn
import modsource
from ephemeral import judge, lint, podpaths, submit
from ephemeral.miniyaml import loads

ROOT = pathlib.Path(__file__).resolve().parent.parent
DECREE_DIR = ROOT / "data" / "decrees"
BRIDGE = ROOT / "bridge.py"
REFLECT_PATCH = (
    ROOT
    / "patches"
    / "mod-playerbots"
    / "0017-casters-hold-on-a-majordomo-add-with-magic-reflection.patch"
)

# The core's log levels, as the `Logger.<name>` config value counts them.
LEVELS = {"FATAL": 1, "ERROR": 2, "WARN": 3, "INFO": 4, "DEBUG": 5, "TRACE": 6}
# The bridge's `log.<method>` calls, by the same names.
PY_LEVELS = {
    "critical": "FATAL",
    "error": "ERROR",
    "warning": "WARN",
    "info": "INFO",
    "debug": "DEBUG",
}

_LITERAL = r'"(?:[^"\\\n]|\\.)*"'
_CALL = re.compile(
    r"LOG_(" + "|".join(LEVELS) + r")\(\s*(" + _LITERAL + r")\s*,\s*"
    r"((?:" + _LITERAL + r"\s*)+)"
)
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def log_calls(text):
    """Every (level, logger, format) a C++ source logs with a literal format.

    Adjacent string literals are one string to the compiler, so they are joined
    here too: the source wraps a format over several lines wherever it likes.
    """
    found = set()
    for m in _CALL.finditer(text):
        fmt = "".join(s[1:-1] for s in re.findall(_LITERAL, m.group(3)))
        found.add((m.group(1), m.group(2)[1:-1], fmt))
    return found


_PY_CALL = re.compile(
    r"\blog\.(" + "|".join(PY_LEVELS) + r")\(\s*((?:" + _LITERAL + r"\s*)+)"
)


def bridge_log_calls(text):
    """Every (level, logger, format) the bridge logs with a literal format on its `log`.

    `log` is the bridge's one module logger; the test that reads bridge.py
    checks that it is still `logging.getLogger("wow-overseer")`.
    """
    found = set()
    for m in _PY_CALL.finditer(text):
        fmt = "".join(s[1:-1] for s in re.findall(_LITERAL, m.group(2)))
        found.add((PY_LEVELS[m.group(1)], "wow-overseer", fmt))
    return found


def patch_added_text(text):
    """The lines a patch adds, without their leading plus sign."""
    return "\n".join(
        line[1:]
        for line in text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


class Line(NamedTuple):
    """One logging call: where it is, what it formats, and sample arguments."""

    source: str  # "module", "reflect-patch" or "bridge"
    level: str
    logger: str
    fmt: str
    args: tuple

    def rendered(self):
        if self.source == "bridge":
            return self.fmt % self.args  # the bridge formats %-style
        holes = _PLACEHOLDER.findall(self.fmt)
        if len(holes) != len(self.args):
            raise AssertionError(
                f"{len(holes)} placeholders but {len(self.args)} sample arguments: {self.fmt}"
            )
        values = iter(self.args)
        return _PLACEHOLDER.sub(lambda _m: str(next(values)), self.fmt)


def module(level, fmt, *args):
    return Line("module", level, "module.overseer", fmt, args)


def bridge(level, fmt, *args):
    return Line("bridge", level, "wow-overseer", fmt, args)


class Pin(NamedTuple):
    """The calls that write a check's line, and the sibling lines it must ignore."""

    writers: tuple
    ignores: tuple = ()


SHIP = "Ship (The Lady Mehley)"
NOT_READ = "its way across was not read"
PARTY_SPLIT = (
    "overseer: '{}' is on map {} and its leader '{}' is on map {} - THE "
    "PARTY IS SPLIT ACROSS TWO MAPS AND THIS MEMBER IS NOT CROSSING: {}. "
    "`follow` cannot cross a map and an `at:` aim cannot name a coordinate "
    "on another one, so following, a catch-up walk, an escort and a WALKED "
    "dungeon run are blocked for it until it crosses; a run by the dungeon "
    "finder is not, because the finder takes a family in from wherever each "
    "member stands (Overseer.DungeonFinder.Default). AN ERRAND IT CAN RUN "
    "ALONE ON THIS MAP IS NOT BLOCKED EITHER: it may still be sent to an "
    "innkeeper, a vendor, a repairer or a trainer under its own aim, and "
    "binding at an innkeeper on its leader's continent is what lets its "
    "hearthstone bring it back (#241, #274, #289)"
)
BARRIER_SATISFIED = (
    "overseer: dungeon run BARRIER satisfied - all {} roster members "
    "alive, out of combat and within {:.0f}y of the staging point{}. ENTER "
    "takes them the last {}y to areatrigger {} and knocks for all of "
    "them at once, followers first and the leader last"
)
BARRIER_HOLDS = "overseer: dungeon run BARRIER holds - {}"
RUN_OVER = (
    "overseer: all {} roster members came back out through "
    "areatrigger {} and are on map {} - the run is over"
)


def flight_report(**errand):
    """The second argument of the bridge's flight line, as flightlearn writes it."""
    return flightlearn.report(flightlearn.Errand(**errand))


# (decree id, observation name) -> the code that writes the line.
PINS = {
    ("majordomo-reflect-hold", "casters-held-on-a-magic-reflection-add"): Pin(
        writers=(
            Line(
                "reflect-patch",
                "INFO",
                "playerbots",
                "[MC] majordomo: {} casters holding, magic reflection on {}",
                (3, "Flamewaker Healer"),
            ),
        ),
    ),
    (
        "raid-durability-before-each-boss",
        "the-lowest-durability-was-logged-before-an-encounter",
    ): Pin(
        writers=(
            module(
                "INFO",
                "overseer: raid run for family '{}': lowest durability {} {}%; "
                "{} seat(s) under the {}% floor (before encounter {})",
                "Grug",
                "Ugga",
                61,
                0,
                30,
                1,
            ),
        ),
        ignores=(
            module(
                "WARN",
                "overseer: raid run for family '{}': cannot log pre-pull "
                "durability for encounter {} - no readable seats",
                "Grug",
                1,
            ),
            module(
                "INFO",
                "overseer: raid run for family '{}' repair walk for '{}' - "
                "lowest durability {}%, floor {}%",
                "Grug",
                "Ugga",
                12,
                30,
            ),
        ),
    ),
    ("raid-straggler-summon-at-stone", "the-straggler-summon-was-logged"): Pin(
        writers=(
            module(
                "INFO",
                "overseer: raid run for family '{}' summons '{}' at the {} stone - '{}' "
                "clicks stone {} (minimum level {}) with '{}' on the portal, try {} of {}; "
                "the kind='summon' row carries source '{}'",
                "Grug",
                "Zug",
                "Blackrock Mountain",
                "Workwork",
                179585,
                48,
                "Ugga",
                1,
                3,
                "raid_stone summon Zug t1 1763400000",
            ),
        ),
    ),
    ("raid-straggler-summon-at-stone", "the-straggler-was-read-back-at-the-stone"): Pin(
        writers=(
            module(
                "INFO",
                "overseer: raid run for family '{}' - '{}' was summoned to the {} "
                "stone {} by '{}' and reads back on map {} at ({:.1f}, {:.1f}, "
                "{:.1f}), {:.0f}y from {}'s staging point",
                "Grug",
                "Zug",
                "Blackrock Mountain",
                179585,
                "Workwork",
                0,
                "-7524.2",
                "-1228.4",
                "285.7",
                "38",
                "Molten Core",
            ),
        ),
        ignores=(
            module(
                "WARN",
                "overseer: raid run for family '{}' - the summon of '{}' at the {} "
                "stone {} by '{}' did not bring it ({}); try {} of {}",
                "Grug",
                "Zug",
                "Blackrock Mountain",
                179585,
                "Workwork",
                "no verdict within 90s",
                1,
                3,
            ),
        ),
    ),
    ("ubrs-ten-seat-run", "the-dungeon-brain-was-accepted-in-the-spire"): Pin(
        writers=(
            module(
                "INFO",
                "overseer: '{}' is inside map {} (run {}) - issuing 'dc on' as '{}': accepted{}",
                "Ugga",
                229,
                4,
                "Grug",
                "",
            ),
        ),
        ignores=(
            module(
                "WARN",
                "overseer: '{}' is inside map {} (run {}) - issuing 'dc on' as "
                "'{}': REFUSED (DcOnAction returned false). The reason is in the "
                "dungeon module's own log under 'DC command refused for {}'; "
                "retrying every {}s and staying quiet until it takes",
                "Ugga",
                229,
                4,
                "Grug",
                "Ugga",
                60,
            ),
            module(
                "INFO",
                "overseer: '{}' is inside raid map {} - the dungeon brain is "
                "held off until the family's raid run is in CLEAR; the raid "
                "holds where it stands",
                "Ugga",
                229,
            ),
        ),
    ),
    (
        "aimed-quest-complete-handin",
        "the-complete-quest-was-handed-in-to-its-taker",
    ): Pin(
        writers=(
            module(
                "INFO",
                "overseer: '{}' handed chosen quest {} ({}) in to '{}' at {:.1f} yards",
                "Ugga",
                783,
                "A Threat Within",
                "Marshal McBride",
                "3.2",
            ),
        ),
        ignores=(
            module(
                "WARN",
                "overseer: '{}' tried to hand in chosen quest {} ({}) to '{}' and "
                "the core did not record the reward (status {})",
                "Ugga",
                783,
                "A Threat Within",
                "Marshal McBride",
                1,
            ),
        ),
    ),
    (
        "aimed-quest-complete-handin",
        "quest-reissues-stay-in-single-figures-over-the-observation",
    ): Pin(
        writers=(
            module(
                "INFO",
                "overseer: '{}' was already on quest {} ({}) by its own choice - "
                "re-issuing for the new errand so the objective pointer resets",
                "Ugga",
                783,
                "A Threat Within",
            ),
        ),
    ),
    ("dungeon-member-leaves-and-rejoins", "stranded-rejoin-poll-was-logged"): Pin(
        writers=(
            module(
                "INFO",
                "overseer: dungeon run {} knocked on areatrigger {} for the {} "
                "stranded outside map {} - {} went back in this poll and the census "
                "is that much nearer complete",
                1,
                288,
                2,
                0,
                1,
            ),
        ),
    ),
    ("stratholme-exit-yard", "the-way-out-was-logged"): Pin(
        writers=(
            module(
                "INFO",
                "overseer: stratholme exit: door {}, way out {}",
                "closed",
                "button",
            ),
            module(
                "INFO",
                "overseer: stratholme exit: door {}, way out {}",
                "closed",
                "hearth",
            ),
            module(
                "INFO", "overseer: stratholme exit: door {}, way out {}", "open", "walk"
            ),
        ),
        ignores=(
            # No way out found is the same call with the word for no way.
            module(
                "INFO",
                "overseer: stratholme exit: door {}, way out {}",
                "closed",
                "none",
            ),
            module(
                "WARN",
                "overseer: stratholme exit: {} of '{}' still in the yard after {} "
                "minutes; the way out gives up and the ordinary drives take them",
                5,
                "Grug",
                20,
            ),
        ),
    ),
    (
        "gnomeregan-exit-hearth-on-cooldown",
        "the-lethal-road-was-refused-or-hearthed",
    ): Pin(
        writers=(
            module(
                "WARN",
                "overseer: '{}' is sent to '{}', {} yards off, and no flight "
                "carried it. The road it was planned along crosses {} unbroken "
                "yards of ground holding creatures ten or more levels above its "
                "party's youngest member (worst {}), so it is not walked - {} "
                "(#836)",
                "Grug",
                "Innkeeper Allison",
                1840,
                620,
                52,
                "it waits for its hearthstone",
            ),
            module(
                "WARN",
                "overseer: '{}' hearths to its bind beside '{}' instead "
                "of walking the road there (#836)",
                "Grug",
                "Innkeeper Allison",
            ),
        ),
        ignores=(
            # The lone-leg hearth of another ticket is not this trip's road check.
            module(
                "WARN",
                "overseer: '{}' hearths to its bind beside the family "
                "instead of walking the leg that {} (#697)",
                "Grug",
                "crosses a zone far above it",
            ),
        ),
    ),
    ("leader-boards-lady-mehley", "the-leader-stepped-aboard"): Pin(
        writers=(
            module(
                "INFO",
                "overseer: '{}' steps aboard '{}' at ({:.1f}, {:.1f}, {:.1f}) on "
                "map {}, {:.1f} yards from where he stands and {:.1f} from the berth - {}",
                "Grug",
                SHIP,
                "-4018.2",
                "-4722.4",
                "6.2",
                1,
                "3.1",
                "2.4",
                "58s of its stop left",
            ),
        ),
        ignores=(
            module(
                "INFO",
                "overseer: '{}' is {:.1f} yards from the berth for '{}', more than "
                "the {:.0f} a step aboard is taken from, so he closes on it first ({}) - {}",
                "Grug",
                "13.3",
                SHIP,
                "4",
                "walking",
                "58s of its stop left",
            ),
        ),
    ),
    ("leader-boards-lady-mehley", "the-leader-was-aboard-between-the-maps"): Pin(
        writers=(
            module(
                "INFO",
                "overseer: the leader '{}' is aboard '{}' between maps {} and {} - {}",
                "Grug",
                SHIP,
                1,
                0,
                "it sails",
            ),
        ),
        ignores=(
            module(
                "WARN",
                "overseer: '{}' is aboard '{}' at its dock on map {} and there is "
                "no surveyed ground off its deck within {:.0f} yards of him, so he "
                "stays aboard - {}",
                "Grug",
                SHIP,
                0,
                "12",
                "it waits",
            ),
        ),
    ),
    ("cross-map-party-split-is-reported", "each-follower-reports-the-split"): Pin(
        writers=(module("ERROR", PARTY_SPLIT, "Ugga", 1, "Zug", 0, NOT_READ),),
        # The same call about a split the other way round is not this one.
        ignores=(module("ERROR", PARTY_SPLIT, "Ugga", 0, "Zug", 1, NOT_READ),),
    ),
    ("deadmines-early-entrant-barrier", "barrier-names-the-early-entrant"): Pin(
        writers=(
            module(
                "INFO", BARRIER_SATISFIED, 5, "10", " or inside already (Zork)", 4, 78
            ),
            # The holds line's text is DungeonRunBarrierHolds: the blockers, then
            # "inside already, counted as staged: <names>".
            module(
                "INFO",
                BARRIER_HOLDS,
                "Ugga (24y out); inside already, counted as staged: Zork",
            ),
        ),
        ignores=(
            # A member inside but dead is a blocker, not staged, and the
            # pattern wants the name after "inside already".
            module("INFO", BARRIER_HOLDS, "Zork (dead, inside already)"),
            module("INFO", BARRIER_SATISFIED, 5, "10", "", 4, 78),
            module("INFO", BARRIER_HOLDS, "Zork (not seen)"),
        ),
    ),
    (
        "long-dungeon-exits-count-walking-progress",
        "maraudon-party-walks-out-through-trigger-3131",
    ): Pin(
        writers=(module("INFO", RUN_OVER, 5, 3131, 0),),
        ignores=(module("INFO", RUN_OVER, 5, 288, 0),),
    ),
    (
        "long-dungeon-exits-count-walking-progress",
        "uldaman-party-walks-out-through-trigger-288",
    ): Pin(
        writers=(module("INFO", RUN_OVER, 5, 288, 0),),
        ignores=(module("INFO", RUN_OVER, 5, 3131, 0),),
    ),
    (
        "razorfen-downs-exits-and-restarts-together",
        "all-five-walk-out-through-trigger-444",
    ): Pin(
        writers=(module("INFO", RUN_OVER, 5, 444, 0),),
        ignores=(module("INFO", RUN_OVER, 4, 444, 0),),
    ),
    # A bridge line, read by the judge because the decree is bridge-on.
    ("family-learns-unknown-flight-node", "the-flight-pass-asked-for-node-forty"): Pin(
        writers=(
            bridge(
                "INFO",
                "flight: leader=%s - %s",
                "Zug",
                flight_report(
                    aim="Bulkrek Ragefist", node=40, node_name="Gadgetzan", yards=2210.0
                ),
            ),
            # A pass whose town slot was held still chose node 40, and the
            # pattern counts that line too. That the node was learned is the
            # decree's taximask check, not this one.
            bridge(
                "INFO",
                "flight: leader=%s could not be aimed at the flight master "
                "teaching taxi node %d this pass, so the family's flight "
                "network does not grow and the next long trip is another walk",
                "Zug",
                40,
            ),
        ),
        ignores=(
            # A refused errand is logged as its refusal sentence alone, and no
            # refusal in flightlearn names a taxi node.
            bridge(
                "INFO",
                "flight: leader=%s - %s",
                "Zug",
                flight_report(refused="no flight master the family lacks is in reach"),
            ),
            bridge(
                "INFO",
                "flight: taxi node %d waits for the family's bags - %s",
                40,
                "two seats are full",
            ),
            bridge(
                "INFO",
                "flight: leader=%s - %s",
                "Zug",
                flight_report(aim="Bragok", node=41, node_name="Ratchet", yards=900.0),
            ),
        ),
    ),
}

# Decrees whose header still says a criterion was narrowed for want of a
# positive log check, and why `at_least` does not restore it from this repo.
STILL_NARROWED = {
    # The line is bridge text. These decrees are bridge-on, and since #3062 the
    # judge reads the bridge sidecar's log on a bridge-on decree, so a pattern
    # pinned to the bridge call can now restore them; that is not done here.
    "guild-brd-keyed-wing": "bridge line, not yet restored",
    "raid-order-seats-arrive-at-door": "bridge line, not yet restored",
    "raid-prep-mail-and-bank-cycle": "bridge line, not yet restored",
    # The line is written by the dungeon module, whose source is not in this repo.
    "blackfathom-gelihast-stranded-rescue": "dungeon module source not here",
    "brd-ale-run-rested-party": "dungeon module source not here",
    "brd-paladin-without-redemption": "dungeon module source not here",
    "deadmines-gunpowder-no-opener": "dungeon module source not here",
    # The orders this decree gives are not the roster errands whose lines name
    # the recipe, so no emitter can be tied to what the decree does.
    "trainer-recipe-and-vendor-manual": "the act does not reach a pinned emitter",
    # Nothing was narrowed here: the criterion only forbids a line.
    "family-boat-crossing": "forbids a line only",
}


class Unpinnable(NamedTuple):
    """Why a bounded check has no emitter this file can read."""

    kind: str  # one of UNPINNABLE_KINDS
    why: str


# Each reason a bounded check cannot be pinned from this repo. A line the
# bridge writes is not one of them: the bridge's source is here, so it is pinned.
CORE = "core line"
DUNGEON_MODULE = "dungeon module line"
NEWER_MODULE = "module commit newer than the pin"
# No source here writes it, and the decree does not say which outside one does.
OUTSIDE = "core or playerbots line"
UNPINNABLE_KINDS = {CORE, DUNGEON_MODULE, NEWER_MODULE, OUTSIDE}

# Bounded log checks whose line no source in this repo writes. Each is named
# with its reason so a new unpinned check is a red test, not a silent one. A
# NEWER_MODULE entry names the mod-overseer commit that added the wording: pin
# it (and delete it here) when the submodule pin reaches that commit.
UNPINNABLE = {
    (
        "alliance-brd-campaign-home",
        "alliance-named-home-refusal-was-recorded",
    ): Unpinnable(NEWER_MODULE, "mod-overseer c85d8a8 (#1401)"),
    ("brd-core-fragment-chest", "the-run-logged-a-fragment-loot"): Unpinnable(
        NEWER_MODULE, "mod-overseer 64eb9ea (#1464)"
    ),
    (
        "brd-fineous-ironfel-pickup",
        "the-module-opened-fineous-corpse-for-ironfel",
    ): Unpinnable(NEWER_MODULE, "mod-overseer 134f5d5 (#1455)"),
    (
        "class-trainer-crosses-map-and-learns",
        "a-cross-map-class-trainer-walk-was-issued",
    ): Unpinnable(NEWER_MODULE, "mod-overseer fa16ae7 (#1586)"),
    (
        "cross-map-stranded-member-names-its-way",
        "each-follower-gets-the-bounded-reason-line",
    ): Unpinnable(NEWER_MODULE, "mod-overseer a68528d (#1369)"),
    (
        "ghost-healer-walk-hold-is-timed",
        "hostile-held-ghost-writes-timed-status",
    ): Unpinnable(NEWER_MODULE, "mod-overseer 40b1d97 (#1289)"),
    (
        "stratholme-yard-hearth-names-its-reason",
        "the-yard-hearth-line-names-the-yard",
    ): Unpinnable(NEWER_MODULE, "mod-overseer 1d7ab3e (#1280)"),
    # The core's entities.player and movement.motionmaster loggers. The decree
    # sends them to the Console and Server appenders, not to the EphModule file
    # the judge reads, so as written these checks can never find the line.
    ("fall-death-logger-capture", "fall-damage-debug-line-is-present"): Unpinnable(
        CORE, "FALLDAMAGE debug line of the core's entities.player logger"
    ),
    ("fall-death-logger-capture", "motionmaster-movefall-line-is-present"): Unpinnable(
        CORE, "MoveFall line of the core's movement.motionmaster logger"
    ),
    (
        "open-world-tank-avoids-out-of-range-melee",
        "casting-creature-fight-started",
    ): Unpinnable(
        OUTSIDE,
        "no call in the pinned module, the patches or the bridge writes a line "
        "naming Azuregos casting",
    ),
}
_NARROWED_WORDS = re.compile(
    r"can only forbid|cannot demand presence|cannot require|is an exact count"
)


def shipped_decrees():
    for path in sorted(DECREE_DIR.glob("*.yaml")):
        if path.name != "anchors.yaml":
            yield path, loads(path.read_text(encoding="utf-8"))


def bounded_checks():
    """(decree id, observation name) -> the log block, for every at_least or at_most."""
    found = {}
    for _path, decree in shipped_decrees():
        for o in decree.get("observe") or []:
            expect = (o.get("log") or {}).get("expect") or {}
            if any(key in expect for key in lint.LOG_RANGE_KEYS):
                found[(decree["id"], o["name"])] = o["log"]
    return found


class LogCallReaderTest(unittest.TestCase):
    SOURCE = """
        if (ok)
            LOG_INFO("module.overseer",
                     "overseer: '{}' was summoned to the {} "
                     "stone {} by '{}'",
                     name, stone, entry, clicker);
        else
            LOG_WARN("module.overseer", "overseer: no \\"stone\\" for '{}'", name);
    """

    def test_adjacent_literals_are_one_format(self):
        self.assertEqual(
            log_calls(self.SOURCE),
            {
                (
                    "INFO",
                    "module.overseer",
                    "overseer: '{}' was summoned to the {} stone {} by '{}'",
                ),
                ("WARN", "module.overseer", "overseer: no \\\"stone\\\" for '{}'"),
            },
        )

    def test_a_reworded_line_is_no_longer_found(self):
        want = (
            "INFO",
            "module.overseer",
            "overseer: '{}' was summoned to the {} stone {} by '{}'",
        )
        self.assertIn(want, log_calls(self.SOURCE))
        drifted = self.SOURCE.replace("was summoned to", "was called to")
        self.assertNotIn(want, log_calls(drifted))
        # The same words at another level or on another logger are not the line either.
        self.assertNotIn(want, log_calls(self.SOURCE.replace("LOG_INFO", "LOG_DEBUG")))
        self.assertNotIn(
            want, log_calls(self.SOURCE.replace('"module.overseer"', '"server"'))
        )

    def test_a_patch_is_read_by_the_lines_it_adds(self):
        patch = '--- a/x.cpp\n+++ b/x.cpp\n@@\n keep\n-    LOG_INFO("playerbots", "old {}", n);\n+    LOG_INFO("playerbots", "new {}", n);\n'
        self.assertEqual(
            log_calls(patch_added_text(patch)), {("INFO", "playerbots", "new {}")}
        )

    def test_a_rendered_line_fills_every_placeholder(self):
        line = module("INFO", "a {} b {:.1f} c", "x", "1.5")
        self.assertEqual(line.rendered(), "a x b 1.5 c")
        with self.assertRaises(AssertionError):
            module("INFO", "a {} b {}", "x").rendered()


def decrees_by_id():
    return {decree["id"]: decree for _path, decree in shipped_decrees()}


# The decrees this change restored: their criteria name the required line again.
RESTORED = {
    "aimed-quest-complete-handin",
    "dungeon-member-leaves-and-rejoins",
    "gnomeregan-exit-hearth-on-cooldown",
    "leader-boards-lady-mehley",
    "majordomo-reflect-hold",
    "raid-durability-before-each-boss",
    "raid-straggler-summon-at-stone",
    "stratholme-exit-yard",
    "ubrs-ten-seat-run",
}


class RequiredLinesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checks = bounded_checks()
        cls.decrees = decrees_by_id()
        cls.bridge_text = BRIDGE.read_text(encoding="utf-8")
        cls.calls = {
            "module": log_calls(modsource.read(modsource.MODULE, errors="replace")),
            "reflect-patch": log_calls(
                patch_added_text(REFLECT_PATCH.read_text(encoding="utf-8"))
            ),
            "bridge": bridge_log_calls(cls.bridge_text),
        }

    def lines(self):
        for key, pin in sorted(PINS.items()):
            for line in (*pin.writers, *pin.ignores):
                yield key, line

    def test_every_bounded_log_check_is_pinned_to_its_emitter(self):
        self.assertEqual(
            sorted(self.checks),
            sorted({*PINS, *UNPINNABLE}),
            "a log check with at_least or at_most needs an entry in PINS naming "
            "the call that writes its line, or in UNPINNABLE naming why no source "
            "here writes it (and a stale entry must go)",
        )
        self.assertFalse(set(PINS) & set(UNPINNABLE), "pinned and unpinnable at once")
        for key, reason in sorted(UNPINNABLE.items()):
            self.assertIn(reason.kind, UNPINNABLE_KINDS, key)
            self.assertTrue(reason.why.strip(), key)
        self.assertTrue(
            any("at_least" in c["expect"] for c in self.checks.values()),
            "no shipped decree requires a log line",
        )

    def test_each_pinned_wording_is_what_the_source_logs(self):
        for key, line in self.lines():
            self.assertIn(
                (line.level, line.logger, line.fmt),
                self.calls[line.source],
                f"{key}: the {line.source} source no longer logs this at {line.level} "
                f"on {line.logger}; read the new wording and fix the decree's pattern",
            )

    def test_the_bridge_logs_on_one_logger_at_info(self):
        # bridge_log_calls names every `log.` call wow-overseer, and the level
        # check below needs the root level the bridge's main sets.
        self.assertIn('log = logging.getLogger("wow-overseer")', self.bridge_text)
        self.assertRegex(
            self.bridge_text, r"logging\.basicConfig\(level=logging\.INFO\b"
        )

    def test_each_writer_reaches_a_log_the_judge_reads(self):
        appender = "EphModule"
        self.assertIn(podpaths.LOG_NAME, submit.BASELINE[f"Appender.{appender}"])
        for key, pin in sorted(PINS.items()):
            for line in pin.writers:
                if line.source == "bridge":
                    # The bridge sidecar's log, which the judge reads on a
                    # bridge-on decree only; the bridge keeps INFO and above.
                    self.assertEqual(self.decrees[key[0]]["world"]["bridge"], "on", key)
                    self.assertGreaterEqual(LEVELS["INFO"], LEVELS[line.level], key)
                    continue
                setting = submit.BASELINE.get(f"Logger.{line.logger}")
                self.assertIsNotNone(
                    setting, f"{key}: no world sets Logger.{line.logger}"
                )
                level, _, appenders = setting.partition(",")
                self.assertIn(appender, appenders.split(), key)
                self.assertGreaterEqual(int(level), LEVELS[line.level], key)

    def test_a_bridge_line_is_in_what_the_judge_reads_for_its_decree(self):
        for key, pin in sorted(PINS.items()):
            bridge_lines = [ln for ln in pin.writers if ln.source == "bridge"]
            if not bridge_lines:
                continue
            decree = self.decrees[key[0]]
            with tempfile.TemporaryDirectory() as tmp:
                world_log = pathlib.Path(tmp) / podpaths.LOG_NAME
                bridge_log = pathlib.Path(tmp) / podpaths.BRIDGE_LOG_NAME
                world_log.write_text("world started\n", encoding="utf-8")
                for line in bridge_lines:
                    bridge_log.write_text(line.rendered() + "\n", encoding="utf-8")
                    read = judge.log_reader(decree, str(world_log), str(bridge_log))
                    self.assertIn(line.rendered(), read(), key)
                    # The same decree with the bridge off reads the world log only.
                    off = {**decree, "world": {**decree["world"], "bridge": "off"}}
                    read_off = judge.log_reader(off, str(world_log), str(bridge_log))
                    self.assertNotIn(line.rendered(), read_off(), key)

    def test_only_the_sent_flight_report_names_a_taxi_node(self):
        # The flight pin's sibling lines assume a refused errand's sentence
        # never names a taxi node, so the pattern cannot count a refusal.
        source = (ROOT / "flightlearn.py").read_text(encoding="utf-8")
        naming = [s for s in re.findall(_LITERAL, source) if "taxi node" in s]
        self.assertEqual(
            naming,
            ['"sending them to learn taxi node %d (%s), %d yards off, by aiming "'],
        )

    def test_the_pattern_holds_on_the_line_as_logged_and_not_without_it(self):
        for key, pin in sorted(PINS.items()):
            log = self.checks.get(key)
            if log is None:
                continue  # reported by the pinning test
            pattern, expect = re.compile(log["pattern"]), log["expect"]
            self.assertIsNone(lint.log_bound_problem(expect), key)
            fewest, most = lint.log_bound_range(expect)
            for line in pin.writers:
                stamped = "2026-11-18 03:04:05 " + line.rendered()
                self.assertTrue(pattern.search(stamped), f"{key}: {stamped}")
                # As the judge counts: lines that match, against the bound.
                for n in range((most if most is not None else fewest) + 3):
                    text = "world started\n" + (stamped + "\n") * n
                    count = sum(1 for ln in text.splitlines() if pattern.search(ln))
                    self.assertEqual(count, n, key)
                    self.assertEqual(
                        judge.log_bound_holds(expect, count),
                        n >= fewest and (most is None or n <= most),
                        f"{key} at {n} lines",
                    )

    def test_the_pattern_ignores_the_sibling_lines(self):
        for key, pin in sorted(PINS.items()):
            log = self.checks.get(key)
            if log is None:
                continue
            pattern = re.compile(log["pattern"])
            for line in pin.ignores:
                self.assertFalse(
                    pattern.search(line.rendered()), f"{key}: {line.rendered()}"
                )

    def test_a_restored_decree_no_longer_says_the_line_is_not_asserted(self):
        self.assertLessEqual(RESTORED, {decree_id for decree_id, _name in PINS})
        self.assertFalse(RESTORED & set(STILL_NARROWED))
        for path, decree in shipped_decrees():
            if decree["id"] not in RESTORED:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(_NARROWED_WORDS.search(text), path.name)
            for entry in decree["proves"]:
                self.assertNotIn("not asserted", entry["criterion"], path.name)

    def test_every_decree_still_narrowed_is_listed_with_its_reason(self):
        narrowed = {
            decree["id"]
            for path, decree in shipped_decrees()
            if _NARROWED_WORDS.search(path.read_text(encoding="utf-8"))
        }
        self.assertEqual(sorted(narrowed), sorted(STILL_NARROWED))


if __name__ == "__main__":
    unittest.main()
