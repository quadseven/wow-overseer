"""Pure builder for the Family tab: snapshot rows -> the five that matter.

WHY THIS EXISTS AS AN ENDPOINT AT ALL. Everything here can be read today:
/api/map carries zone and combat, /api/character carries health. But the
Family tab wants BOTH for five characters at a phone-friendly cadence, and
the only way to get health without this is five /api/character calls - five
connections, thirty-odd queries, and about 12KB of hotbars, bags and
equipment nobody asked for, every poll. This is that same state, projected
to what a card actually draws.

Same seam rule as map_core and panel (infra#2597): the HTTP adapter fetches
rows and does nothing else. Which member is "hurt", who is missing, and what
a dead character reads as are decisions, so they live here where the stdlib
suite can reach them.

Ticket: infra#2892.
"""

from __future__ import annotations

import os
import re

import bonds
import stream
import watchwall
from core import _ALLIANCE_RACES, _HORDE_RACES
from panel import _CLASS_NAMES, _RACE_NAMES, CLASS_COLOURS

# Below this fraction of their health a character is in trouble, and the card
# says so in colour rather than making a person read two numbers and divide.
#
# A THIRD, not a tenth. The incident that produced this tab was the family
# dying on a loop in a zone thirty levels above them (infra#2891 territory):
# by the time anyone was under 10% the fight was already lost, so the useful
# warning is the one that fires while there is still something to be done.
HURT_BELOW = 0.35

# What a card can be, in the order a person cares about them. The page maps
# these straight to a colour and a word; deciding it here is what makes it
# testable, and what stops "dead" and "logged out" ever rendering the same.
DEAD = "dead"
HURT = "hurt"
OK = "ok"
GONE = "gone"

# --- the always-on broadcast grid (infra#2892 Twitch view) -----------------
#
# The five family members already stream continuously to MediaMTX - five
# ffmpeg encoders running on the gaming box independently of the on-demand
# POV watch above. That watch flow (stream.py, MAX_CHANNELS=2, a 45-60s
# client bring-up) governs LOGGING IN AS somebody; this is a passive VIEWER
# path onto a broadcast that is already running, and the two are unrelated -
# nothing here ever asks the stream agent for a client, so it never competes
# for a GPU channel.
#
# WHY THE PATH IS BUILT HERE AND NOT BORROWED FROM wow-stream-agent/video.py.
# That module's stream_path() is the correct, current answer for anything the
# stream agent itself starts - but it is a separate codebase on a separate
# machine, imported nowhere near this one, and as of this feature landing its
# formula (f"{prefix}-{name}", HYPHENATED) does not match what is actually
# live: querying http://127.0.0.1:9997/v3/paths/list on the gaming box right
# now returns devgrug, devbork, devgrog, devog, devugga - prefix and name
# CONCATENATED, no separator. The encoders publishing those paths were
# started before video.py grew the hyphen (infra#2994) and were not
# restarted to pick it up - restarting them is exactly the "kill a live
# demo" this feature must not do. So this mirrors the convention that is
# actually running, not the one in the newer source file, and says so here
# rather than silently disagreeing with a file three directories away.
_STREAM_PREFIX = os.environ.get("WOW_STREAM_PREFIX", "dev").strip().lower()
_STREAM_BASE = os.environ.get(
    "WOW_STREAM_BASE", "https://wow.stream.ts.ehumps.me"
).rstrip("/")
# Same shape restriction as the stream agent's own _NAME_RE (video.py): a
# name that lands in a URL gets the same treatment frames._NAME_RE gives it.
_BROADCAST_NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")

# WHO IS ACTUALLY STREAMED. Every character has a stream PATH, because the path
# is a pure function of the name, but only some have anything publishing to it.
# On a host that can render two game clients, the other eight characters are
# headless bots: there is no picture to show, and drawing a video tile for each
# put eight black rectangles beside the two that work. The operator asked for
# them to go.
#
# A comma-separated list of names. UNSET OR EMPTY MEANS EVERYONE, which is what
# every deployment did before this existed, so nothing changes anywhere that does
# not set it. A character on the list keeps the URL it always had; a character not
# on it has none, and `watchwall.playable` already means "a URL exists to try", so
# the wall and the cards follow without a second rule.
_STREAMED = frozenset(
    name.strip()
    for name in os.environ.get("WOW_STREAMED_CHARACTERS", "").split(",")
    if name.strip()
)


