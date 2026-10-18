"""The bank passes log a line when it changes, not every pass (#1142).

Measured read-only on the dev realm bridge 2026-10-18, full hours 03:00 to
05:00 UTC: 9,686 and 10,087 lines an hour. The bank forecast logged about 250
lines a pass for its two families, six passes an hour, and 4 to 11 of them had
changed since the pass before; one moved count re-logged the whole forecast.
The bank policy logged the same twelve lines on every fresh read (every one to
three minutes), and the bank bags pass the same six lines every minute.
Between them about 3,000 lines an hour, nearly all a repeat.

Pinned here on the bridge's own functions, loaded out of bridge.py onto
fakes: a repeated note is not logged again, a changed one is, a note that
stopped holding is counted, the whole set is logged again after
LOG_RESAY_SECONDS, and two hours of the measured traffic stay under the
issue's bar of 1,000 bank forecast, bank policy and bank bags lines an hour.
"""

import contextlib
import pathlib
import types
import unittest

from test_family_economy_parity import FAKE_ASYNCIO, _load  # noqa: F401 - pymysql stub

import bankforecast  # noqa: E402

BRIDGE = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text(
    encoding="utf-8"
)
PREFIXES = ("bank forecast:", "bank policy:", "bank bags:")
LOGGERS = ["_log_capped", "_unsaid", "_log_changed"]


class _Log:
    """INFO lines kept, DEBUG lines counted apart: the bar is on INFO."""

    def __init__(self):
        self.lines = []
        self.debug_lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = info

    def debug(self, msg, *a, **k):
        self.debug_lines.append(msg % a if a else msg)


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


def _namespace(log, clock, resay=6 * 3600.0):
    return {
        "log": log,
        "time": clock,
        "GUILD_ROUTE_NOTE_LINES": 5,
        "LOG_RESAY_SECONDS": resay,
        "_SAID": {},
        "asyncio": FAKE_ASYNCIO,
        "bankforecast": bankforecast,
        "_family_label": lambda cohort: "",
    }


class _Line:
    def __init__(self, summary):
        self.summary = summary


class _Forecast:
    def __init__(self, summaries):
        self.lines = [_Line(s) for s in summaries]

    def decisions(self):
        return ()

    def headline(self):
        return "the vault holds %d stack(s)" % len(self.lines)


def _forecast_lines(family, n, moved, tick):
    """n item lines for a family; the first `moved` carry this pass's count."""
    return [
        "%s item %d: %d guild-wide" % (family, i, tick if i < moved else 7)
        for i in range(n)
    ]


class TheChangeOnlyLogger(unittest.TestCase):
    def setUp(self):
        self.log, self.clock = _Log(), _Clock()
        self.ns = _load(LOGGERS, _namespace(self.log, self.clock))

    def test_a_repeated_set_is_not_logged_again(self):
        notes = ["Zug has 1 empty bank bag slot(s)", "Oz has 1 empty bank bag slot(s)"]
        self.ns["_log_changed"]("bank bags", notes, ("Oz", "Zug"))
        self.assertEqual(2, len(self.log.lines))
        self.ns["_log_changed"]("bank bags", notes, ("Oz", "Zug"))
        self.assertEqual(2, len(self.log.lines), self.log.lines)
        self.assertEqual(1, len(self.log.debug_lines))

    def test_only_the_changed_note_is_logged_and_the_dropped_one_counted(self):
        self.ns["_log_changed"]("bank policy", ["a", "b", "c"], ("Grog",))
        self.log.lines.clear()
        self.ns["_log_changed"]("bank policy", ["a", "b", "d"], ("Grog",))
        self.assertEqual(
            ["bank policy: d", "bank policy: 1 line(s) logged before no longer hold"],
            self.log.lines,
        )

    def test_each_family_is_remembered_apart(self):
        self.ns["_log_changed"]("bank bags", ["x"], ("Grog",))
        self.ns["_log_changed"]("bank bags", ["y"], ("Zug",))
        self.ns["_log_changed"]("bank bags", ["x"], ("Grog",))
        self.ns["_log_changed"]("bank bags", ["y"], ("Zug",))
        self.assertEqual(["bank bags: x", "bank bags: y"], self.log.lines)

    def test_the_whole_set_is_logged_again_after_the_resay_window(self):
        self.ns["_log_changed"]("bank bags", ["x", "y"], ())
        self.clock.now += self.ns["LOG_RESAY_SECONDS"] - 1
        self.ns["_log_changed"]("bank bags", ["x", "y"], ())
        self.assertEqual(2, len(self.log.lines))
        self.clock.now += 1
        self.ns["_log_changed"]("bank bags", ["x", "y"], ())
        self.assertEqual(4, len(self.log.lines))

    def test_uncapped_logs_every_fresh_note(self):
        notes = ["n%d" % i for i in range(8)]
        self.ns["_log_changed"]("bank", notes, (), capped=False)
        self.assertEqual(["bank: n%d" % i for i in range(8)], self.log.lines)


