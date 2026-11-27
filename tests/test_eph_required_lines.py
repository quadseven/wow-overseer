"""A decree that requires a log line is pinned to the code that writes the line.

Since #2767 a log check can require a line (`at_least`) or cap one (`at_most`).
A pattern that no code emits makes such a check useless in the worst way: a
required line that is never written fails every run, and a capped line that is
never written passes every run. So every bounded log check in a shipped decree
is listed here beside the format string of each call that writes its line, and:

- the format string must still be in the pinned source, at that level and on
  that logger, so a reworded line turns this file red before it turns a
  proving run red;
- the logger must reach the one log the judge reads (the file appender that
  `submit.BASELINE` adds), at a level that keeps the line;
- the pattern must match the line as the source formats it, and must not match
  the sibling line the same code writes when the thing did not happen.

The pinned sources are the mod-overseer submodule, the immutable raid fix in
its history, and the test copies of the playerbots patches under patches/.
Lines of the bridge, of the core and of the
dungeon module are not in this repo or not in the log the judge reads; the
decrees whose criteria rest on them are listed in STILL_NARROWED.
"""

import pathlib
import re
import unittest
from typing import NamedTuple

import modsource
from ephemeral import judge, lint, podpaths, submit
from ephemeral.miniyaml import loads

ROOT = pathlib.Path(__file__).resolve().parent.parent
DECREE_DIR = ROOT / "data" / "decrees"
REFLECT_PATCH = (
    ROOT
    / "patches"
    / "mod-playerbots"
    / "0017-casters-hold-on-a-majordomo-add-with-magic-reflection.patch"
)

# The core's log levels, as the `Logger.<name>` config value counts them.
LEVELS = {"FATAL": 1, "ERROR": 2, "WARN": 3, "INFO": 4, "DEBUG": 5, "TRACE": 6}

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


