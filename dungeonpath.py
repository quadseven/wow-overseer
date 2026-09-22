"""The order to run dungeons in, for each family, and what each step holds.

THE PAGE THIS REPLACES RANKED 74 DUNGEONS BY GEAR ALONE, so a level 60 family
saw Ahn'Qiraj Temple (a 40 player raid) first and Ragefire Chasm somewhere in
the middle. That answers "where is the most loot" and not the question the
operator asks, which is "what do we run next, and after that". This module
answers the second one: a PATH, lowest level band first, with each family
placed on it by its weakest member, and the gear count riding along on each
step rather than deciding the order.

THE ORDER IS A CURATED BAND TABLE, NOT THE ACCESS TABLE. The world's
`dungeon_access_template` gives a door minimum for every map and a maximum of 0
for all of them, and several door minimums are far below where a party
survives (Blackrock Depths lets a level 40 in; council.PLACES explains why 52
is the honest number). Where council.PLACES already recommends a level for a
map, that number is the band's floor here, so the council and this page cannot
disagree about when a family is ready. The ceilings and the maps council does
not cover are this module's, written down in PATH.

WHAT THE OVERSEER CAN RUN comes from jobs.PORTAL_KEYWORDS, the list of portal
rows mod-overseer carries. A dungeon without one can still be run by hand, and
the page says which is which rather than implying the overseer can drive them
all.

Every sentence the page prints is written here, so a Python test can read it.
The page renders and decides nothing (test_dungeon_tab.ThePageDecidesNothing).
"""

from __future__ import annotations

from dataclasses import dataclass

import council
import jobs

DUNGEON = "dungeon"
RAID = "raid"

ALLIANCE = "Alliance"
HORDE = "Horde"


@dataclass(frozen=True)
class Step:
    map_id: int
    low: int
    high: int
    kind: str = DUNGEON
    players: int = 5
    # The faction whose capital the entrance stands inside, or "" for none.
    # The other faction cannot walk in, so the step is off that family's path.
    inside: str = ""
    city: str = ""
    # The raids' own rows in the access table are named by a free-text comment
    # ("Molten Core - 40man"), so the path names them itself.
    name: str = ""

    @property
    def floor(self) -> int:
        """council.PLACES's recommendation where it has one, so the two views
        agree about when a family is ready; this table's own number otherwise."""
        return int(council.PLACES.get(self.map_id, self.low))


# THE PATH, in the order it is walked. Dungeons by level band, then the classic
# raids in the order they opened. Every raid is level 60: on this realm Onyxia's
# Lair and Naxxramas were rebuilt for level 80, so they are not on a classic
# path and are left to the off-path list with the rest of Outland and
# Northrend.
PATH: tuple[Step, ...] = (
    Step(389, 13, 21, inside=HORDE, city="Orgrimmar"),  # Ragefire Chasm
    Step(43, 17, 24),  # Wailing Caverns
    Step(36, 17, 26),  # The Deadmines
    Step(33, 22, 30),  # Shadowfang Keep
    Step(48, 24, 32),  # Blackfathom Deeps
    Step(34, 24, 32, inside=ALLIANCE, city="Stormwind"),  # The Stockade
    Step(189, 28, 45),  # Scarlet Monastery
    Step(90, 29, 38),  # Gnomeregan
    Step(47, 30, 40),  # Razorfen Kraul
    Step(129, 33, 47),  # Razorfen Downs
    Step(70, 34, 51),  # Uldaman
    Step(209, 36, 54),  # Zul'Farrak
    Step(349, 45, 55),  # Maraudon
    Step(109, 50, 60),  # Sunken Temple
    Step(230, 52, 60),  # Blackrock Depths
    Step(229, 55, 60),  # Blackrock Spire
    Step(429, 56, 60),  # Dire Maul
    Step(289, 58, 60),  # Scholomance
    Step(329, 58, 60),  # Stratholme
    Step(409, 60, 60, RAID, 40, name="Molten Core"),
    Step(469, 60, 60, RAID, 40, name="Blackwing Lair"),
    Step(309, 60, 60, RAID, 20, name="Zul'Gurub"),
    Step(509, 60, 60, RAID, 20, name="Ruins of Ahn'Qiraj"),
    Step(531, 60, 60, RAID, 40, name="Temple of Ahn'Qiraj"),
)

PATH_MAPS = tuple(step.map_id for step in PATH)

