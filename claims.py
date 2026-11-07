"""One claims module: who holds the travel column and who holds a member.

Passes ask this module instead of unioning occupancy sets or releasing
aims themselves. It owns both kinds of hold behind one interface: why
each hold exists, when it expires, and which release is legal.

COLUMN HOLDS. The family's one travel column is townslot's Slot: who
has the traveller, what they wrote, and since when, held in memory so
a bridge restart costs one lease. This module surfaces townslot's
decide logic unchanged (not rewritten here) and adds no rule of its
own: the lease, the orphan lease and the release guard stay
townslot's, spelled once there.

MEMBER HOLDS. A family at the bag floor is held in town until a town
pass makes room. That hold is judged on evidence by bag_pressure's
bag_hold_progress, and this module surfaces the same judgment as a
MemberHold: why it exists, when it expires, and which members the
legal release names. Holds are in-process only, exactly as before:
a fresh store holds nothing, and the bridge's own memo persistence
layer (unaffected by this module) is what survives a restart.

OCCUPANCY. Every member another pass has on a walk reads as busy
through busy_members, so a new pass cannot forget a set. A death
knight stranded in its starting zone is freed through
stranded_knights, the one place that names which sets held it.

PER-COHORT SLOTS. new_column_slot builds one in-memory column ledger.
Claims.slot_for keeps one per cohort key, so each family has its own
slot and never sees another family's holder.
"""

from __future__ import annotations

import dataclasses

import bag_pressure
import townslot

# The column vocabulary, re-exported so a caller names one module.
SLOT_TAKE = townslot.SLOT_TAKE
SLOT_HOLD = townslot.SLOT_HOLD
SLOT_WAIT = townslot.SLOT_WAIT
SLOT_PREEMPT = townslot.SLOT_PREEMPT
SLOT_CLEAR = townslot.SLOT_CLEAR
SLOT_NOT_THE_LEADER = townslot.SLOT_NOT_THE_LEADER
SLOT_GIVE_UP = townslot.SLOT_GIVE_UP
GRANTED = townslot.GRANTED

Holder = townslot.Holder
Want = townslot.Want
Decision = townslot.Decision
Reservation = townslot.Reservation
Cohort = townslot.Cohort
Slot = townslot.Slot

decide = townslot.decide
decide_idle = townslot.decide_idle
lease_for = townslot.lease_for
leases_for_ask = townslot.leases_for_ask
fresh_wants = townslot.fresh_wants
stranded_nonleader_aims = townslot.stranded_nonleader_aims
stranded_aims_far_from_doors = townslot.stranded_aims_far_from_doors
urgent_ground_release = townslot.urgent_ground_release
campaign_owns_traveller = townslot.campaign_owns_traveller
is_town_stop = townslot.is_town_stop
stop_yards = townslot.stop_yards
report = townslot.report
reserved_wait = townslot.reserved_wait
walk_rank = townslot.walk_rank
urgency_cuts = townslot.urgency_cuts
reserve_rank = townslot.reserve_rank
other_cohorts = townslot.other_cohorts
stalled = townslot.stalled

LEASE_SECONDS = townslot.LEASE_SECONDS
ORPHAN_LEASE_SECONDS = townslot.ORPHAN_LEASE_SECONDS
GATHER_LEASE_SECONDS = townslot.GATHER_LEASE_SECONDS
REAGENT_TRIP_LEASE_SECONDS = townslot.REAGENT_TRIP_LEASE_SECONDS
WANT_FRESH_SECONDS = townslot.WANT_FRESH_SECONDS
STARVED_SECONDS = townslot.STARVED_SECONDS
URGENT_BACKOFF_SECONDS = townslot.URGENT_BACKOFF_SECONDS
URGENT_BACKOFF_CAP_SECONDS = townslot.URGENT_BACKOFF_CAP_SECONDS
STALL_SECONDS = townslot.STALL_SECONDS
STOP_CLAIMANTS = townslot.STOP_CLAIMANTS
AWAY_CLAIMANTS = townslot.AWAY_CLAIMANTS
STAGING_PHASES = townslot.STAGING_PHASES
RESERVE_SECONDS = townslot.RESERVE_SECONDS
RESERVE_ORDER = townslot.RESERVE_ORDER
BAG_ROOM_CLAIMANTS = townslot.BAG_ROOM_CLAIMANTS