def is_streamed(character: str, streamed=None) -> bool:
    """Does this character have a picture to watch?

    Case-sensitive on purpose: a character name IS its spelling, and a near-miss
    must read as not streamed rather than quietly matching somebody else's.
    """
    listed = _STREAMED if streamed is None else frozenset(streamed)
    return not listed or (character or "").strip() in listed


_BROADCAST_PREFIX_RE = re.compile(r"^[a-z]{0,8}$")


def broadcast_path(character: str, prefix: str | None = None) -> str:
    """The MediaMTX path a family member's continuous broadcast lives on.

    Concatenated, not hyphenated - see the module docstring above for why
    this deliberately does not match video.py's stream_path(). An unusable
    name or prefix returns "" rather than raising: a broadcast tile that
    cannot resolve a path is drawn offline, not a 500 that takes the whole
    Family tab down with it.
    """
    name = (character or "").strip()
    if not _BROADCAST_NAME_RE.match(name):
        return ""
    label = (_STREAM_PREFIX if prefix is None else prefix).strip().lower()
    if label and not _BROADCAST_PREFIX_RE.match(label):
        return ""
    return f"{label}{name.lower()}"


def broadcast_url(
    character: str, base: str | None = None, prefix: str | None = None
) -> str | None:
    """Where a browser opens a WHEP connection for this member's broadcast.

    None when the path cannot be built, so the page can tell "nobody to
    watch" (no URL) apart from "asked and got refused" (a URL that 404s).

    ALWAYS THE DEFAULT RENDITION. This field predates the quality ladder and
    a player that has never heard of renditions must keep working unchanged,
    so it keeps meaning exactly what it always meant: one address, the full
    size one.
    """
    return _rendition_url(character, RENDITION_DEFAULT, base, prefix)


# --- the quality ladder (infra#3330) --------------------------------------
#
# WHY THE SERVER SAYS THIS AT ALL, rather than the page assuming a suffix.
# WebRTC has no quality ladder of its own and MediaMTX does not transcode, so
# a second quality exists only because a second encoder output publishes it.
# That is a fact about what the gaming box is running, and a page that
# guessed it would offer a picker whose second entry is a 404. Naming the
# ladder here means the UI is built from data and, when the list has one
# entry, honestly shows no picker at all.
#
# WHAT THIS CAN AND CANNOT KNOW, stated plainly because the difference is the
# whole contract. It knows what the publisher is CONFIGURED to produce. It
# does NOT know what is live right now, and it cannot: MediaMTX's API is
# bound to 127.0.0.1:9997 on the gaming box (wow-stream-agent/mediamtx.yml)
# and this server runs in the cluster, so there is nothing to ask. Probing per
# request would also put a network call in the middle of a page load to answer
# a question the browser is about to answer for itself.
#
# SO LIVENESS STAYS WHERE IT ALREADY LIVES: the WHEP handshake. That is not a
# new rule, it is the one _member already follows - a logged-out character is
# still offered a URL because the tile learns the truth from the handshake. A
# rendition nobody is publishing answers the WHEP POST with 404, which
# index.html's whepFailure() already turns into a sentence. The page falls
# back to the default rendition; the ladder never has to lie.
#
# MIRRORED FROM wow-stream-agent/video.py's RENDITIONS, deliberately rather
# than imported - the same split, for the same reason, as broadcast_path
# above: that is a separate codebase on a separate machine. Kept honest by
# tests/test_family.py, which reads that file and compares.
RENDITION_DEFAULT = "high"
RENDITIONS = (
    {"id": "high", "label": "720p", "suffix": "", "width": 1280, "height": 720},
    {"id": "low", "label": "360p", "suffix": "low", "width": 640, "height": 360},
)

# The lever for turning the ladder off from the map's side, and the one case
# it is for: the encoders on the gaming box are pinned to a detached worktree
# and only pick up a new command line when an operator restarts them. If they
# are ever rolled back to a build that publishes one rendition, setting this
# to 0 stops the page offering a second quality before anyone sees a 404.
# It is not a feature flag for the ladder itself - the WHEP fallback already
# makes a mismatch harmless - it is a way to make the UI quieter during one.
_LADDER = os.environ.get("WOW_STREAM_LADDER", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)