def patch_added_text(text):
    """The lines a patch adds, without their leading plus sign."""
    return "\n".join(
        line[1:]
        for line in text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


class Line(NamedTuple):
    """One logging call: where it is, what it formats, and sample arguments."""

    source: str  # "module", "raid-door-fix", or "reflect-patch"
    level: str
    logger: str
    fmt: str
    args: tuple

    def rendered(self):
        holes = _PLACEHOLDER.findall(self.fmt)
        if len(holes) != len(self.args):
            raise AssertionError(
                f"{len(holes)} placeholders but {len(self.args)} sample arguments: {self.fmt}"
            )
        values = iter(self.args)
        return _PLACEHOLDER.sub(lambda _m: str(next(values)), self.fmt)


def module(level, fmt, *args):
    return Line("module", level, "module.overseer", fmt, args)


class Pin(NamedTuple):
    """The calls that write a check's line, and the sibling lines it must ignore."""

    writers: tuple
    ignores: tuple = ()


SHIP = "Ship (The Lady Mehley)"
RAID_DOOR = "raid-under-quorum-at-door"
# RaidQuorumShortfall in the decree's exact fix produces this with five DPS
# assembled and the decree's 36-seat, 3-tank, 8-healer floor.
RAID_SHORTFALL = "5 of 5, short 31 seats, 3 tanks, 8 healers"

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
    (RAID_DOOR, "the-hold-warned-about-the-shortfall"): Pin(
        writers=(
            Line(
                "raid-door-fix",
                "WARN",
                "module.overseer",
                "overseer: raid run for family '{}' holds at the door - {}",
                ("Grug", RAID_SHORTFALL),
            ),
        ),
    ),
    (RAID_DOOR, "the-shortfall-was-logged"): Pin(
        writers=(
            # AI-REVIEW 2026-11-27 [nemotron-3.5-super-vl] 90f35a03 (Elder, PR #3344):
            # Verify the dedicated quorum warning in the decree's exact fix.
            Line(
                "raid-door-fix",
                "WARN",
                "module.overseer",
                "overseer: raid run for family '{}' ends the order - no quorum at the door ({})",
                ("Grug", RAID_SHORTFALL),
            ),
        ),
        ignores=(
            module(
                "INFO",
                "overseer: raid run for family '{}' released at {} - {}",
                "Grug",
                "ASSEMBLE",
                "no raid is ordered",
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
}

# Decrees whose header still says a criterion was narrowed for want of a
# positive log check, and why `at_least` does not restore it from this repo.
STILL_NARROWED = {
    # The line is bridge text. The judge reads one file, the worldserver's own
    # appender, and the bridge does not write to it.
    "guild-brd-keyed-wing": "bridge log",
    "raid-order-seats-arrive-at-door": "bridge log",
    "raid-prep-mail-and-bank-cycle": "bridge log",
    # The line is written by the dungeon module, whose source is not in this repo.
    "blackfathom-gelihast-stranded-rescue": "dungeon module source not here",
    "brd-ale-run-rested-party": "dungeon module source not here",
    "brd-paladin-without-redemption": "dungeon module source not here",
    "deadmines-gunpowder-no-opener": "dungeon module source not here",
    # The core writes these, its source is not in this repo, and the decree
    # sends the two loggers to appenders the judge does not read.
    # The orders this decree gives are not the roster errands whose lines name
    # the recipe, so no emitter can be tied to what the decree does.
    "trainer-recipe-and-vendor-manual": "the act does not reach a pinned emitter",
    # Nothing was narrowed here: the criterion only forbids a line.
    "family-boat-crossing": "forbids a line only",
}

# Bounded log checks that main gained after the pinning above was written and
# whose emitter is not in a source this file reads (the wording is not in the
# pinned module source, or the line is written by the core, the bridge or the
# dungeon module). Each is listed so a new unpinned check is a red test, not a
# silent one; pin an entry (and delete it here) when its emitter is reachable.
UNPINNED = {
    "alliance-brd-campaign-home": "emitter not in the pinned module source",
    "brd-core-fragment-chest": "emitter not in the pinned module source",
    "brd-fineous-ironfel-pickup": "dungeon module source not here",
    "cross-map-party-split-is-reported": "emitter not in the pinned module source",
    "cross-map-stranded-member-names-its-way": "emitter not in the pinned module source",
    "deadmines-early-entrant-barrier": "emitter not in the pinned module source",
    "fall-death-logger-capture": "core source not here",
    "family-learns-unknown-flight-node": "emitter not in the pinned module source",
    "ghost-healer-walk-hold-is-timed": "emitter not in the pinned module source",
    "long-dungeon-exits-count-walking-progress": "emitter not in the pinned module source",
    "open-world-tank-avoids-out-of-range-melee": "core source not here",
    "razorfen-downs-exits-and-restarts-together": "emitter not in the pinned module source",
    "stratholme-yard-hearth-names-its-reason": "emitter not in the pinned module source",
}
_NARROWED_WORDS = re.compile(
    r"can only forbid|cannot demand presence|cannot require|is an exact count"
)


def shipped_decrees():
    for path in sorted(DECREE_DIR.glob("*.yaml")):
        if path.name != "anchors.yaml":
            yield path, loads(path.read_text(encoding="utf-8"))


def bounded_checks():
    """Log blocks for bounds that need an emitter, including scenario witnesses."""
    found = {}
    for _path, decree in shipped_decrees():
        for o in decree.get("observe") or []:
            expect = (o.get("log") or {}).get("expect") or {}
            if ("log" in o and o.get("role") == "precondition") or any(
                key in expect for key in lint.LOG_RANGE_KEYS
            ):
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


class RequiredLinesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checks = bounded_checks()
        cls.calls = {
            "module": log_calls(modsource.read(modsource.MODULE, errors="replace")),
            "reflect-patch": log_calls(
                patch_added_text(REFLECT_PATCH.read_text(encoding="utf-8"))
            ),
        }

    def lines(self):
        for key, pin in sorted(PINS.items()):
            for line in (*pin.writers, *pin.ignores):
                yield key, line

    def test_every_bounded_log_check_is_pinned_to_its_emitter(self):
        self.assertEqual(
            sorted(self.checks),
            sorted({*PINS, *((d, n) for (d, n) in self.checks if d in UNPINNED)}),
            "a log precondition or a check with at_least or at_most needs an entry in PINS naming "
            "the call that writes its line (and a stale entry must go)",
        )
        self.assertEqual(
            sorted(UNPINNED),
            sorted({d for d, _n in self.checks if d in UNPINNED}),
            "a stale UNPINNED entry must go",
        )
        self.assertTrue(
            any("at_least" in c["expect"] for c in self.checks.values()),
            "no shipped decree requires a log line",
        )

    def test_each_pinned_wording_is_what_the_source_logs(self):
        for key, line in self.lines():
            if line.source == "raid-door-fix":
                continue  # checked against the exact fix, not the test checkout
            self.assertIn(
                (line.level, line.logger, line.fmt),
                self.calls[line.source],
                f"{key}: the {line.source} source no longer logs this at {line.level} "
                f"on {line.logger}; read the new wording and fix the decree's pattern",
            )

    def test_raid_door_warnings_are_emitted_at_hold_and_end(self):
        raid = loads((DECREE_DIR / f"{RAID_DOOR}.yaml").read_text(encoding="utf-8"))
        source = modsource.read_revision(raid["fix"]["commit"], modsource.MODULE)
        before_end, _, after_end = source.partition("if (step.quorumEnds)")
        _, hold, hold_block = before_end.rpartition(
            "else if (run.quorumShortSaid != step.shortfall)"
        )
        end_block, release, _ = after_end.partition("if (step.release)")
        self.assertTrue(hold, "the hold warning must use the measured shortfall")
        self.assertTrue(release, "the quorum-end block no longer precedes raid release")
        for name, block in (
            ("the-hold-warned-about-the-shortfall", hold_block),
            ("the-shortfall-was-logged", end_block),
        ):
            (line,) = PINS[(RAID_DOOR, name)].writers
            self.assertIn((line.level, line.logger, line.fmt), log_calls(block))

    def test_each_writer_reaches_the_log_the_judge_reads(self):
        appender = "EphModule"
        self.assertIn(podpaths.LOG_NAME, submit.BASELINE[f"Appender.{appender}"])
        for key, pin in sorted(PINS.items()):
            for line in pin.writers:
                setting = submit.BASELINE.get(f"Logger.{line.logger}")
                self.assertIsNotNone(
                    setting, f"{key}: no world sets Logger.{line.logger}"
                )
                level, _, appenders = setting.partition(",")
                self.assertIn(appender, appenders.split(), key)
                self.assertGreaterEqual(int(level), LEVELS[line.level], key)

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
        restored = {decree_id for decree_id, _name in PINS} - set(STILL_NARROWED)
        self.assertEqual(len(restored), 10)
        for path, decree in shipped_decrees():
            if decree["id"] not in restored:
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
