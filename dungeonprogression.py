"""Pure dungeon campaign progression decisions.

The dungeon coordinator records which portal a run used.  A map id is not
enough for Scarlet Monastery because all four wings share map 189.  This
module consumes that durable portal identity and chooses the first stage whose
successful run count is below the requested campaign size.

WHICH DUNGEON IS NOT DECIDED HERE, AND THAT IS THE POINT (infra#4247).
council.prospects() already picks the place: it ranks every dungeon by the
level that opens it against the level of the family's weakest member.  This
module answers the narrower question that ranking cannot - "the family is
going to map 189, which of its four doors" - and it answers it in ORDER,
against a durable ledger, so a 25-run-per-wing campaign can be audited.

THE TWO WERE THE WRONG WAY ROUND UNTIL infra#4247, and the symptom was a level
60 family being sent back to Scarlet Cathedral (a level 39 wing) every hour,
for ever.  The Scarlet campaign was allowed to OUTRANK the level frontier, so
once the family walked past Scarlet Monastery there was nothing that could
move them off it: the frontier had a better answer and never got asked.  The
frontier now chooses the dungeon and this module orders that dungeon's stages,
which is the division of labour each half was already built for.

No database, HTTP, or world access belongs here.  The adapter is responsible
for reading the run ledger and handing rows to these functions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence


SCARLET_MAP_ID = 189

# The order is a progression contract, not a level ranking.  The library key
# is deliberately kept as the same job keyword the C++ coordinator accepts.
SCARLET_WINGS = (
    ("scarlet", 28),
    ("scarlet-library", 33),
    ("scarlet-armory", 36),
    ("scarlet-cathedral", 39),
)

# BLACKROCK DEPTHS, AND IT NEEDS NONE OF THE MACHINERY ABOVE (infra#4247).
#
# The four Scarlet entries exist because four DIFFERENT dungeons share one map
# id, so `map_id = 189` cannot say which of them a run was.  That is a fact
# about Scarlet Monastery and not a shape every dungeon has.  Checked against
# the pinned core's own world database rather than assumed:
#
#   instance_template       map 230, parent 0, script instance_blackrock_depths
#   areatrigger_teleport    1466 'Blackrock Depths Entrance'
#                             map 0 (-7176.63, -937.667, 170.206) r13 -> map 230
#                           1472 'Blackrock Dephts - Searing Gorge Instance'
#                             map 230 (456.969, 48.368, -65.2753) r12 -> map 0
#                           2886 'The Molten Bridge'
#                             map 230 -> map 409 (Molten Core, a RAID exit and
#                             not a second way into this dungeon)
#
# ONE way in, ONE way back out, one map, one instance script.  So one keyword,
# and `map_id = 230` identifies a Blackrock Depths run on its own.
#
# IT DOES HAVE DISTINCT WINGS IN THE ORDINARY SENSE - the Detention Block, the
# Ring of Law, the Upper City behind the Lyceum - and they were considered
# rather than waved away.  They are not separate maps and not separate
# entrances: they are doors inside one instance, so nothing in the run ledger
# could tell them apart.  overseer_dungeon_run carries ONE row per run with one
# `outcome`; it has no per-boss column and inventing one to slice a single
# instance into imaginary wings would be this module asserting a distinction
# the data cannot support.  A cleared run is the honest unit here.
#
# 52 IS A RECOMMENDATION AND NOT THE CORE'S GATE, exactly like every number in
# council.PLACES.  `dungeon_access_template` lets a level 40 walk in
# (row 14, min_level 40, "Blackrock Depths (BRD)").  Measured against what is
# actually spawned on map 230 on this pinned core: the trash runs 48 to 60, the
# rare elites 52 to 56.  A family let in at 40 would die at the door, which is
# the whole reason council.PLACES carries a judgement rather than the access
# table's minimum.
BLACKROCK_DEPTHS_MAP_ID = 230
BLACKROCK_DEPTHS = (("blackrock-depths", 52),)

# Map id -> the ordered stages of that map's campaign.  A map that is NOT in
# here has no named campaign, which is an ordinary answer and not a gap: the
# council sends that map's own front door (council.front_door), never the
# bare `dungeon` job, which is the Deadmines (#202).
CAMPAIGNS = {
    SCARLET_MAP_ID: SCARLET_WINGS,
    BLACKROCK_DEPTHS_MAP_ID: BLACKROCK_DEPTHS,
}

# Every map whose runs are worth counting, for the adapter's own read.  Derived
# rather than written out again: a second list is a second answer, and the one
# that goes stale is always the one the SQL uses.
CAMPAIGN_MAP_IDS = tuple(sorted(CAMPAIGNS))

SUCCESS_OUTCOMES = frozenset({"complete"})


def campaign_stages(map_id: int) -> tuple[tuple[str, int], ...]:
    """The ordered stages of the campaign on this map, or () for no campaign.

    () is "this module names no doors on that map", NOT "that map cannot be
    run".  The caller sends that map's front door in that case
    (council.front_door), and refuses a map with no portal row at all.
    """
    return tuple(CAMPAIGNS.get(int(map_id), ()))


def successful_runs(rows: Iterable[Mapping]) -> dict[str, int]:
    """Count successful runs by durable portal keyword.

    Rows without a keyword or without the explicit completion outcome are not
    counted.  In particular, ``left``, ``wipe``, ``emptied`` and
    ``reset_failed`` are attempts, not proof that a stage was cleared.

    EVERY campaign keyword is a key, including the ones whose count is zero, so
    a caller can tell "nobody has cleared Blackrock Depths" from "this module
    has never heard of Blackrock Depths".
    """
    counts = {keyword: 0 for stages in CAMPAIGNS.values() for keyword, _ in stages}
    for row in rows:
        keyword = str(row.get("portal_keyword") or "")
        outcome = str(row.get("outcome") or "")
        if keyword in counts and outcome in SUCCESS_OUTCOMES:
            counts[keyword] += 1
    return counts


def next_stage(
    completed: Mapping[str, int] | None,
    wanted: int,
    *,
    stages: Sequence[tuple[str, int]],
) -> str | None:
    """Return the first stage of ``stages`` with fewer than ``wanted`` successes.

    ``None`` for ``completed`` means the durable ledger is unavailable.  The
    caller must withhold an ORDERED decision in that case; guessing from the
    family's level would skip lower stages and make a 25-run-per-stage campaign
    impossible to audit.

    ``None`` is also the answer when every stage is at its target, which is a
    different fact with the same shape: this campaign has nothing left to
    order.  The caller decides what a finished campaign means - for a
    single-stage dungeon the family is meant to keep running, it means run it
    again.
    """
    target = int(wanted)
    if target <= 0 or completed is None:
        return None
    for keyword, _ in stages:
        if int(completed.get(keyword, 0) or 0) < target:
            return keyword
    return None


def frontier_stage(stages: Sequence[tuple[str, int]], level: int, *, slack: int) -> str:
    """The HIGHEST stage this family is ready (or ``slack`` short of) for.

    The answer when no ordered campaign can be had: either the ledger is
    unavailable, or every stage of this map's campaign is already at its
    target and the family is to keep running its hardest door.

    ``slack`` is handed in rather than defaulted because it is council.py's
    NEAR_ENOUGH - the same "short, and near enough to try anyway" allowance
    that module extends everywhere else.  A copy of the number here would be a
    second answer able to disagree with the gate the page draws.
    """
    if not stages:
        return ""
    keyword = stages[0][0]
    for name, wants in stages:
        if int(level) + int(slack) >= int(wants):
            keyword = name
    return keyword