def _rendition_url(
    character: str,
    rendition_id: str,
    base: str | None = None,
    prefix: str | None = None,
) -> str | None:
    """One rendition's WHEP base URL, or None if the path cannot be built OR the
    character is not streamed."""
    if not is_streamed(character):
        return None
    path = broadcast_path(character, prefix)
    if not path:
        return None
    for spec in RENDITIONS:
        if spec["id"] == rendition_id:
            suffix = spec["suffix"]
            break
    else:
        return None
    root = (_STREAM_BASE if base is None else base).rstrip("/")
    return f"{root}/{path}{suffix}"


def broadcast_renditions(
    character: str, base: str | None = None, prefix: str | None = None
) -> list[dict]:
    """Every quality this member can be watched at, best first.

    A LIST, ALWAYS, and never a bare URL: one entry is the honest answer when
    only one rendition is published, and the page draws no picker for it. An
    unusable name returns [] for the same reason broadcast_path returns "" -
    a tile that cannot resolve a path is drawn offline, not a 500 that takes
    the whole Family tab down.

    `default` marks where a player starts and what it falls back TO when a
    chosen rendition 404s. Exactly one entry carries it.
    """
    out = []
    for spec in RENDITIONS:
        if not _LADDER and spec["id"] != RENDITION_DEFAULT:
            continue
        url = _rendition_url(character, spec["id"], base, prefix)
        if not url:
            return []
        out.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "url": url,
                "width": spec["width"],
                "height": spec["height"],
                "default": spec["id"] == RENDITION_DEFAULT,
            }
        )
    return out


def roster() -> list[str]:
    """The five, oldest first.

    bonds.speaking_order is the family table's own answer to who comes first,
    and it is already what decides who speaks first when they all answer at
    once. Sorting these cards by a second rule would be a second opinion about
    the same family that could disagree with it.
    """
    return bonds.speaking_order(bonds.FAMILY)


# THE GLYPH TILE, WHICH IS NOT A PHOTO SLOT. 64 pixels cannot hold a portrait
# with any chrome around it, and there is no portrait to hold: these are game
# characters whose only likeness on this page is the live broadcast above the
# tile. So the tile is a MARK - the character's initials over a two-letter
# stand-in for their race - and the two functions that build it are here
# because a label is a decision about what to call something, which is the
# same rule that keeps every other word on this card out of the page.


def race_mark(race: str) -> str:
    """A race as two letters: "human" -> HU, "night elf" -> NE.

    Two WORDS take an initial each and one word takes its first two letters,
    which is what keeps the four elf races apart: "night elf" and "blood elf"
    both start "bl"/"ni" harmlessly, but "ni" and "bl" say nothing while NE
    and BE are what players already write. An empty race gives an empty mark
    rather than a placeholder, so a tile with nothing to say draws nothing.
    """
    words = (race or "").split()
    if not words:
        return ""
    if len(words) > 1:
        return (words[0][:1] + words[1][:1]).upper()
    return words[0][:2].upper()


def initials(name: str) -> str:
    """The letters that go on the tile: "Grug" -> G.

    At most two, because three initials in a 64px tile is a word rather than a
    mark. Every one of the five has a single name today; this handles the
    other shape rather than assuming it away.
    """
    words = (name or "").split()
    if not words:
        return ""
    if len(words) > 1:
        return (words[0][:1] + words[1][:1]).upper()
    return words[0][:1].upper()


def _condition(health: int, max_health: int) -> str:
    # max_health of 0 is a snapshot mid-write, not a corpse. Calling that
    # "dead" would put a red card on screen for a character running about
    # perfectly well, which is the one lie this tab cannot afford.
    if max_health <= 0:
        return OK if health > 0 else DEAD
    if health <= 0:
        return DEAD
    return HURT if health / max_health < HURT_BELOW else OK


# --- what a card knows about someone who is not logged in -----------------
#
# A persona (bonds) spells its class and race as WORDS; the database spells
# them as ids. Both are answers to the same question, so each of these takes
# the persona when there is one and the database when there is not, and a
# character neither knows renders blank rather than wrong.


