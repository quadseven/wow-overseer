"""The Eye: what this realm actually is, tier by tier.

Pure module, same seam as agenda.py and achievements.py: rows in, a rollup
out. map_server.py reads the rows and does nothing else.

WHY THIS VIEW EXISTS AND WHY IT IS MOSTLY ZEROS. Every server dashboard ever
drawn shows population curves, guild ladders and a world map with faction
percentages. This realm has one family on it. A dashboard of that shape would
be five real numbers and a dozen invented ones, and the invented ones are the
part a reader would remember.

So the rollup is a LADDER OF TIERS and each tier answers two questions: is it
real, and if it is not, what would turn it on. A tier that is off says the
condition rather than drawing an empty chart, because "no guild exists, and
here is what would make one" is a fact, while an empty guild table with an
axis on it is a picture of a server that does not exist.

The counts are all MEASURED. The guild tier says zero because the guild table
was counted and had nothing in it, not because somebody remembered that no
guild had been made. A realm that grows a guild turns that tier on by itself,
with no change here.
"""

from __future__ import annotations

from datetime import datetime

# The three things a tier can be. Status words, so the page sets them in the
# mono face and never has to decide what to call a tier itself.
ON = "ON"
OFF = "OFF"
PARTIAL = "PARTIAL"

# The hue each state is drawn in. Chosen here and not in the page, because
# "off is the alarming one" is a judgement about the state and not about the
# stylesheet - the page's job is to know what vermilion looks like on the
# ground it is painting, and it has two grounds to know that on. Token names,
# never colours.
STATE_HUES = {ON: "green", PARTIAL: "amber", OFF: "vermilion"}

# Tier names, in the order they are drawn: smallest real thing first, largest
# absent thing last. The order is the argument - it is a ladder, and a reader
# should be able to see where the real stops.
CHARACTER = "CHARACTER"
FAMILY = "FAMILY"
PARTY = "PARTY"
GUILD = "GUILD"
REALM = "REALM"

# A guild charter needs this many signatures in the 3.3.5 client. Named rather
# than inlined because it is the exact condition the GUILD tier reports as its
# switch, and a realm this small may not have the characters to sign one.
CHARTER_SIGNATURES = 10

# Below this the realm is one family and whoever happens to be standing next
# to them; at or above it there is a population worth a number. Two families
# is the smallest thing that is not "the family".
CROWD = 10


def _iso(when: datetime | None) -> str | None:
    return when.isoformat() if when else None


def _count(rows: list[dict], key: str) -> int:
    """The single number a COUNT(*) row carries, or 0 when the read degraded.

    The adapter hands [] for a table this realm's schema does not have, and a
    tier that cannot be counted must read as "nothing found" rather than
    taking the whole view out with a KeyError.
    """
    if not rows:
        return 0
    value = rows[0].get(key)
    return int(value or 0)


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def tier(name: str, state: str, value: str, headline: str,
         switch: str = "") -> dict:
    """One rung. `switch` is what would turn it on, and only an off rung has one.

    An ON tier carrying a switch would read as a suggestion to change
    something that already works, so the field is emptied here by
    construction rather than by whoever builds the dict remembering.
    """
    return {
        "tier": name,
        "state": state,
        "hue": STATE_HUES.get(state, "muted"),
        "value": value,
        "headline": headline,
        "switch": switch if state != ON else "",
    }


def character_tier(family_rows: list[dict], realm_characters: int) -> dict:
    """The characters the module knows by name, and how much of the realm they are."""
    held = len(family_rows)
    if not held:
        return tier(
            CHARACTER, OFF, "0",
            "The module holds no characters on this realm.",
            "One character saved by the module. Until then every tier above "
            "this one is counting nothing.",
        )
    rest = max(realm_characters - held, 0)
    headline = "%d %s the module knows by name" % (
        held, _plural(held, "character", "characters"))
    if rest:
        headline += ", of %d on the realm" % realm_characters
    else:
        headline += ", and they are the whole realm"
    return tier(CHARACTER, ON, str(held), headline + ".")


def family_tier(family_rows: list[dict]) -> dict:
    """One family. Not a count of families - there is one, and it is named."""
    names = sorted(str(row["name"]) for row in family_rows)
    if not names:
        return tier(
            FAMILY, OFF, "0",
            "No family is in the world.",
            "The five characters logged in and saved by the module.",
        )
    return tier(FAMILY, ON, "1",
                "One family: %s." % ", ".join(names))


def party_tier(snapshot_rows: list[dict], family: set) -> dict:
    """Whether the family is actually together, from the leader they follow.

    A party is the one social tier above a character that this realm really
    has, so it is reported as a real thing and not as an absence - but it is
    reported HONESTLY: five characters behind two different leaders are not
    one party, and calling that a party would be the invention this view
    exists to refuse.

    Read off the LIVE snapshot and not off the saved rows, because a party is
    the one thing on this ladder that stops existing when everybody logs out.
    """
    leaders = {str(row.get("group_leader") or "") for row in snapshot_rows
               if str(row.get("name") or "") in family}
    leaders.discard("")
    if not leaders:
        return tier(
            PARTY, OFF, "0",
            "Nobody is following anybody.",
            "A party leader in the snapshot. The module writes one the moment "
            "the family groups up, and writes none while they are logged out.",
        )
    if len(leaders) > 1:
        return tier(
            PARTY, PARTIAL, str(len(leaders)),
            "%d groups, not one: the family is split." % len(leaders),
            "The family behind one leader again.",
        )
    return tier(PARTY, ON, "1",
                "One party, behind %s." % sorted(leaders)[0])