# Which map each portal keyword opens. Keyed by the same words
# jobs.PORTAL_KEYWORDS holds, and a test holds the two key sets equal, so a
# portal added in jobs.py without a map here fails loudly rather than reading
# as "cannot run it".
PORTAL_MAPS = {
    "deadmines": 36,
    "shadowfang": 33,
    "scarlet": 189,
    "scarlet-library": 189,
    "scarlet-armory": 189,
    "scarlet-cathedral": 189,
    "stockades": 34,
    "wailing": 43,
}

# What mod-overseer's own portal table says about a row that exists and still
# cannot be run end to end, in its words cut short. Said beside the "can run it"
# line, because a portal row is not the same claim as a run that works.
PORTAL_CAVEATS = {
    43: (
        "mod-overseer's portal table notes the entrance is on Kalimdor and a "
        "family living on the Eastern Kingdoms has no crossing yet, so a run "
        "is refused until one exists"
    ),
    189: (
        "the Armory and Cathedral doors need the Scarlet Key, which drops in "
        "the Library, so the Library wing comes first"
    ),
}

# Where a family stands on a step.
BEHIND = "behind"  # the band tops out below the weakest member
NOW = "now"  # the weakest member is in the band, or near enough
NEXT = "next"  # the one "now" step the page points at
AHEAD = "ahead"  # the band starts too far above the weakest member
OFF = "off"  # the entrance is inside the other faction's capital

STATE_WORDS = {
    BEHIND: "outgrown",
    NOW: "in range",
    NEXT: "next",
    AHEAD: "later",
    OFF: "not reachable",
}
STATE_TONES = {BEHIND: "", NOW: "", NEXT: "up", AHEAD: "unsure", OFF: "no"}

# How many members to keep per slot in a step's detail. The family cards on the
# old page carried every gain with its tooltip, and a level 12 family gains on
# almost everything, so the list is cut to the best piece per slot; the count
# of what was cut is kept and said.
_PER_SLOT = 1

# How many steps the family and guild upgrade summaries name.
_SUMMARY_STEPS = 3


def portals_by_map() -> dict:
    """map id -> the portal keywords that open it, in jobs.PORTAL_KEYWORDS."""
    out: dict = {}
    for keyword in sorted(jobs.PORTAL_KEYWORDS):
        map_id = PORTAL_MAPS.get(keyword)
        if map_id is not None:
            out.setdefault(map_id, []).append(keyword)
    return out


def _plural(count: int, one: str, many: str | None = None) -> str:
    return "%d %s" % (count, one if count == 1 else (many or one + "s"))


def _names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def faction_of(race_ids: list[int], alliance: set, horde: set) -> str:
    """The family's faction by the races its members were made with.

    A family is one faction by construction (the game will not group them
    otherwise), so the majority is the answer and a tie or nothing is "".
    """
    a = len([r for r in race_ids if r in alliance])
    h = len([r for r in race_ids if r in horde])
    if a > h:
        return ALLIANCE
    if h > a:
        return HORDE
    return ""


def _band(step: Step) -> str:
    if step.floor == step.high:
        return "level %d" % step.high
    return "levels %d to %d" % (step.floor, step.high)


def _state(step: Step, weakest: int | None, faction: str) -> str:
    if step.inside and faction and step.inside != faction:
        return OFF
    if weakest is None:
        return AHEAD
    if step.high < weakest:
        return BEHIND
    if weakest + council.NEAR_ENOUGH < step.floor:
        return AHEAD
    return NOW


def _state_line(
    step: Step, state: str, weakest_name: str, weakest: int | None, faction: str
) -> str:
    if state == OFF:
        return (
            "Its entrance is inside %s, which the %s cannot walk into, so "
            "it is not on this family's path." % (step.city, faction)
        )
    if weakest is None:
        return "Nothing here knows the family's levels, so it cannot place them."
    if state == BEHIND:
        return (
            "Outgrown: the band tops out at %d and even %s, the lowest of "
            "them, is %d." % (step.high, weakest_name, weakest)
        )
    if state == AHEAD:
        return (
            "Later: the band starts at %d and %s, the lowest of them, is "
            "%d, so %s to go."
            % (
                step.floor,
                weakest_name,
                weakest,
                _plural(step.floor - weakest, "level"),
            )
        )
    if weakest < step.floor:
        return (
            "In range, just: the band starts at %d and %s is %d, which is "
            "near enough to try." % (step.floor, weakest_name, weakest)
        )
    return "In range: every one of them is at least %d." % step.floor