def _class_name_of(bond, profile: dict) -> str:
    if bond:
        return bond.char_class.title()
    class_id = profile.get("class")
    return _CLASS_NAMES.get(class_id, "") if class_id is not None else ""


def _class_colour_of(bond, profile: dict) -> str:
    if bond:
        return class_colour_by_name(bond.char_class)
    class_id = profile.get("class")
    return CLASS_COLOURS.get(class_id, "#ffffff")


def _race_name_of(bond, profile: dict) -> str:
    if bond:
        return bond.race
    race_id = profile.get("race")
    return _RACE_NAMES.get(race_id, "") if race_id is not None else ""


def _member(
    name: str,
    row: dict | None,
    geo,
    leader_name: str | None,
    profile: dict | None = None,
) -> dict:
    """One card. `profile` is what the DATABASE knows about this character's
    class and race, and it is what makes this work for a second family.

    WHY bonds IS NO LONGER INDEXED DIRECTLY. `bonds.FAMILY` is ONE family's
    persona table - five keys, renamed per world - so `bonds.FAMILY[name]`
    was a KeyError for every member of any other family, which is to say the
    Family tab could only ever render the family bonds happened to hold.
    `bonds.bond_of` reads every family bonds describes and returns None for
    anyone outside them all, and everything that used to come from the bond
    has a database answer behind it:

      role   - bonds only. Both families have one ("father", "chief"). A
               character no family claims has no persona and therefore no
               role, and "" is the honest answer rather than a guess. The
               card shows the class, which is a fact.
      class  - the snapshot row when present, `profile` when logged out.
      race   - the same.

    So a persona enriches a card here; it no longer gates one existing.
    """
    bond = bonds.bond_of(name)
    profile = profile or {}
    if row is None:
        # Logged out, or the worldserver dropped them. NOT an error and NOT a
        # dead character: the snapshot sweep removes rows for anyone who is
        # not there, so an absent row is the ordinary way to be offline.
        return {
            "name": name,
            "role": bond.role if bond else "",
            "class": _class_name_of(bond, profile),
            "class_colour": _class_colour_of(bond, profile),
            # The glyph tile is drawn for a logged-out member too. The card
            # still carries their name, and a card whose picture, bars and
            # zone have all gone quiet is exactly the one that needs a mark
            # on it to still read as somebody.
            "initials": initials(name),
            "mark": race_mark(_race_name_of(bond, profile)),
            "present": False,
            "condition": GONE,
            # A logged-out character can still be mid-broadcast for a beat -
            # the snapshot sweep and the encoder are not the same clock - so
            # the tile is offered a URL here too. The tile itself learns the
            # truth from the WHEP handshake, the same way the on-demand
            # player does; this module does not guess "offline" from absence.
            "broadcast_url": broadcast_url(name),
            "broadcast_renditions": broadcast_renditions(name),
        }
    race, class_id = row["race"], row["class"]
    health, max_health = int(row["health"]), int(row["max_health"])
    placed = geo.place(row["map_id"], row["pos_x"], row["pos_y"])
    in_instance = placed is not None and str(row["map_id"]) != placed[0]
    return {
        "name": row["name"],
        "role": bond.role if bond else "",
        "present": True,
        "level": row["level"],
        "class": _CLASS_NAMES.get(class_id, f"class {class_id}"),
        # The feed's name is drawn in it (infra#88), the same colour the
        # Armory and the quest board's portraits use for the same person.
        "class_colour": CLASS_COLOURS.get(class_id, "#ffffff"),
        "race": _RACE_NAMES.get(race, f"race {race}"),
        "initials": initials(row["name"]),
        "mark": race_mark(_RACE_NAMES.get(race, "")),
        "faction": "alliance"
        if race in _ALLIANCE_RACES
        else "horde"
        if race in _HORDE_RACES
        else "neutral",
        "condition": _condition(health, max_health),
        "health": health,
        "max_health": max_health,
        # Rounded here so five cards cannot each round it differently, and so
        # a character on 1hp of 583 reads as 1% rather than 0% - "0%" next to
        # a living character is a card arguing with itself.
        "health_pct": _health_pct(health, max_health),
        "zone": "inside an instance" if in_instance else _zone_of(row, geo),
        "broadcast_url": broadcast_url(row["name"]),
        "broadcast_renditions": broadcast_renditions(row["name"]),
        "instance": in_instance,
        "combat": bool(row["in_combat"]),
        "leader": bool(leader_name) and row["name"] == leader_name,
        # Surfaced because stream.pov_changes_the_family says in as many words
        # that the UI must not hide it: watching the leader in POV hands the
        # other four a master and they start following. Best thing about
        # watching Grug, and a surprise if nobody says it.
        "pov_changes_the_family": stream.pov_changes_the_family(
            row["name"], leader_name or ""
        ),
        "age_seconds": int(row["age_seconds"]),
    }


