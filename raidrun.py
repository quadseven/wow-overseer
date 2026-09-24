"""The raid run: the operator's order for a raid night, and what it needs.

WHAT THIS IS FOR. A family's dungeon campaign is a `dungeon:<keyword>` job
the queue writes and mod-overseer's coordinator runs. A raid is not a bigger
dungeon run: forty characters, most of them guild bots off the roster, have to
be put in one raid group, brought to one door and walked through it together.
mod-overseer's raid run (quadseven/mod-overseer#634) does that on a
`raid:<keyword>` job, reading who sits where from `overseer_raid_seat`. This
module is the site's half: the keyword, the seats the bridge writes from the
Lineup tab's own selection, the attunement path, and the plain facts the Raid
tab states about what the overseer can and cannot do yet.

AN ORDER AND NEVER A PLAN. The only way `raid:moltencore` reaches a roster row
is an operator typing `queue <family>: moltencore 1`. The campaign planner and
the council choose among jobs.PORTAL_KEYWORDS, which a raid keyword is not in,
so neither can propose one.

PURE MODULE, same seam as campaignqueue.py: rows in, rows and sentences out,
nothing that talks to MySQL. bridge.py runs the statements named here.
"""

from __future__ import annotations

import jobs

# The one raid door mod-overseer has (RaidDoorFor in overseer_decisions).
MOLTEN_CORE = "moltencore"
MOLTEN_CORE_MAP = 409

# THE LEVEL THE INSTANCE'S OWN ACCESS ROW ASKS: dungeon_access_template for map
# 409 says min_level 50 and carries no requirement rows. The site reads the row
# live for the readiness card; this copy is only the queue's refusal, checked
# before an order is written.
MIN_LEVEL = {MOLTEN_CORE: 50}

# ONE NIGHT PER ORDER. The queue counts an entry done off the leader's
# `dungeon_runs_done`, which only the dungeon coordinator writes, so a raid
# entry stays active until the operator clears the queue. An order for "3"
# would read as a promise of three nights that nothing counts.
RUNS_PER_ORDER = 1

# The names an order may use for the raid, folded the way campaignqueue folds.
NAMES = {
    "moltencore": MOLTEN_CORE,
    "molten core": MOLTEN_CORE,
    "mc": MOLTEN_CORE,
}

# WHAT THE OVERSEER CAN DO WITH AN ORDERED RAID, stated rather than inferred,
# because the module that does it is another repository. Pinned to
# quadseven/mod-overseer#634; change these with the module, never ahead of it.
FORMS = True  # converts the head's group and seats the lineup
ENTERS = True  # assembles at the door and walks the raid in, head last
CLEARS = False  # the dungeon brain is held off raid maps until this is built

# --- the seats -----------------------------------------------------------------

SEAT_TABLE = "overseer_raid_seat"

# The module's migration (2026_09_23_01_overseer_raid_seat.sql) creates the
# table; the bridge only replaces one family's rows for one raid.
DELETE_SEATS_SQL = "DELETE FROM overseer_raid_seat WHERE family = %s AND keyword = %s"
INSERT_SEAT_SQL = (
    "INSERT INTO overseer_raid_seat (family, keyword, name, subgroup, role) "
    "VALUES (%s, %s, %s, %s, %s)"
)

# EVERY MEMBER OF THE FAMILY'S GUILD, found from the family's own names, which
# is the same read the Raid tab's lineup is chosen from (map_server's
# _RAID_GUILD), so the seats written are the lineup the operator saw.
GUILD_MEMBERS_SQL = (
    "SELECT c.name, c.level, c.class AS class_id, c.race "
    "FROM characters c JOIN guild_member gm ON gm.guid = c.guid "
    "WHERE gm.guildid IN (SELECT gm2.guildid FROM guild_member gm2 "
    "JOIN characters c2 ON c2.guid = gm2.guid WHERE c2.name IN ({holes}))"
)


def is_raid(keyword: str) -> bool:
    return str(keyword or "") in jobs.RAID_KEYWORDS


def keyword_for(text: str) -> str | None:
    """The raid keyword `text` names, or None."""
    folded = " ".join(str(text or "").lower().replace("'", "").split())
    if folded.startswith("the "):
        folded = folded[4:]
    return NAMES.get(folded)


def place(keyword: str) -> str:
    return {MOLTEN_CORE: "Molten Core"}.get(keyword, keyword)


def refusal(keyword: str, runs: int, level_rows: list) -> str:
    """Why this family cannot be ordered to this raid, or "".

    Every member must be at the instance's own minimum level: the core refuses
    the door to anybody below it, and one member refused at the door is a
    family split at the door.
    """
    if not is_raid(keyword):
        return "the overseer has no raid door for %s" % keyword
    if int(runs) != RUNS_PER_ORDER:
        return (
            "a raid order is one night; order %s %d and clear the queue when "
            "it is over" % (place(keyword), RUNS_PER_ORDER)
        )
    floor = MIN_LEVEL.get(keyword, 0)
    under = sorted(
        str(r.get("name")) for r in level_rows or [] if int(r.get("level") or 0) < floor
    )
    if under:
        return "%s %s below level %d, the lowest %s admits" % (
            ", ".join(under),
            "is" if len(under) == 1 else "are",
            floor,
            place(keyword),
        )
    return ""


def seat_rows(family: str, keyword: str, lineup: dict) -> list:
    """(family, keyword, name, subgroup, role) per placed raider.

    `lineup` is raidlineup.build_lineup's answer. Groups there are numbered
    1 to 8 for the page; the module and the core hold subgroups 0 to 7, so the
    conversion is made once, here.
    """
    rows = []
    for index, group in enumerate(lineup.get("groups") or []):
        number = int(group.get("number") or index + 1)
        for member in group.get("members") or []:
            rows.append(
                (
                    family,
                    keyword,
                    str(member["name"]),
                    number - 1,
                    str(member.get("role") or ""),
                )
            )
    return rows