def _overseer(step: Step, portals: dict) -> dict:
    keywords = portals.get(step.map_id, [])
    if keywords:
        caveat = PORTAL_CAVEATS.get(step.map_id)
        return {
            "can": True,
            "line": (
                "The overseer can run this one: mod-overseer has a "
                "portal for it (%s)%s."
                % (", ".join(keywords), "; " + caveat if caveat else "")
            ),
        }
    return {
        "can": False,
        "line": (
            "The overseer cannot run this one yet: mod-overseer has no "
            "portal for it, so a dungeon goal naming it is refused "
            "and it has to be run by hand."
        ),
    }


def _runs(map_id: int, rows: list[dict]) -> str:
    mine = [r for r in rows if int(r.get("map_id") or 0) == map_id]
    if not mine:
        return "This family has never started a run here."
    cleared = len([r for r in mine if str(r.get("outcome") or "") == "complete"])
    done = (
        "never cleared it"
        if not cleared
        else "cleared it once"
        if cleared == 1
        else "cleared it %d times" % cleared
    )
    return "This family has started %s here and %s." % (_plural(len(mine), "run"), done)


def _trim(found: dict) -> dict:
    """One member's gains cut to the best piece per slot, with what was cut
    counted, because a level 12 character gains on nearly everything."""
    kept: list = []
    per_slot: dict = {}
    for gain in found["gains"]:
        seen = per_slot.get(gain["slot"], 0)
        if seen < _PER_SLOT:
            kept.append(gain)
        per_slot[gain["slot"]] = seen + 1
    cut = len(found["gains"]) - len(kept)
    trimmed = dict(found)
    trimmed["gains"] = kept
    trimmed["more_line"] = (
        ""
        if not cut
        else "and %s for the same slots, not shown" % _plural(cut, "lesser piece")
    )
    return trimmed


def _family_gain_line(card: dict | None) -> str:
    if card is None:
        return "The world database lists no boss loot here for this page to compare."
    return card["line"][:1].upper() + card["line"][1:] + "."


def _guild_line(guild: str, counts: dict | None) -> str:
    if not guild or counts is None or not counts.get("of"):
        return ""
    if not counts.get("pieces"):
        return "The guild %s: no boss loot is listed here to compare." % guild
    return "The guild %s: %d of %d members would gain something here." % (
        guild,
        len(counts["gainers"]),
        counts["of"],
    )


def _chips(
    step: Step,
    state: str,
    overseer: dict,
    card: dict | None,
    size: int,
    counts: dict | None,
    guild: str,
) -> list[dict]:
    out = [
        {"text": STATE_WORDS[state], "tone": STATE_TONES[state]},
        {"text": _band(step), "tone": ""},
    ]
    if step.kind == RAID:
        out.append({"text": "raid, %d players" % step.players, "tone": ""})
    if state != OFF:
        out.append(
            {
                "text": (
                    "overseer can run it"
                    if overseer["can"]
                    else "overseer cannot run it yet"
                ),
                "tone": "up" if overseer["can"] else "no",
            }
        )
    gainers = len(card["gainers"]) if card else 0
    if size:
        out.append(
            {
                "text": "family: %d of %d gain" % (gainers, size),
                "tone": "up" if gainers else "",
            }
        )
    if guild and counts and counts.get("of"):
        n = len(counts["gainers"])
        out.append(
            {
                "text": "%s: %d of %d gain" % (guild, n, counts["of"]),
                "tone": "up" if n else "",
            }
        )
    return out


def _pick_next(steps: list[dict]) -> None:
    """Mark one in-range step as next: the first on the path that holds
    something for somebody, or the first in range when none does."""
    live = [s for s in steps if s["state"] == NOW]
    chosen = next((s for s in live if s["family_gainers"]), None)
    if chosen is None and live:
        chosen = live[0]
    if chosen is not None:
        chosen["state"] = NEXT
        chosen["chips"][0] = {"text": STATE_WORDS[NEXT], "tone": STATE_TONES[NEXT]}


def _next_short(steps: list[dict]) -> str:
    chosen = next((s for s in steps if s["state"] == NEXT), None)
    if chosen is not None:
        return chosen["name"]
    ahead = next((s for s in steps if s["state"] == AHEAD), None)
    if ahead is not None:
        return "%s, from level %d" % (ahead["name"], ahead["floor"])
    return "nothing left on the path"