class TheBankForecastLogsWhatMoved(unittest.TestCase):
    def setUp(self):
        self.log, self.clock = _Log(), _Clock()
        self.forecast = _Forecast([])
        ns = _namespace(self.log, self.clock)
        ns["_bank_forecast"] = lambda names, fresh: self.forecast
        self.ns = _load(LOGGERS + ["_say_bank_forecast"], ns)

    def say(self, names=("Bork", "Grog")):
        coro = self.ns["_say_bank_forecast"](None, list(names))
        with contextlib.suppress(StopIteration):
            coro.send(None)

    def test_the_same_forecast_twice_logs_once(self):
        self.forecast = _Forecast(["Tin Ore: 4", "Small Egg: 130"])
        self.say()
        self.assertEqual(3, len(self.log.lines))
        self.say()
        self.assertEqual(3, len(self.log.lines), self.log.lines)

    def test_one_moved_count_logs_the_headline_and_that_line_only(self):
        self.forecast = _Forecast(["Tin Ore: 4", "Small Egg: 130", "Murloc Fin: 22"])
        self.say()
        self.log.lines.clear()
        self.forecast = _Forecast(["Tin Ore: 4", "Small Egg: 131", "Murloc Fin: 22"])
        self.say()
        self.assertEqual(
            [
                "bank forecast: the vault holds 3 stack(s)",
                "bank forecast: Small Egg: 131",
                "bank forecast: 1 line(s) logged before no longer hold",
            ],
            self.log.lines,
        )

    def test_an_empty_forecast_never_logged_says_nothing(self):
        self.say()
        self.assertEqual([], self.log.lines)


class TwoHoursOfTheMeasuredTrafficStayUnderTheBar(unittest.TestCase):
    """The dev realm's shape, replayed for a warm-up hour and two measured
    hours: two families, a forecast of 126 lines each every ten minutes with 7
    moved; a fresh bank policy read of 6 placements and 6 spare copies per
    family every two minutes; 6 bank bag notes per family every minute."""

    FAMILIES = (
        ("Bork", "Grog", "Grug", "Og", "Ugga"),
        ("Oz", "Uzza", "Zork", "Zrog", "Zug"),
    )

    def setUp(self):
        self.log, self.clock = _Log(), _Clock()
        self.tick = 0
        ns = _namespace(self.log, self.clock)
        ns["_bank_forecast"] = lambda names, fresh: _Forecast(
            _forecast_lines(names[0], 126, 7, self.tick)
        )
        ns["_BANK_POLICY_CACHE"] = {}
        ns["_keep_reservations"] = lambda cur, key: None
        ns["_connect"] = lambda: contextlib.nullcontext(
            types.SimpleNamespace(cursor=lambda: contextlib.nullcontext(None))
        )
        ns["bankpolicy"] = types.SimpleNamespace(
            read=lambda cur, names, reservations=None: names,
            place=lambda names: {
                i: types.SimpleNamespace(
                    holder=names[i % 5], item="Item %d" % i, where="bank", why="kept"
                )
                for i in range(6)
            },
            redundant=lambda names: frozenset(range(100, 106)),
        )
        ns["_fetch_bank_bag_facts"] = lambda names: [
            types.SimpleNamespace(name=n) for n in names + names[:1]
        ]
        ns["bankbags"] = types.SimpleNamespace(
            family_floor=lambda facts: 0,
            step=lambda f, floor: (None, "%s has 1 empty bank bag slot(s)" % f.name),
        )
        self.ns = _load(
            LOGGERS + ["_say_bank_forecast", "_bank_policy_read", "_bank_bag_slots"], ns
        )

    def run_coro(self, coro):
        with contextlib.suppress(StopIteration):
            coro.send(None)

    def minute(self, m):
        self.clock.now += 60
        for names in self.FAMILIES:
            names = list(names)
            if m % 10 == 0:
                self.run_coro(self.ns["_say_bank_forecast"](None, names))
            if m % 2 == 0:
                self.ns["_bank_policy_read"](names, True)
            self.run_coro(self.ns["_bank_bag_slots"](None, names, set()))

    def bank_lines(self):
        return [ln for ln in self.log.lines if ln.startswith(PREFIXES)]

    def test_under_a_thousand_an_hour_over_two_full_hours(self):
        for m in range(60):
            if m % 10 == 0:
                self.tick += 1
            self.minute(m)
        warm = len(self.bank_lines())
        for m in range(60, 180):
            if m % 10 == 0:
                self.tick += 1
            self.minute(m)
        measured = len(self.bank_lines()) - warm
        self.assertLess(measured / 2, 1000, "%d lines in two hours" % measured)


class ThePassesUseTheChangeOnlyLogger(unittest.TestCase):
    def block(self, signature):
        start = BRIDGE.index(signature)
        end = BRIDGE.index("\n    def ", start + 1)
        end = min(end, BRIDGE.index("\n    async def ", start + 1))
        return BRIDGE[start:end]

    def test_the_bank_policy_read(self):
        self.assertIn('_log_changed("bank policy", ', BRIDGE)
        self.assertIn('_log_changed("bank policy: spare copy", ', BRIDGE)

    def test_the_bank_bags_pass(self):
        self.assertIn(
            '_log_changed("bank bags", notes',
            self.block("    async def _bank_bag_slots("),
        )

    def test_the_bank_plan_notes(self):
        self.assertIn(
            '_log_changed("bank", bank_plan.notes',
            self.block("    async def _bank_once("),
        )

    def test_the_sell_passes_policy_notes(self):
        self.assertIn('_log_changed("%s: bank policy" % what', BRIDGE)


if __name__ == "__main__":
    unittest.main()
