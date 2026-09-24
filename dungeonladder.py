"""The dungeon ladder: every door before Molten Core, as one family stands to it.

WHY THIS EXISTS. The campaign planner (campaignplan.py) answers "which run
next", and Jev answers it again over the same runs. Neither says what a person
reading the Dungeons tab asks first: of every dungeon before the raid, which
can this family run now, which are behind it, which are ahead, which belong
to the other faction, and which wait for a crossing or a key. The ladder is
that answer, one rung per door, lowest band first.

PER FACTION AND PER LEVEL, AND NOTHING WRITTEN TWICE. The rungs are
campaignplan.RUNS, every door mod-overseer has a portal for. Whether a rung is
open is the planner's own refusal (campaignplan.refusal_kinds), which is
council.door_refusal_kind for the faction, the level, withheld doors and the
crossing, and campaignplan's rule for outgrown runs and key doors. So the
Horde's ladder has Ragefire Chasm and the Alliance's does not, a door across
the sea opens the moment crossing.py says the crossing can be made, and a
level 60 family keeps a lower dungeon on its ladder while its loot still
upgrades somebody. The bosses' levels are the world's own
(campaignplan.BOSSES_SQL), said beside the band so a reader can check the fit.

PURE MODULE: facts in, a dict of sentences out. The page sets textContent.
"""

from __future__ import annotations

import council
import campaignplan

# Where a family stands on one rung, as the page's class and the word it says.
OPEN = "open"
DONE = "done"
AHEAD = "ahead"
OUTGROWN = "outgrown"
OTHER_SIDE = "other-side"
ACROSS = "across"
LOCKED = "locked"
WITHHELD = "withheld"
UNKNOWN = "unknown"

STATE_WORDS = {
    OPEN: "open now",
    DONE: "done for now",
    AHEAD: "ahead",
    OUTGROWN: "outgrown",
    OTHER_SIDE: "the other faction's",
    ACROSS: "across the sea",
    LOCKED: "locked",
    WITHHELD: "withheld",
    UNKNOWN: "cannot be said",
}

_BY_KIND = {
    council.REFUSED_LEVEL: AHEAD,
    campaignplan.REFUSED_OUTGROWN: OUTGROWN,
    council.REFUSED_FACTION: OTHER_SIDE,
    council.REFUSED_CROSSING: ACROSS,
    campaignplan.REFUSED_LOCKED: LOCKED,
    council.REFUSED_WITHHELD: WITHHELD,
}

# The order the summary line counts the closed rungs in.
_SUMMARY = (AHEAD, ACROSS, LOCKED, OTHER_SIDE, WITHHELD, OUTGROWN, DONE, UNKNOWN)


def _levels(low: int, high: int) -> str:
    return "%d" % low if low == high else "%d to %d" % (low, high)


def _open_line(option) -> str:
    parts = [
        "%d run%s would be queued, %s"
        % (
            option.runs,
            "" if option.runs == 1 else "s",
            option.why,
        )
    ]
    if option.fit:
        parts.append(option.fit)
    if option.expected is not None and option.capped:
        parts.append(
            "%.1f item levels a run expected over every slot" % option.expected
        )
    if option.progress:
        parts.append(option.progress)
    if option.crossing:
        parts.append("across a continent crossing")
    parts.append("record: " + option.history)
    if option.troubled:
        parts.append("the family keeps dying here, so it goes behind the rest")
    return "; ".join(parts) + "."


def rungs(facts: campaignplan.Facts) -> list:
    """Every door, lowest band first, with where the family stands on it."""
    refused = campaignplan.refusal_kinds(facts)
    offered = {o.keyword: o for o in campaignplan.options(facts)}
    known_bosses = facts.bosses or {}
    out = []
    for run in campaignplan.RUNS:
        bosses = known_bosses.get(run.map_id)
        if run.keyword in offered:
            state, line = OPEN, _open_line(offered[run.keyword])
        elif run.keyword in refused:
            kind, why = refused[run.keyword]
            state, line = _BY_KIND.get(kind, UNKNOWN), why[:1].upper() + why[1:] + "."
        else:
            done = int(facts.done.get(run.keyword, 0))
            state = DONE
            line = "Run to its count for now: %d completed." % done
        levels = _levels(run.floor, run.ceiling)
        said_bosses = "" if bosses is None else _levels(*bosses)
        continent = council.CONTINENT_NAMES.get(council.continent_of(run.map_id), "")
        detail = "Levels %s" % levels
        if said_bosses:
            detail += "; its bosses %s" % said_bosses
        if continent:
            detail += "; on %s" % continent
        out.append(
            {
                "keyword": run.keyword,
                "place": run.place,
                "levels": levels,
                "bosses": said_bosses,
                "continent": continent,
                "state": state,
                "word": STATE_WORDS[state],
                "head": "%s: %s" % (run.place, STATE_WORDS[state]),
                "detail": detail + ".",
                "line": line,
            }
        )
    return out


def _faction(facts: campaignplan.Facts) -> str:
    rows = list(facts.level_rows)
    return council._faction(rows, [str(r.get("name") or "") for r in rows])


def view(facts: campaignplan.Facts | None) -> dict:
    """The Dungeons tab's ladder for one family: a title, a summary line and
    the rungs. Empty rungs and a line saying why when nothing can be read."""
    if facts is None:
        return {"title": "", "line": "", "rungs": []}
    who, level = facts.weakest
    if not level:
        return {
            "title": "The dungeon ladder",
            "line": "Nobody's level can be read, so the ladder cannot be drawn.",
            "rungs": [],
        }
    faction = _faction(facts) or "family's"
    steps = rungs(facts)
    counts: dict = {}
    for rung in steps:
        counts[rung["state"]] = counts.get(rung["state"], 0) + 1
    opened = [r["place"] for r in steps if r["state"] == OPEN]
    said = ["Open now: %s." % ("; ".join(opened) if opened else "nothing")]
    closed = [
        "%s %d" % (STATE_WORDS[state], counts[state])
        for state in _SUMMARY
        if counts.get(state)
    ]
    if closed:
        said.append("Closed: %s." % ", ".join(closed))
    return {
        "title": "The %s ladder, with %s the weakest at %d" % (faction, who, level),
        "line": " ".join(said),
        "rungs": steps,
    }