def _next_line(steps: list[dict], weakest_name: str, weakest: int | None) -> str:
    chosen = next((s for s in steps if s["state"] == NEXT), None)
    if chosen is not None:
        how = (
            "and the overseer can run it"
            if chosen["overseer"]["can"]
            else "but the overseer cannot run it yet, so it is a run by hand"
        )
        if chosen["family_gainers"]:
            why = "%d of them would gain something there" % chosen["family_gainers"]
        else:
            why = "nothing in range holds an upgrade, so this is simply the first in range"
        return "Next: %s (%s). %s, %s." % (
            chosen["name"],
            chosen["band"],
            why[:1].upper() + why[1:],
            how,
        )
    ahead = next((s for s in steps if s["state"] == AHEAD), None)
    if ahead is not None and weakest is not None:
        return "Next: %s, once %s reaches %d (%s is %d now)." % (
            ahead["name"],
            weakest_name,
            ahead["floor"],
            weakest_name,
            weakest,
        )
    return "Every step on the path is behind this family."


def _upgrades_line(steps: list[dict], key: str, who: str, raids: bool = True) -> str:
    """The steps in range that hold the most for `who`, best first.

    A raid is left out of the FAMILY's summary: five people do not clear a
    forty player raid, so its loot is not an upgrade a family can go and get.
    """
    live = [
        s for s in steps if s["state"] in (NOW, NEXT) and (raids or s["kind"] != RAID)
    ]
    if not live:
        return "No step is in range for %s yet." % who
    pool = [s for s in live if s[key]]
    if not pool:
        return "Nothing on the steps in range is an upgrade for %s." % who
    pool.sort(key=lambda s: (-s[key], -s.get("family_total", 0), s["rank"]))
    named = ["%s (%d)" % (s["name"], s[key]) for s in pool[:_SUMMARY_STEPS]]
    return "Most upgrades for %s in range, by how many would gain: %s." % (
        who,
        _names(named),
    )


@dataclass(frozen=True)
class _Family:
    """What every step of one family's path is judged against."""

    faction: str
    size: int
    weakest: int | None
    weakest_name: str
    guild: str
    guild_counts: dict
    run_rows: list
    portals: dict
    names: dict


def _weakest(members: list[dict]) -> tuple[int | None, str]:
    levelled = [m for m in members if m.get("level")]
    if not levelled:
        return None, ""
    low = min(levelled, key=lambda m: int(m["level"]))
    return int(low["level"]), low["name"]


def _step_name(step: Step, card: dict | None, names: dict) -> str:
    return (
        step.name
        or names.get(step.map_id)
        or (card.get("name") if card else None)
        or "map %d" % step.map_id
    )


def _step(rank: int, step: Step, card: dict | None, fam: _Family) -> dict:
    """One step on the path, for one family."""
    state = _state(step, fam.weakest, fam.faction)
    overseer = _overseer(step, fam.portals)
    counts = fam.guild_counts.get(step.map_id)
    gained = card["gainers"] if card else []
    return {
        "rank": str(rank),
        "map_id": step.map_id,
        "name": _step_name(step, card, fam.names),
        "kind": step.kind,
        "band": _band(step),
        "floor": step.floor,
        "state": state,
        "state_line": _state_line(
            step, state, fam.weakest_name, fam.weakest, fam.faction
        ),
        "overseer": overseer,
        "runs_line": _runs(step.map_id, fam.run_rows),
        "raid_line": (
            "A raid for %d players: that is the guild's job, not "
            "a family's, and the Raid tab tracks it." % step.players
            if step.kind == RAID
            else ""
        ),
        "family_line": _family_gain_line(card),
        "family_gainers": len(gained),
        "family_total": card["total"] if card else 0,
        "guild_line": _guild_line(fam.guild, counts),
        "guild_gainers": len(counts["gainers"]) if counts else 0,
        "members": [_trim(found) for found in (card["members"] if card else [])],
        "chips": _chips(step, state, overseer, card, fam.size, counts, fam.guild),
    }


def _fold(steps: list[dict]) -> tuple[list[dict], list[dict]]:
    """THE STEPS ALREADY BEHIND THEM FOLD AWAY. A level 60 family has thirteen
    outgrown dungeons before the first one that matters, and scrolling past
    them to reach "next" is the old page's problem in a new order. They stay
    on the payload, in order, so the path is still whole when opened."""
    first_live = next(
        (i for i, s in enumerate(steps) if s["state"] not in (BEHIND, OFF)), len(steps)
    )
    return steps[:first_live], steps[first_live:]


def _off_path(cards: dict) -> list[dict]:
    """Maps outside the classic path that still hold something, most first."""
    found = [
        card
        for map_id, card in cards.items()
        if map_id not in PATH_MAPS and card["gainers"]
    ]
    found.sort(key=lambda c: (-len(c["gainers"]), -c["total"], c["name"]))
    return found


def _who_line(members: list[dict], faction: str, guild: str) -> str:
    who = ", ".join("%s %s" % (m["name"], m.get("level") or "?") for m in members)
    return "%s%s%s." % (
        faction + ": " if faction else "",
        who or "nobody on the roster",
        (", in the guild %s" % guild) if guild else ", in no guild",
    )