def guild_tier(guilds: int, realm_characters: int) -> dict:
    """The tier that is off, and the reason this view is shaped as a ladder.

    The switch is a real condition and not an aspiration: a charter needs
    CHARTER_SIGNATURES signatures, and this realm may not have that many
    characters at all. Saying so is more useful than an empty guild roster,
    because it names the thing that has to change first.
    """
    if guilds:
        return tier(GUILD, ON, str(guilds),
                    "%d %s on the realm." % (guilds, _plural(guilds, "guild",
                                                             "guilds")))
    short = max(CHARTER_SIGNATURES - realm_characters, 0)
    if short:
        switch = ("A charter with %d signatures. The realm has %d %s in "
                  "total, so it is %d short of being able to sign one at all."
                  % (CHARTER_SIGNATURES, realm_characters,
                     _plural(realm_characters, "character", "characters"),
                     short))
    else:
        switch = ("A charter with %d signatures. The realm has the characters "
                  "for it; nobody has taken one round." % CHARTER_SIGNATURES)
    return tier(GUILD, OFF, "0", "No guild exists on this realm.", switch)


def realm_tier(souls: int, mortals: int) -> dict:
    """Who is in the world right now, and whether that is a population.

    PARTIAL until there is a crowd, because one family logged in is not a
    server's population however truthfully it is counted - and a graph of it
    would be a graph of whether five characters were switched on.
    """
    if not souls:
        return tier(
            REALM, OFF, "0",
            "Nobody walks the world right now.",
            "Anyone logged in. An empty realm is a real state here - the "
            "module sweeps logged-out rows, so the table drains.",
        )
    bots = max(souls - mortals, 0)
    headline = "%d %s in the world, %d of them played by the machine." % (
        souls, _plural(souls, "soul", "souls"), bots)
    if souls >= CROWD:
        return tier(REALM, ON, str(souls), headline)
    return tier(
        REALM, PARTIAL, str(souls), headline,
        "%d at once. Below that the population IS the family, and a "
        "population chart would be a chart of whether they are logged in."
        % CROWD,
    )


def honest_line(on: int, total: int) -> str:
    """What the ladder adds up to, in one sentence.

    Deliberately not cheerful. A rollup that says "3 of 5 systems nominal"
    over a realm with one family on it is the dashboard voice this view
    refuses; what a reader needs is the shape of what is missing.
    """
    if on >= total:
        return ("Every tier is real. Nothing on this page is a placeholder "
                "for something that does not exist yet.")
    off = total - on
    return ("%d of %d tiers are real. The other %d %s drawn as a chart, "
            "because %s not there yet; each one names what would turn it on."
            % (on, total, off, _plural(off, "is not", "are not"),
               _plural(off, "it is", "they are")))


def build_eye(snapshot_rows: list[dict], family_rows: list[dict],
              realm_rows: list[dict], guild_rows: list[dict],
              now: datetime | None = None) -> dict:
    """Rows in, the Eye's JSON out.

    snapshot_rows overseer_snapshot, the live world (name, is_bot, group_leader)
    family_rows   the family's SAVED character rows (name), so the ladder does
                  not report a family that stopped existing at bedtime
    realm_rows    a single COUNT(*) row over `characters`, or []
    guild_rows    a single COUNT(*) row over `guild`, or []
    now           the clock, injectable so the suite can stand still

    EVERY ONE OF THOSE MAY BE EMPTY, exactly as build_agenda's may: a realm
    whose schema predates a table hands in [] for it, and every tier above
    reads an empty list as "nothing found" rather than raising.
    """
    now = now or datetime.now()
    realm_characters = _count(realm_rows, "characters")
    guilds = _count(guild_rows, "guilds")
    souls = len(snapshot_rows)
    mortals = sum(1 for row in snapshot_rows if not row.get("is_bot"))
    family = {str(row["name"]) for row in family_rows}
    tiers = [
        character_tier(family_rows, realm_characters),
        family_tier(family_rows),
        party_tier(snapshot_rows, family),
        guild_tier(guilds, realm_characters),
        realm_tier(souls, mortals),
    ]
    on = sum(1 for row in tiers if row["state"] == ON)
    return {
        "generated_at": _iso(now),
        "tiers": tiers,
        # The stat strip over the ladder. Every one of these is counted, and
        # the last is the point of the view: how much of the ladder is real.
        "strip": [
            {"label": "CHARACTERS", "value": str(realm_characters)},
            {"label": "IN WORLD", "value": str(souls)},
            {"label": "FAMILIES", "value": "1" if family_rows else "0"},
            {"label": "GUILDS", "value": str(guilds)},
            {"label": "TIERS ON", "value": "%d/%d" % (on, len(tiers))},
        ],
        # THE SENTENCE THE VIEW IS FOR. Said by the module, not by the page,
        # for the same reason every other sentence on this site is: a claim
        # about what exists is a judgement, and the page has no business
        # making one.
        "honest": honest_line(on, len(tiers)),
    }