def new_column_slot(
    lease: float = LEASE_SECONDS,
    orphan_lease: float = ORPHAN_LEASE_SECONDS,
    releasable=None,
    long_leases=None,
    firm_leases=None,
):
    """One in-memory column ledger, for one family's cohort.

    The bridge keeps one per roster family, created on first use. A
    restart forgets every holder in it, exactly as townslot documents:
    the column itself survives in the world and is adopted as an
    orphan on the longer lease.
    """
    return townslot.Slot(
        lease=lease,
        orphan_lease=orphan_lease,
        releasable=releasable,
        long_leases=long_leases,
        firm_leases=firm_leases,
    )


def column_expiry(
    holder: Holder | None,
    now: float,
    lease: float = LEASE_SECONDS,
    orphan_lease: float = ORPHAN_LEASE_SECONDS,
    long_leases=None,
) -> float:
    """When this holder's lease runs out, or now when there is none."""
    if holder is None:
        return now
    return holder.since + lease_for(holder, lease, orphan_lease, long_leases)


def release_legal(holder: Holder | None, releasable) -> bool:
    """Whether this process may hand that holder's aim back.

    A trainer errand answers False and can never be preempted by
    anybody: the predicate is the same guard the write's WHERE clause
    is built from, so this never grants a release the update refuses.
    """
    if holder is None or releasable is None:
        return False
    try:
        return bool(releasable(holder.aim))
    except Exception:
        return False


@dataclasses.dataclass(frozen=True)
class Release:
    """Whether a ground aim may be handed back, and why not.

    `why` names the walk being kept (a quest walk under a released
    bag hold) so a refused release reads as a reason, not a silence.
    `expires_at` is when the underlying hold times out, when known.
    """

    legal: bool
    why: str
    expires_at: float | None = None


def may_release_ground(
    *,
    aim: str,
    pressure: bool,
    in_run: bool,
    errand_active: bool = False,
    hold_released: bool = False,
    ground,
) -> bool:
    """Whether bag pressure may interrupt a stale positional town aim.

    The released-bag-hold case is the pass-against-pass rule: once
    the hold is released the family was sent questing, and the same
    bags are no reason to tear down the walk it was sent on.
    """
    return townslot.urgent_ground_release(
        aim=aim,
        pressure=pressure,
        in_run=in_run,
        errand_active=errand_active,
        hold_released=hold_released,
        ground=ground,
    )


def ground_release(
    *,
    aim: str,
    pressure: bool,
    in_run: bool,
    errand_active: bool = False,
    hold_released: bool = False,
    ground,
    hold_expires_at: float | None = None,
) -> Release:
    """The legality of releasing `aim` under bag pressure, in words."""
    legal = may_release_ground(
        aim=aim,
        pressure=pressure,
        in_run=in_run,
        errand_active=errand_active,
        hold_released=hold_released,
        ground=ground,
    )
    if legal:
        why = (
            "bag pressure may hand back the stale positional aim %r; "
            "no active town errand, no dungeon run and no released "
            "bag hold stand in the way" % aim
        )
    else:
        why = (
            "the aim %r stays: no bag pressure, a run or an active "
            "errand owns it, or the bag hold is released so the "
            "quest walk must be kept" % aim
        )
    return Release(legal=legal, why=why, expires_at=hold_expires_at)