# --- the attunement ------------------------------------------------------------
#
# "Attunement to the Core", both of the core's rows (7848 Alliance, 7487 Horde;
# raidready.ATTUNEMENT_QUESTS). Given and taken by Lothos Riftwaker (creature
# 14387) on Blackrock Mountain's own ledge, at (-7508.63, -1039.84, 180.995) on
# map 0. The objective is one Core Fragment (item 18412), which drops only for
# a character holding the quest, from the Core Fragment chest (gameobject
# 179553) inside Blackrock Depths at (1128.01, -471.76, -104.03) on map 230,
# beside the Molten Bridge. The Alliance row is not shareable (quest Flags 64,
# no sharable bit), so each member takes it from Lothos in person.
#
# WHAT IT BUYS, AND WHAT IT DOES NOT. Lothos's gossip "Teleport me to the
# Molten Core" is conditioned on either row rewarded. The Molten Core window
# (areatrigger 3529), a few yards from him, asks only a raid group and level
# 50. So the attunement is a shortcut for a person, not a gate for the raid.

LOTHOS = 14387
CORE_FRAGMENT = "Core Fragment"
CORE_FRAGMENT_ITEM = 18412

ATTUNED = "attuned"
FRAGMENT_HELD = "fragment held"
IN_LOG = "in the quest log"
NOT_TAKEN = "not taken"

# Quest status 3 is QUEST_STATUS_INCOMPLETE and 1 QUEST_STATUS_COMPLETE in
# character_queststatus, the two a quest in the log carries.
IN_LOG_STATUSES = frozenset({1, 3})

STEPS = (
    "Send the family to Lothos Riftwaker: a travel order for the head to "
    "creature %d; the family follows. Each member takes Attunement to the Core "
    "from him in person (the Alliance quest cannot be shared)." % LOTHOS,
    "Queue the family into Blackrock Depths: queue <family>: blackrock depths "
    "1. The Core Fragment chest stands beside the Molten Bridge in the back "
    "half of the dungeon, past the Lyceum; it opens only for a member holding "
    "the quest, one fragment each.",
    "Walk back to Lothos and hand the fragment in. The Raid tab shows each "
    "member move from not taken to in the quest log to fragment held to "
    "attuned, read from the realm.",
)

STEPS_UNPROVEN = (
    "Not yet seen on this realm: whether every follower takes the quest at "
    "Lothos when the head does, whether the dungeon brain's route passes close "
    "enough to the chest for each member to loot it, and whether the hand-in "
    "happens without a turn-in errand. Each is read back from the realm rather "
    "than assumed."
)


# THE GUILD BOTS ARE NOT ON THIS PATH, and that is a finding rather than an
# omission. Nothing in the overseer drives a guild bot's quests (mod-overseer
# steers roster characters; a guild bot only follows the head it is grouped
# with), Blackrock Depths is a five-player dungeon a raid group cannot take in,
# and the window they walk through does not ask for the attunement.
BOTS_LINE = (
    "The guild bots in the raid are not attuned, and nothing in the overseer "
    "can make them: it steers the family, and a guild bot only follows the "
    "head it is grouped with. They do not need it to walk in."
)


def attunement_status(rewarded: bool, in_log: bool, fragments: int) -> str:
    if rewarded:
        return ATTUNED
    if in_log and fragments > 0:
        return FRAGMENT_HELD
    if in_log:
        return IN_LOG
    return NOT_TAKEN


def attunement(names: list, rewarded: set, in_log: set, fragments: dict) -> dict:
    """Where each of `names` stands on the attunement, and the steps.

    `rewarded` and `in_log` are names; `fragments` is name -> Core Fragments
    carried or banked.
    """
    members = []
    for name in names:
        status = attunement_status(
            name in rewarded, name in in_log, int(fragments.get(name) or 0)
        )
        members.append(
            {"name": name, "status": status, "line": "%s: %s" % (name, status)}
        )
    done = len([m for m in members if m["status"] == ATTUNED])
    return {
        "line": "%d of %d attuned to the Core. It opens Lothos Riftwaker's "
        "teleport; the Molten Core window beside him admits a raid without it."
        % (done, len(members)),
        "members": members,
        "steps": list(STEPS),
        "unproven": STEPS_UNPROVEN,
        "bots": BOTS_LINE,
    }


# --- what the overseer can and cannot do with the raid ------------------------

DUNGEON_CLEAR_LINE = (
    "The dungeon-clear brain at the pinned revision has raid code: a raid "
    "profile of its settings, a pre-boss muster, a stand-down that hands each "
    "boss fight to the playerbots raid strategies, and Molten Core's finale "
    "authored (Majordomo's adds, then Ragnaros summoned by gossip). Its own "
    "notes say none of it has been validated live, and the overseer keeps it "
    "switched off on a raid map until clearing is ordered."
)


def run_line() -> str:
    """What an order does today, in the order it happens."""
    did = []
    if FORMS:
        did.append("forms the raid from the lineup")
    if ENTERS:
        did.append("walks it to the Molten Core door and in, the head last")
    head = (
        "An order (queue <family>: moltencore 1) "
        + " and ".join(did)
        + ", with a family member streaming."
        if did
        else "Nothing can take a raid in yet."
    )
    if not CLEARS:
        head += (
            " It does not clear: inside, the raid holds at the entrance. "
            "Raiders on another continent are not brought to the door; "
            "summoning them is a later slice."
        )
    return head