def _zone_of(row: dict, geo) -> str:
    """Where a character is, preferring the world's own answer.

    The snapshot row carries `zone_id`, which the core writes from the
    player's live zone on every tick. The rectangle lookup is only a guess
    from position, and it guessed wrong where zone boxes overlap: a head
    standing in Winterspring was captioned "in Felwood" on the Watch tile
    while the client on the same screen said Winterspring. The guess stays
    as the fallback for a row with no id, or an id this realm's zone table
    does not draw.
    """
    return geo.zone_by_id(row.get("zone_id")) or geo.zone_name(
        row["map_id"], row["pos_x"], row["pos_y"]
    )


def class_colour_by_name(class_name: str) -> str:
    """The colour for a class the family table spells by name.

    A logged-out member has no snapshot row and so no class id, but the card
    still carries their name and the name should still be their colour.
    """
    wanted = (class_name or "").strip().lower()
    for cid, spelled in _CLASS_NAMES.items():
        if spelled.lower() == wanted:
            return CLASS_COLOURS.get(cid, "#ffffff")
    return "#ffffff"


def _health_pct(health: int, max_health: int) -> int:
    if max_health <= 0:
        return 0
    pct = round(100 * health / max_health)
    # A living character never rounds down to nothing, and a dead one never
    # rounds up to something.
    if pct == 0 and health > 0:
        return 1
    if pct == 100 and health < max_health:
        return 99
    return pct


def build_family(rows: list[dict], geo, names=None, profiles=None) -> dict:
    """One family's cards, in roster order, from whatever the snapshot has.

    `rows` is every fresh snapshot row for a family name; anyone missing is
    rendered as GONE rather than dropped, because a card that vanishes is how
    a logged-out character stops being noticed - which is the whole complaint
    this tab answers.

    `names` IS THE FAMILY AND THE CALLER OWNS IT. This used to enumerate
    `roster()`, which is bonds, which knows exactly one family - so asking for
    a second family returned the SECOND family's snapshot rows rendered
    against the FIRST family's five names, and every card came out "logged
    out" because none of those names was in the rows. The wall said Zug's
    family and listed Grug's. Defaulting to `roster()` keeps every existing
    caller on the family bonds holds.

    `profiles` is {name: {"class": id, "race": id}} from the characters table,
    for members with no snapshot row to describe them - see `_member`.
    """
    names = roster() if names is None else names
    profiles = profiles or {}
    by_name = {r["name"]: r for r in rows}
    by_guid = {r["guid"]: r for r in rows}
    # The leader as the WORLD has it, not as the family table remembers it:
    # group_leader is a live guid, and the party can be led by someone the
    # snapshot has not got, in which case nobody here is marked leader.
    leader_name = None
    for r in rows:
        holder = by_guid.get(r["group_leader"])
        if holder is not None:
            leader_name = holder["name"]
            break
    members = [
        _member(n, by_name.get(n), geo, leader_name, profiles.get(n)) for n in names
    ]
    present = [m for m in members if m["present"]]
    return {
        "members": members,
        # THE WALL IS COMPOSED HERE rather than in the page, because deciding
        # what a tile says is judgement and infra#2597 puts judgement in a
        # module the stdlib suite can reach. It rides on this payload rather
        # than on an endpoint of its own so the wall and the cards can never
        # disagree about who is dead: they are the same five dicts, read once.
        "wall": watchwall.build_wall(members),
        "here": len(present),
        "expected": len(members),
        "dead": sum(1 for m in present if m["condition"] == DEAD),
        "in_combat": sum(1 for m in present if m["combat"]),
        "freshest_seconds": min((m["age_seconds"] for m in present), default=None),
    }