@dataclasses.dataclass(frozen=True)
class MemberHold:
    """One family's hold at the bag floor: why, when, and what release.

    `why` names the members at the floor. `expires_at` is when the
    hold times out with no slot gained. `legal_release` is the
    stuck members once released, else None: no town pass may release
    the hold early for any other reason.
    """

    names: tuple = ()
    best: tuple = ()
    since: float = 0.0
    seen: float = 0.0
    released: bool = False
    window: float = bag_pressure.BAG_HOLD_STUCK_SECONDS
    floor: int = bag_pressure.TOWN_RUN_FREE_SLOTS

    @property
    def held(self) -> bool:
        return bool(self.best)

    @property
    def stuck(self) -> tuple:
        return bag_pressure.bag_hold_stuck(
            bag_pressure.BagHoldProgress(
                best=self.best,
                since=self.since,
                seen=self.seen,
                released=self.released,
            )
        )

    @property
    def legal_release(self) -> tuple | None:
        stuck = self.stuck
        return stuck if stuck else None

    @property
    def why(self) -> str:
        held = ", ".join("%s at %d" % (name, free) for name, free in self.best)
        return (
            "held at the bag floor (%s) until a town pass makes room; "
            "releases after %d minutes with no slot gained"
            % (held, int(self.window // 60))
        )

    @property
    def expires_at(self) -> float:
        return self.since + self.window


def member_hold_observe(
    names,
    free_slots: dict,
    now: float,
    running: bool = False,
    previous: MemberHold | None = None,
) -> MemberHold | None:
    """The hold after this reading, or None when nobody is at the floor.

    The same evidence bag_pressure judges: while some member is at
    the floor the clock restarts whenever any of them gains over the
    best it has had in this hold, and BAG_HOLD_STUCK_SECONDS with no
    gain releases the hold until nobody is at the floor.
    """
    prior = None
    if previous is not None:
        prior = bag_pressure.BagHoldProgress(
            best=previous.best,
            since=previous.since,
            seen=previous.seen,
            released=previous.released,
        )
    progress = bag_pressure.bag_hold_progress(prior, free_slots, now, running=running)
    if progress is None:
        return None
    return MemberHold(
        names=tuple(sorted(str(name) for name in names or ())),
        best=progress.best,
        since=progress.since,
        seen=progress.seen,
        released=progress.released,
    )


class MemberClaims:
    """In-process member holds, one per family member-set.

    Plain memory, like the column ledger: a new store holds nothing
    and a restart forgets every hold. The bridge's memo persistence
    sits above this store and is unchanged.
    """

    def __init__(self) -> None:
        self._holds: dict = {}

    @staticmethod
    def key(names) -> tuple:
        return tuple(sorted(str(name) for name in names or ()))

    def observe(
        self,
        names,
        free_slots: dict,
        now: float,
        running: bool = False,
    ) -> MemberHold | None:
        key = self.key(names)
        hold = member_hold_observe(
            key,
            free_slots,
            now,
            running=running,
            previous=self._holds.get(key),
        )
        if hold is None:
            self._holds.pop(key, None)
        else:
            self._holds[key] = hold
        return hold

    def current(self, names) -> MemberHold | None:
        return self._holds.get(self.key(names))

    def released(self, names) -> bool:
        hold = self.current(names)
        return hold is not None and hold.released

    def stuck(self, names) -> tuple:
        hold = self.current(names)
        return hold.stuck if hold is not None else ()

    def reset(self, names) -> None:
        self._holds.pop(self.key(names), None)


def busy_members(*sets) -> set:
    """Every member another pass has put on a walk.

    The one union: a new pass joins by naming its set here and cannot
    forget one, because forgetting is the bug this exists to end.
    Each argument is a mapping (its keys are the members) or an
    iterable of names.
    """
    busy = set()
    for names in sets:
        if not names:
            continue
        busy.update(names.keys() if hasattr(names, "keys") else names)
    return busy


def _held_map(held) -> dict:
    if held is None:
        return {}
    if hasattr(held, "items"):
        return {str(label): set(names or ()) for label, names in held.items()}
    return {str(label): set(names or ()) for label, names in held}


def is_stranded_knight(member, death_knight=None, start_map=None) -> bool:
    """Whether this member is the stranded death knight.

    A death knight in its starting zone can reach nobody: a gear
    hand-over run, a crafter walk, a guild ask or a dungeon run that
    names it walks nowhere and holds it for good.
    """
    if death_knight is None or start_map is None:
        from classquest import DEATH_KNIGHT, DEATH_KNIGHT_START_MAP

        if death_knight is None:
            death_knight = DEATH_KNIGHT
        if start_map is None:
            start_map = DEATH_KNIGHT_START_MAP
    if not getattr(member, "online", False):
        return False
    try:
        if int(member.class_id) != death_knight:
            return False
    except (AttributeError, TypeError, ValueError):
        return False
    return getattr(member, "map_id", None) == start_map


def stranded_knights(
    members, own_steps, held, *, death_knight=None, start_map=None
) -> set:
    """The stranded knights to free: held by another pass, not by their own step.

    `members` are read for online, class, map and name, as the guild
    jobs pass reads them. `own_steps` maps members on the step this
    pass is running; only that step holds a knight. `held` maps a
    label to the names that label holds, as busy_members unions them.
    """
    from classquest import DEATH_KNIGHT, DEATH_KNIGHT_START_MAP

    death = DEATH_KNIGHT if death_knight is None else death_knight
    start = DEATH_KNIGHT_START_MAP if start_map is None else start_map
    held_map = _held_map(held)
    held_names = set()
    for names in held_map.values():
        held_names.update(names)
    own = set(own_steps.keys()) if hasattr(own_steps, "keys") else set(own_steps)
    freed = set()
    for member in members or ():
        if member.name not in held_names:
            continue
        if member.name in own:
            continue
        if is_stranded_knight(member, death, start):
            freed.add(member.name)
    return freed


def stranded_held_labels(members, own_steps, held) -> dict:
    """member -> the held labels that name it, for the log line.

    The caller logs which sets held a freed knight so the next pass
    shows which pass starved it.
    """
    held_map = _held_map(held)
    out = {}
    for member in members or ():
        labels = tuple(
            sorted(label for label, names in held_map.items() if member.name in names)
        )
        if labels:
            out[member.name] = labels
    return out


class Claims:
    """The one interface: column and member holds in one place.

    Column slots live per cohort key in memory; member holds live in
    one MemberClaims store. Nothing here touches the world or a
    database, so a restart forgets holds exactly as before.
    """

    def __init__(
        self,
        lease: float = LEASE_SECONDS,
        orphan_lease: float = ORPHAN_LEASE_SECONDS,
        releasable=None,
        long_leases=None,
        firm_leases=None,
    ) -> None:
        self.kwargs = dict(
            lease=lease,
            orphan_lease=orphan_lease,
            releasable=releasable,
            long_leases=long_leases,
            firm_leases=firm_leases,
        )
        self.releasable = releasable
        self._slots: dict = {}
        self.members = MemberClaims()

    def slot_for(self, cohort=None):
        """The column ledger for one family's cohort key."""
        key = str(getattr(cohort, "key", cohort) or "")
        if key not in self._slots:
            self._slots[key] = new_column_slot(**self.kwargs)
        return self._slots[key]

    def want_column(self, cohort=None, **ask) -> Decision:
        """May this pass have the traveller now, and what says so."""
        return self.slot_for(cohort).want(**ask)

    def member_observe(
        self, names, free_slots: dict, now: float, running: bool = False
    ) -> MemberHold | None:
        return self.members.observe(names, free_slots, now, running=running)

    def member_released(self, names) -> bool:
        return self.members.released(names)

    def member_stuck(self, names) -> tuple:
        return self.members.stuck(names)

    def release_ground(self, **kw) -> Release:
        return ground_release(**kw)

    def busy(self, *sets) -> set:
        return busy_members(*sets)

    def freed_knights(self, members, own_steps, held) -> set:
        return stranded_knights(members, own_steps, held)
