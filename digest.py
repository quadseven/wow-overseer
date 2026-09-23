"""Catching up on the family: a time window in, an account of it out.

Pure module, the same seam as questbook.py and bonds.py - facts in,
judgements and prose out. No pymysql, no network. bridge.py runs the queries
and hands the rows in.

WHY THIS EXISTS, in the operator's words:

  "What is the family doing now? What did they do all night? I want to be able
   to ask these questions when I come back later to catch up on what they've
   been doing. I wanna ask naturally how they are, what they did the past x
   hours, any new quests, or gear they got, and skills or levels."

So: ask in plain words, get an account of five characters - where they stand,
what moved, and who is falling behind.

THE HARD PART IS "WHAT CHANGED", AND MOST OF THE TABLES CANNOT ANSWER IT.
`characters.level` says Grug is 14. It does not say he dinged twice tonight.
`character_queststatus_rewarded` is (guid, quest, active) with no timestamp -
it says Og has turned in 17 quests, never when. `overseer_snapshot` is
overwritten roughly once a minute and keeps no history at all. A digest that
reported "Grug gained 2 levels in the last 6 hours" from those tables would be
inventing the number.

This module is therefore explicit about THREE grades of fact, and every figure
it renders carries the grade it came from:

  RECONSTRUCTABLE TODAY, from rows that genuinely carry a time:
    - overseer_chat.created_at        what they actually said, verbatim
    - overseer_thought.created_at     narrated moments (events.py, #2602)
    - overseer_command.created_at     orders given and obeyed
    - overseer_goal                   goals opened and finished
    - characters.leveltime            PLAYED time at the current level, which
                                      dates the most recent ding - see
                                      dinged_recently() for the one condition
                                      under which that is wall-clock truth.

  STANDING ONLY, true right now and carrying no history:
    - level, gold, quest turn-ins, spells, talents, equipped gear.
      These are what "how are they?" is really asking, and they are the
      inequality the operator cares about, so they are reported plainly as standings
      and never dressed up as deltas.

  ONLY FROM THE MOMENT SAMPLING SHIPS:
    - levels gained, gold earned, quests turned in, spells learned, talents
      spent, gear changed OVER A WINDOW. bridge.py writes an overseer_sample
      row per character every few minutes; a delta is the difference between
      two of those rows. Before the first sample there is no baseline, and
      changes() returns BASIS_NO_BASELINE rather than a zero - "nothing
      happened" and "I was not watching" are different answers and this module
      never confuses them.

STALENESS. character_spell and character_talent are written on the player save
interval (PlayerSaveInterval = 900000, staggered per player), so a spell count
can be a quarter of an hour behind the world. The live truth is tools/probe.py.
Every standing therefore carries a `source` string and the renderer prints it,
rather than mixing a one-minute-fresh level with a fifteen-minute-old spell
count and presenting both as now.

OPTIONAL ENRICHMENT. A sibling ticket is adding an `overseer_event` table
(level ups, quest accept/complete, items equipped, deaths, spell failures, all
timestamped). This module never requires it: moments arrive as an ordinary
list, and whether they were built from that table or from overseer_chat and
overseer_thought is the bridge's problem. When the table exists the account
gains named quests and named items; without it, it still says who moved and
who is behind. See Moment.source.

WHO IS BEHIND IS NOT DECIDED HERE. questbook.py already computes shared vs
personal quests, who is behind, an ordered catch-up plan and unreachable
stalls, against the class masks and chain rules that make that question hard.
A Ledger is an input; this module reads it and speaks it. A second opinion
about who is behind would be a second answer that could disagree with the one
the council acts on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import bonds
import questbook

# --- provenance ------------------------------------------------------------
# Short strings, printed verbatim in the digest's footer. The rule they exist
# for: a reader must never have to guess whether a number is a minute old or a
# quarter of an hour old, because two of these tables genuinely differ by that
# much and the difference is invisible in the value.
SOURCE_SNAPSHOT = "overseer_snapshot, refreshed about once a minute"
SOURCE_CHARACTERS = "characters table, written on player save"
SOURCE_SAVED = "player save tables, up to 15 minutes behind (PlayerSaveInterval)"
SOURCE_SAMPLE = "overseer_sample, taken periodically by the bridge"
SOURCE_EVENT = "overseer_event"
SOURCE_CHAT = "overseer_chat"
SOURCE_THOUGHT = "overseer_thought"

# How a Change was arrived at. Three values, because there are three genuinely
# different situations and collapsing any two of them tells a lie.
BASIS_SAMPLED = "sampled"  # two real samples, the delta is measured
BASIS_NO_BASELINE = "no-baseline"  # sampling started after the window did
BASIS_NO_SAMPLES = "no-samples"  # nothing sampled for this character at all

COPPER_PER_GOLD = 10000

# --- thresholds, named so a reader can argue with them ---------------------
# The operator's standing requirement is that nobody falls behind, so the digest
# volunteers these without being asked. Each number is a judgement, written
# down where it can be changed rather than buried in an if.

# Turn-in spread worth mentioning. Live tonight: Og 17 against Grog and Ugga
# on 3, a spread of 14. Five is already a visible gap in levelling pace.
QUEST_SPREAD = 5
# Under this and a character cannot pay a trainer, which is how a character
# stops gaining spells without anything looking wrong. Grog is on 0.3 gold.
BROKE_COPPER = 1 * COPPER_PER_GOLD
# Level spread worth mentioning. At these levels three is a different set of
# mobs and a different quest hub.
LEVEL_SPREAD = 3

# How many of each kind of thing the account quotes before it summarises.
# A digest is read, not scrolled.
MAX_QUOTES = 4
MAX_NAMED = 5


@dataclass(frozen=True)
class Window:
    """The stretch of time being asked about."""

    hours: float
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return self.hours * 3600.0

    def contains(self, when) -> bool:
        return when is not None and self.start <= when <= self.end

    def describe(self) -> str:
        if self.hours >= 23:
            return "the last day"
        if self.hours == int(self.hours):
            n = int(self.hours)
            return "the last hour" if n == 1 else "the last %d hours" % n
        return "the last %.1f hours" % self.hours


@dataclass(frozen=True)
class Standing:
    """Where one character stands right now.

    `copper` rather than gold: `characters.money` is copper, and rounding at
    the edge of the system is how 0.3 gold and 0 gold become the same number.
    The renderer divides; nothing else does.

    `level_time_seconds` is characters.leveltime - PLAYED seconds at the
    current level. It is the only per-character time this schema carries that
    points backwards, and dinged_recently() is the one place it is allowed to
    become a claim about wall-clock.
    """

    name: str
    level: int = 0
    copper: int = 0
    quests_done: int = 0
    spells: int = 0
    talents: int = 0
    equipped: int = 0
    online: bool = False
    zone: str = ""
    level_time_seconds: int = 0
    # Which table each grade of figure came from, printed in the footer.
    live_source: str = SOURCE_SNAPSHOT
    saved_source: str = SOURCE_SAVED

    @property
    def gold(self) -> float:
        return self.copper / COPPER_PER_GOLD


@dataclass(frozen=True)
class Sample:
    """One periodic reading of a character's counters.

    This is the only thing in the whole design that makes "what changed in the
    last six hours" answerable, and it is why the PR says half of this feature
    starts accruing on deploy rather than reaching backwards.
    """

    name: str
    at: datetime
    level: int = 0
    copper: int = 0
    quests_done: int = 0
    spells: int = 0
    talents: int = 0
    equipped: int = 0


@dataclass(frozen=True)
class Moment:
    """Something that happened at a known time.

    Deliberately loose. It is built from overseer_event where that table
    exists and from overseer_chat / overseer_thought where it does not, and
    the digest treats the two the same except for saying which it was.
    """

    at: datetime
    name: str
    kind: str
    text: str = ""
    source: str = SOURCE_EVENT


@dataclass(frozen=True)
class Change:
    """What moved for one character across the window, and on what authority.

    Every counter is a delta of two samples. `basis` is checked before any
    field is read: on BASIS_NO_BASELINE the numbers are all zero and MEAN
    NOTHING, and rendering them would be the fabrication this module exists
    to avoid.
    """

    name: str
    basis: str = BASIS_NO_SAMPLES
    since: datetime | None = None
    levels: int = 0
    copper: int = 0
    quests: int = 0
    spells: int = 0
    talents: int = 0
    equipped: int = 0

    @property
    def measured(self) -> bool:
        return self.basis == BASIS_SAMPLED

    @property
    def moved(self) -> bool:
        """Did anything at all change? Only meaningful when measured."""
        return self.measured and any(
            (
                self.levels,
                self.copper,
                self.quests,
                self.spells,
                self.talents,
                self.equipped,
            )
        )


@dataclass(frozen=True)
class Gap:
    """One inequality in the family, stated with both ends named.

    Volunteered, never asked for: the digest reports these whether or not the
    question mentioned them, because "nobody falls behind" is a standing
    requirement and a number nobody looks at cannot enforce it.
    """

    metric: str
    unit: str
    leader: str
    leader_value: float
    laggards: tuple = ()
    laggard_value: float = 0.0
    note: str = ""

    @property
    def spread(self) -> float:
        return self.leader_value - self.laggard_value


def dinged_recently(standing: Standing, window: Window) -> bool:
    """Did this character reach its current level inside the window?

    THE ONE HONEST USE OF leveltime, and the condition is load-bearing.
    characters.leveltime counts PLAYED seconds at the level, not wall-clock
    ones, so a small value on an offline character proves nothing - they could
    have dinged a week ago and logged out a minute later. It equals wall-clock
    only while a character stays logged in, which these five do: they are
    playerbots held in the world by the overseer around the clock.

    So: online, and fewer played seconds at this level than the window is
    long. Anything else returns False, which reads as "I cannot tell" and
    costs nothing, rather than a ding that may never have happened.
    """
    if not standing.online or standing.level_time_seconds <= 0:
        return False
    return standing.level_time_seconds < window.seconds


def _latest_at_or_before(samples, when):
    """The most recent sample not later than `when`, or None."""
    best = None
    for s in samples:
        if s.at <= when and (best is None or s.at > best.at):
            best = s
    return best


def _latest(samples):
    return max(samples, key=lambda s: s.at) if samples else None


def changes(window: Window, samples) -> dict:
    """name -> Change, from sample rows.

    The baseline is the last sample AT OR BEFORE the window opened, not the
    first sample inside it. Using the first inside would silently shorten the
    window to whatever the sampler happened to cover and report a six-hour
    night as the twenty minutes since the last restart - a wrong number that
    looks entirely reasonable.

    A character with samples but none old enough gets BASIS_NO_BASELINE and
    the time its record actually starts, so the digest can say "I have only
    been counting since 04:10" instead of "nothing happened".
    """
    by_name: dict = {}
    for s in samples:
        by_name.setdefault(s.name, []).append(s)

    out: dict = {}
    for name, rows in by_name.items():
        before = _latest_at_or_before(rows, window.start)
        after = _latest_at_or_before(rows, window.end) or _latest(rows)
        if before is None or after is None or after.at <= before.at:
            earliest = min(rows, key=lambda s: s.at).at if rows else None
            out[name] = Change(name=name, basis=BASIS_NO_BASELINE, since=earliest)
            continue
        out[name] = Change(
            name=name,
            basis=BASIS_SAMPLED,
            since=before.at,
            levels=after.level - before.level,
            copper=after.copper - before.copper,
            quests=after.quests_done - before.quests_done,
            spells=after.spells - before.spells,
            talents=after.talents - before.talents,
            equipped=after.equipped - before.equipped,
        )
    return out


def gaps(standings) -> tuple:
    """Every inequality worth saying out loud, worst first.

    Quest turn-ins, gold, level - in that order of importance, which is the
    order they actually bite: turn-ins are the experience nobody is getting,
    gold is the training nobody can pay for, and level is the symptom of both.

    A gap is only reported when it clears its named threshold. Reporting every
    spread would make the section noise, and noise is how "Grog has 0.3 gold"
    goes unread for a week.
    """
    live = [s for s in standings if s.name]
    if len(live) < 2:
        return ()

    found = []

    quests = {s.name: s.quests_done for s in live}
    hi, lo = max(quests.values()), min(quests.values())
    if hi - lo >= QUEST_SPREAD:
        found.append(
            Gap(
                metric="quest turn-ins",
                unit="",
                leader=max(sorted(quests), key=lambda n: quests[n]),
                leader_value=hi,
                laggards=tuple(sorted(n for n, v in quests.items() if v == lo)),
                laggard_value=lo,
                note=(
                    "turn-ins are where the experience is, so this is what the "
                    "level difference is made of"
                ),
            )
        )

    broke = sorted(s.name for s in live if s.copper < BROKE_COPPER)
    if broke:
        richest = max(sorted(live, key=lambda s: s.name), key=lambda s: s.copper)
        poorest = min(sorted(live, key=lambda s: s.name), key=lambda s: s.copper)
        found.append(
            Gap(
                metric="gold",
                unit="g",
                leader=richest.name,
                leader_value=richest.gold,
                laggards=tuple(broke),
                laggard_value=poorest.gold,
                note="under a gold buys no training and no repairs",
            )
        )

    levels = {s.name: s.level for s in live}
    hi, lo = max(levels.values()), min(levels.values())
    if hi - lo >= LEVEL_SPREAD:
        found.append(
            Gap(
                metric="level",
                unit="",
                leader=max(sorted(levels), key=lambda n: levels[n]),
                leader_value=hi,
                laggards=tuple(sorted(n for n, v in levels.items() if v == lo)),
                laggard_value=lo,
                note="different mobs, and a quest hub they cannot share",
            )
        )

    return tuple(found)


@dataclass(frozen=True)
class Digest:
    """Everything the account needs, computed once so the parts agree."""

    window: Window
    standings: tuple = ()
    changes: dict = field(default_factory=dict)
    moments: tuple = ()
    gaps: tuple = ()
    ledger: questbook.Ledger | None = None
    # True when the moments were built from the typed event table rather than
    # from chat and thoughts. Only ever used to say so.
    has_event_log: bool = False

    @property
    def names(self) -> tuple:
        return tuple(s.name for s in self.standings)

    def standing(self, name: str):
        for s in self.standings:
            if s.name == name:
                return s
        return None

    @property
    def measured(self) -> bool:
        """Is there a real baseline for anybody?"""
        return any(c.measured for c in self.changes.values())


def build(
    window: Window,
    standings,
    samples,
    moments,
    *,
    ledger=None,
    has_event_log: bool = False,
) -> Digest:
    """The whole account, in one pass.

    Standings come out in the family's speaking order - oldest first - which
    is the same order bonds already uses when the whole family answers at
    once. Alphabetical would put the seven-year-old first and the mother last
    in a report about how the family is.
    """
    order = {
        n: i for i, n in enumerate(bonds.speaking_order([s.name for s in standings]))
    }
    ordered = tuple(sorted(standings, key=lambda s: order.get(s.name, 999)))
    return Digest(
        window=window,
        standings=ordered,
        changes=changes(window, samples),
        moments=tuple(
            sorted(
                (m for m in moments if window.contains(m.at)),
                key=lambda m: (m.at, m.name),
            )
        ),
        gaps=gaps(ordered),
        ledger=ledger,
        has_event_log=has_event_log,
    )


# --- asking for it ---------------------------------------------------------
# "how are they", "what did they do all night", "catch me up on the last 6
# hours". Parsed here rather than in core.py for the same reason goals and
# fanout parse in their own modules: core is the dispatcher, and a grammar
# living in the dispatcher is a grammar with no tests of its own.
#
# THIS IS NOT A voice.VOCABULARY ENTRY, and that is the point. Entries in
# VOCABULARY are mod-playerbots chat commands delivered verbatim to a
# character; a reporting verb put there would be whispered to a bot that has
# no such command, and mod-playerbots would cheerfully report success - the
# exact shape of the `sell junk` failure documented in voice.py. Asking how
# the family is, is a question for the OVERSEER, and it never reaches the
# game at all.

DEFAULT_HOURS = 6.0
NIGHT_HOURS = 8.0
MAX_HOURS = 24.0 * 14

_ASK_RE = re.compile(
    r"\b("
    r"how (are|is|have|has) (they|the family|everyone|everybody|things)"
    r"|how('s| is) the family"
    r"|what (are|is|have|has|did|were|was) (they|the family|everyone|everybody)"
    r"|catch (me )?up"
    r"|what did i miss|anything happen|what happened"
    r"|digest|family report|how did they do"
    r")\b",
    re.IGNORECASE,
)
_NIGHT_RE = re.compile(
    r"\b(all night|overnight|last night|while i (was )?(slept|was asleep|slept)"
    r"|since i went to bed)\b",
    re.IGNORECASE,
)
_HOURS_RE = re.compile(
    r"\b(?:last|past|previous)\s+(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|d|day|days)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Ask:
    """A parsed request for a digest."""

    hours: float = DEFAULT_HOURS


def parse_ask(text: str):
    """An Ask, or None if this is not somebody asking after the family.

    Deliberately narrow. This runs on unaddressed lines in the overseer's own
    channel, where the roster query already lives, so a loose pattern would
    start swallowing "who is online". Every alternative above names the
    family, or is an explicit catch-up phrase, or is a word only this feature
    uses.
    """
    if not text or not _ASK_RE.search(text):
        return None
    m = _HOURS_RE.search(text)
    if m:
        value = float(m.group(1))
        if m.group(2).lower().startswith("d"):
            value *= 24.0
        # Zero and negative are somebody testing, not a window. Fall back to
        # the default rather than reporting an empty stretch of time.
        hours = min(value, MAX_HOURS) if value > 0 else DEFAULT_HOURS
        return Ask(hours=hours)
    if _NIGHT_RE.search(text):
        return Ask(hours=NIGHT_HOURS)
    return Ask(hours=DEFAULT_HOURS)


def window_for(ask: Ask, now: datetime) -> Window:
    return Window(hours=ask.hours, start=now - timedelta(hours=ask.hours), end=now)


# --- saying it -------------------------------------------------------------


def _gold(copper: int) -> str:
    return "%.1fg" % (copper / COPPER_PER_GOLD)


def _plural(n: int, word: str) -> str:
    return "%d %s%s" % (n, word, "" if abs(n) == 1 else "s")


def _and_list(names) -> str:
    names = list(names)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return "%s and %s" % (", ".join(names[:-1]), names[-1])


def _change_clause(change: Change) -> str:
    """What moved for one character, as a clause, or "" for nothing to say."""
    if not change.measured:
        return ""
    bits = []
    if change.levels:
        bits.append("gained %s" % _plural(change.levels, "level"))
    if change.quests:
        bits.append("turned in %s" % _plural(change.quests, "quest"))
    if change.spells:
        bits.append("learned %s" % _plural(change.spells, "spell"))
    if change.talents:
        bits.append("spent %s" % _plural(change.talents, "talent point"))
    if change.equipped:
        bits.append("changed %s" % _plural(abs(change.equipped), "piece of gear"))
    if change.copper:
        bits.append(
            "%s %s"
            % ("made" if change.copper > 0 else "spent", _gold(abs(change.copper)))
        )
    return _and_list(bits)


def _duration(seconds: int) -> str:
    """Seconds as something a person says. Rounded, never padded with false
    precision - "2 hours 30 minutes" from a counter that ticks once a second
    would imply the source is exact about a thing it is only roughly right
    about (see dinged_recently)."""
    minutes = int(seconds // 60)
    if minutes < 90:
        return _plural(max(minutes, 1), "minute")
    hours = minutes / 60.0
    return "%.1f hours" % hours


def _pronoun(name: str) -> str:
    """he/she, from bonds. Read rather than stored a second time here: the
    family table is where the five are described, and a duplicate could
    disagree with it. Anyone outside the family gets "they"."""
    bond = bonds.bond_of(name)
    if bond is None or not bond.gender:
        return "they"
    return "she" if bond.gender == "female" else "he"


def _standing_line(digest: Digest, standing: Standing) -> str:
    """One character, one sentence: where they are and what moved."""
    bond = bonds.bond_of(standing.name)
    who = ("the %s" % bond.role) if bond else "one of ours"
    where = " in %s" % standing.zone if standing.zone else ""
    they = _pronoun(standing.name)
    verb = "have" if they == "they" else "has"
    head = "%s, %s, is level %d%s with %s." % (
        standing.name,
        who,
        standing.level,
        where,
        _gold(standing.copper),
    )

    change = digest.changes.get(standing.name)
    if change is not None and change.measured:
        moved = _change_clause(change)
        head += (
            " Since then %s %s." % (they, moved)
            if moved
            else " Nothing moved for %s."
            % ("them" if they == "they" else "him" if they == "he" else "her")
        )
    elif dinged_recently(standing, digest.window):
        head += (
            " %s %s been level %d for %s of played time, so that ding is inside the window."
            % (
                they.capitalize(),
                verb,
                standing.level,
                _duration(standing.level_time_seconds),
            )
        )
    return head


def _no_baseline_line(digest: Digest) -> str:
    """The honest sentence for a window that starts before the counting did."""
    starts = [
        c.since
        for c in digest.changes.values()
        if c.basis == BASIS_NO_BASELINE and c.since
    ]
    if starts:
        return (
            "I cannot tell you what changed across %s: I have only been "
            "keeping count since %s, and nothing in the database remembers "
            "levels, gold or turn-ins before that."
            % (digest.window.describe(), min(starts).strftime("%H:%M on %d %b"))
        )
    return (
        "I cannot tell you what changed across %s. Nothing has been sampled "
        "yet, and levels, gold and turn-ins are stored as they are now, not "
        "as a history." % digest.window.describe()
    )


def _gap_lines(digest: Digest) -> list:
    out = []
    for gap in digest.gaps:
        if gap.metric == "quest turn-ins":
            out.append(
                "%s has %d quest turn-ins. %s %s on %d - %s."
                % (
                    gap.leader,
                    int(gap.leader_value),
                    _and_list(gap.laggards),
                    "is" if len(gap.laggards) == 1 else "are",
                    int(gap.laggard_value),
                    gap.note,
                )
            )
        elif gap.metric == "gold":
            out.append(
                "%s %s under a gold (%s, against %s's %.1fg) - %s."
                % (
                    _and_list(gap.laggards),
                    "is" if len(gap.laggards) == 1 else "are",
                    "%.1fg" % gap.laggard_value,
                    gap.leader,
                    gap.leader_value,
                    gap.note,
                )
            )
        else:
            out.append(
                "%s is %d, %s %d. %s."
                % (
                    gap.leader,
                    int(gap.leader_value),
                    _and_list(gap.laggards),
                    int(gap.laggard_value),
                    gap.note[0].upper() + gap.note[1:],
                )
            )
    return out


def _behind_lines(digest: Digest) -> list:
    """questbook's own words, one per member who has work to catch up on.

    questbook.say() is the sentence, unchanged. Rewriting it here would put
    the same judgement in two places and let the digest and the council
    disagree about who is behind, in front of the person who asked.
    """
    ledger = digest.ledger
    if ledger is None:
        return []
    out = []
    for name in digest.names:
        if ledger.behind.get(name) or ledger.stalled.get(name):
            out.append(questbook.say(ledger, name))
    return out


def _moment_lines(digest: Digest) -> list:
    """What actually happened, from rows that carry a time."""
    if not digest.moments:
        return []
    by_kind: dict = {}
    for m in digest.moments:
        by_kind.setdefault(m.kind, []).append(m)

    out = []
    for kind in sorted(by_kind):
        rows = by_kind[kind]
        if kind == "said":
            quotes = rows[-MAX_QUOTES:]
            out.append("They spoke %s. The last of it:" % _plural(len(rows), "time"))
            out.extend('  %s - "%s"' % (m.name, m.text) for m in quotes)
            continue
        named = [m for m in rows if m.text][:MAX_NAMED]
        if named:
            out.append(
                "%s: %s."
                % (
                    kind.replace("_", " ").capitalize(),
                    "; ".join("%s %s" % (m.name, m.text) for m in named),
                )
            )
        else:
            out.append("%s: %d." % (kind.replace("_", " ").capitalize(), len(rows)))
    return out


def _sources(digest: Digest) -> str:
    used = [SOURCE_SNAPSHOT, SOURCE_CHARACTERS, SOURCE_SAVED]
    if digest.measured:
        used.append(SOURCE_SAMPLE)
    seen = {m.source for m in digest.moments}
    used.extend(sorted(seen))
    # dict.fromkeys and not set(): the order is the order of confidence, and
    # a set would reshuffle it differently on every run.
    return "Sources: " + "; ".join(dict.fromkeys(used)) + "."


def render(digest: Digest) -> str:
    """The whole account, as something a person would read.

    Plain sentences, like questbook.say and quests.say_remaining. The family's
    register belongs to the voice layer; written in character here it would
    live in two places and drift. Every number in this text came in as a fact
    and none of it is computed twice.
    """
    if not digest.standings:
        return (
            "Nobody is in the world and nothing was sampled, so there is "
            "nothing to tell you about %s." % digest.window.describe()
        )

    lines = ["The family, over %s." % digest.window.describe(), ""]
    lines.extend(_standing_line(digest, s) for s in digest.standings)

    if not digest.measured:
        lines.extend(["", _no_baseline_line(digest)])

    moments = _moment_lines(digest)
    if moments:
        lines.append("")
        lines.append("What is on the record for that stretch:")
        lines.extend(moments)

    gap_lines = _gap_lines(digest)
    if gap_lines:
        lines.append("")
        lines.append("What you should know without asking:")
        lines.extend(gap_lines)

    behind = _behind_lines(digest)
    if behind:
        lines.append("")
        lines.append("Catching up:")
        lines.extend(behind)

    lines.extend(["", _sources(digest)])
    return "\n".join(lines)


def build_prompt(digest: Digest, *, speaker: str = "") -> str:
    """Ask one member of the family to open the report in their own voice.

    THE MODEL GETS NO NUMBERS TO INVENT. It is handed the finished account and
    asked for ONE sentence of greeting on top of it - the same contract as
    events.build_batch_prompt, where the LLM voices what happened and never
    decides what happened. The account itself is rendered above and posted
    whatever the model says, so an outage costs a greeting and nothing else.
    """
    speaker = speaker or bonds.head_of_family()
    bond = bonds.bond_of(speaker)
    persona = ("\n%s\n" % bond.persona) if bond and bond.persona else ""
    return (
        "You are %s, a character in World of Warcraft.\n%s"
        "The Overseer has been away and asks how the family has been over %s. "
        "Here is the true account, which will be shown to him in full:\n\n"
        "%s\n\n"
        "Write ONE short sentence, in character, greeting him and pointing at "
        "the thing in that account that matters most. Invent no numbers and no "
        "events. Answer with the sentence only, no quotes and no preamble."
        % (speaker, persona, digest.window.describe(), render(digest))
    )


def opening_line(digest: Digest, content: str = "", *, speaker: str = "") -> str:
    """The greeting, from the model or from a template. Never empty.

    Same defensive contract as events.voice_events: whatever comes back, a
    usable line comes out, because the report must not depend on the gateway
    being up.
    """
    speaker = speaker or bonds.head_of_family()
    said = " ".join((content or "").split())[:200]
    if said:
        return said
    worst = digest.gaps[0] if digest.gaps else None
    if worst is not None:
        return "%s: the family stands, but %s %s behind on %s." % (
            speaker,
            _and_list(worst.laggards),
            "is" if len(worst.laggards) == 1 else "are",
            worst.metric,
        )
    return "%s: the family stands." % speaker