def build_family_path(
    head: str,
    faction: str,
    members: list[dict],
    plan: dict,
    guild: str,
    guild_counts: dict,
    run_rows: list[dict],
    portals: dict,
    names: dict | None = None,
) -> dict:
    """One family's path.

    head          the family's name, which is its head's name
    faction       ALLIANCE, HORDE or "" when the races did not say
    members       [{"name", "level"}] for the family
    plan          dungeonplan.build_dungeonplan for this family
    guild         the guild's name, "" for none
    guild_counts  dungeonplan.gainer_counts for the guild, over PATH_MAPS
    run_rows      overseer_dungeon_run rows led by this family
    portals       portals_by_map()
    """
    cards = {int(card["map_id"]): card for card in plan.get("dungeons", [])}
    weakest, weakest_name = _weakest(members)
    fam = _Family(
        faction,
        len(members),
        weakest,
        weakest_name,
        guild,
        guild_counts,
        run_rows,
        portals,
        names or {},
    )
    steps = [
        _step(rank, step, cards.get(step.map_id), fam)
        for rank, step in enumerate(PATH, start=1)
    ]
    _pick_next(steps)
    behind, steps = _fold(steps)
    off_path = _off_path(cards)
    return {
        "family": head,
        "title": "%s's family" % head if head else "The family",
        "faction": faction,
        "who_line": _who_line(members, faction, guild),
        "next_line": _next_line(steps, weakest_name, weakest),
        "next_short": _next_short(steps),
        "family_upgrades": _upgrades_line(
            steps, "family_gainers", "the family", raids=False
        ),
        "guild_upgrades": (
            _upgrades_line(steps, "guild_gainers", "the guild " + guild)
            if guild and guild_counts
            else ""
        ),
        "steps": steps,
        "behind": behind,
        "behind_line": (
            "%s behind them, outgrown or out of reach: open to see "
            "the start of the path." % _plural(len(behind), "step")
            if behind
            else ""
        ),
        "off_path_line": (
            "Off the path: %s outside the classic path (Outland, Northrend, "
            "heroics) hold something for this family. They are listed for "
            "completeness, not as a next step."
            % _plural(len(off_path), "dungeon or raid", "dungeons and raids")
            if off_path
            else ""
        ),
        "off_path": [
            {"name": c["name"], "line": c["line"], "chips": c["chips"]}
            for c in off_path
        ],
    }


ORDER = (
    "The path runs lowest level band first, then the classic raids in the "
    "order they opened. The band is where a party of that level survives, not "
    "the door minimum, and where the council already recommends a level for a "
    "dungeon that number is the band's floor. Each family is placed on it by "
    "its weakest member: a band that tops out below that level is outgrown, "
    "and one that starts more than %d levels above it is later. Upgrades ride "
    "along on each step and never change the order; the next step is the "
    "first one in range that holds something for somebody." % council.NEAR_ENOUGH
)


def runnable_line(portals: dict, names: dict) -> str:
    """Which dungeons the overseer can drive today, said once for the page."""
    if not portals:
        return "The overseer cannot run any dungeon on its own yet."
    listed = []
    for map_id in sorted(
        portals, key=lambda m: PATH_MAPS.index(m) if m in PATH_MAPS else 999
    ):
        name = names.get(map_id) or "map %d" % map_id
        wings = len(portals[map_id])
        listed.append(name if wings == 1 else "%s (%d wings)" % (name, wings))
    return (
        "The overseer can run %s on its own today, through the portals "
        "mod-overseer carries: %s. Every other step is marked as one it "
        "cannot run yet." % (_plural(len(listed), "dungeon"), _names(listed))
    )


BASIS = (
    "The families are the roster's own family column, and each is placed by "
    "the lowest level among its members. The bands are this module's PATH "
    "table, floored by the council's recommendations. What the overseer can "
    "run is the list of dungeon portals mod-overseer carries. Runs are this "
    "family's rows in the dungeon run ledger, led by any of its members, and "
    "a run counts as cleared only when its outcome says complete. The guild "
    "count uses the same upgrade verdict as the family's, over every member of "
    "the guild. Each character's list is cut to the best piece per slot, and "
    "the cut is counted on the card."
)


def headline(families: list[dict]) -> str:
    """The one line at the top: what each family should run next."""
    if not families:
        return "the roster names no family, so there is no path to draw"
    return " ".join(
        "Next for %s: %s." % (f["title"], f["next_short"]) for f in families
    )
