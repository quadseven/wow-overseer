"""A grouped follower's own walk is held, not written for the world to refuse (#995).

THE WALL. mod-overseer walks a guild bot to a mailbox, a vendor, a trainer or
a spawn through one gate (`MailWalkGate`), and that gate refuses a character
whose group somebody else leads: "character is grouped as a follower". A
follower moves by following, and the module will not steer it away from its
leader. The four walks ride four kinds - `walk-to-mailbox` on 'mail',
`walk-to-vendor` on 'buy', `walk-to-trainer` on 'cast' and `walk-to-spawn` on
'job' - so the one wall shows in the command table as all four.

WHAT WENT WRONG WITHOUT THIS. In the six hours to 2026-10-14 23:50Z the bridge
wrote 174 such rows to 16 guild members (66 buy, 56 mail, 27 cast, 25 job).
The module calls the refusal retryable, which is true, because a group breaks
up. So every guild pass asked again on its next cycle, and every ask was a row
that did nothing.

WHAT THIS DECIDES. Whether one walk row may be written for one character now,
from what the snapshot says of its group and from the last time the world
refused it as a follower. A follower's walk is HELD until it is ungrouped. The
leader cannot carry it, because each walk's arrival belongs to the walker: a
trainer walk trains the walker, and a vendor or mailbox walk is followed by
the walker's own buy or letter, which wants the walker at the counter. The pass
that asked keeps its errand and asks again on a later cycle. While the answer
is known, the row is not written.

THE TWO FACTS, AND WHICH WINS.

  snapshot   `overseer_snapshot.group_leader` is the leader's guid, the
             character's own guid when it leads, and 0 when it is ungrouped:
             the same `Group::GetLeaderGUID` the module's gate reads. A fresh
             row saying "follows" holds the walk.
  refusal    The world's own answer, kept for REFUSAL_HOLD_SECONDS. It holds
             the walk while no snapshot row NEWER than the refusal says the
             member has left the group, so a missing or stale snapshot cannot
             let the same row be written straight back.

PURE: facts and a clock reading in, a sentence out. The bridge reads and logs.
"""

from __future__ import annotations

from dataclasses import dataclass

# The module's MailWalkRefusal::Follower, which every walk goal answers with
# unchanged (WalkRefusalFor maps only the literals that name a destination).
REFUSAL = "character is grouped as a follower"

# The four walk verbs the gate stands in front of.
WALK_VERBS = ("walk-to-mailbox", "walk-to-vendor", "walk-to-trainer", "walk-to-spawn")

# How long a follower refusal holds a member no newer snapshot row clears:
# long enough to cover several passes, short enough that a member whose
# snapshot never comes back is asked about again within the half hour.
REFUSAL_HOLD_SECONDS = 1800.0


@dataclass(frozen=True)
class Group:
    """What one fresh snapshot row says of a character's group.

    `leader_guid` is the row's `group_leader`. `leader` is that guid's name
    from the characters table, "" when it has none. `age` is how many seconds
    old the row is.
    """

    guid: int
    leader_guid: int
    leader: str = ""
    age: float = 0.0

    @property
    def follows(self) -> bool:
        """True when somebody else leads this character's group."""
        return bool(self.leader_guid) and self.leader_guid != self.guid


def group_from_row(row) -> Group | None:
    """A Group from one snapshot read; None when there was no fresh row."""
    if not row:
        return None
    try:
        return Group(
            guid=int(row.get("guid") or 0),
            leader_guid=int(row.get("group_leader") or 0),
            leader=str(row.get("leader_name") or ""),
            age=max(0.0, float(row.get("age") or 0)),
        )
    except (TypeError, ValueError):
        return None


def is_walk(command) -> bool:
    """Is this command one of the four walks the follower gate refuses?"""
    return str(command or "").startswith(WALK_VERBS)


def _verb(command) -> str:
    return str(command).split(" ", 1)[0]


def _leader_words(group: Group) -> str:
    return group.leader or "guid %d" % group.leader_guid


class Holds:
    """The members the world last refused a walk as followers, and when."""

    def __init__(self) -> None:
        self._refused: dict[str, float] = {}

    def note_answer(self, name, detail, now) -> None:
        """Remember a follower refusal from one command row's answer."""
        if name and str(detail or "").strip() == REFUSAL:
            self._refused[str(name)] = float(now)

    def held(self, name, command, group: Group | None, now) -> str:
        """Why `command` must not be written for `name` now; "" when it may."""
        if not is_walk(command):
            return ""
        name = str(name)
        if group is not None and group.follows:
            return (
                "%s is grouped as a follower of %s, so its %s is held until it is "
                "ungrouped rather than written for the world to refuse"
                % (name, _leader_words(group), _verb(command))
            )
        refused = self._refused.get(name)
        if refused is None:
            return ""
        since = float(now) - refused
        if since >= REFUSAL_HOLD_SECONDS or (group is not None and group.age < since):
            del self._refused[name]
            return ""
        return (
            "the world refused %s's last walk %d seconds ago as grouped as a "
            "follower and no newer snapshot says it left the group, so its %s is "
            "held until it is ungrouped" % (name, int(since), _verb(command))
        )
