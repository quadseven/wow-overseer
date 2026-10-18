"""The names a member's step reads, in the order it reads them.

guildjobs._member_step runs its rungs through two helpers (_quest_first, then
_upkeep_first; Refs #962). The tests that pin which rung comes first read the
rung names in order; this reads them through the helpers, each expanded where
the orchestrator calls it, so a rung moved into a helper keeps its place.
"""

import guildjobs

PIECES = ("_quest_first", "_upkeep_first")


def names():
    out = []
    for name in guildjobs._member_step.__code__.co_names:
        if name in PIECES:
            out.extend(getattr(guildjobs, name).__code__.co_names)
        else:
            out.append(name)
    return tuple(out)
