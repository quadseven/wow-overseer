"""Whose turn it is at the family's one travel column, and for how long.

THE COLUMN IS ONE SLOT AND SEVEN PASSES WRITE IT (infra#3703).
`overseer_roster.travel_npc` is one string per character and it is the only
thing in this system that makes anybody walk to a counter. The sell pass wants
a vendor, the town trip wants a repairer, the bank pass wants a banker, the
guild bank pass wants the vault, the auction pass wants an auctioneer, the
forge pass wants a forge and craft_supply wants one named reagent vendor.
Every one of them writes that column through `bridge._write_trade_errand`,
whose economy guard retasks only an IDLE traveller - which is correct, it is
what stops an economy pass erasing a profession errand (mod-overseer#438) -
and which means whichever pass writes first holds the column and every other
pass is refused until it clears.

AND IT IS ONE SLOT FOR THE WHOLE FAMILY, NOT ONE PER CHARACTER. mod-overseer
refuses to send anybody who is not carrying `new rpg`, and goals.py keeps that
strategy on the leader alone (a follower given both wanders off every tick -
measured at a 937-yard spread). So aiming a follower is an UPDATE that moves
nobody, and five rows of a column are in practice one seat. `SLOT_NOT_THE_LEADER`
below is that fact written down once, instead of each pass rediscovering it.

WHAT WENT WRONG WITHOUT THIS. Measured on wow-dev 2026-09-14, minutes apart:

    01:36:36 guild bank: queued 0/5 deposit(s), leader=Grug aimed at
             at:1:-7203.1,-3821.1,8.6
    01:38:37 auction: leader=Grug could not be aimed at an auctioneer - the
             column already holds 'at:1:-7203.1,-3821.1,8.6' and an economy
             errand may only retask an idle traveller, so this pass is starved
             until that one clears (infra#3703)

Nothing there is broken. Each pass did exactly what it should and one of them
lost, for the whole of its cycle, on the timing of who ran first. Over a day
that is not a fair coin: the guild bank pass has produced 68 `no guild bank in
reach` rows in 24 hours and has been starved behind other passes for its entire
life.

WHAT THIS MODULE DECIDES, AND WHAT IT REFUSES TO DECIDE. It answers one
question - "may this pass have the traveller now?" - out of facts the caller
supplies, and it returns a `Decision` the caller executes. It holds no
connection, imports nothing from this package, and knows nothing about vendors,
vaults or auction houses. Which errand is worth running is each pass's own
business and stays there.

THE THREE RULES, IN THE ORDER THEY MATTER.

  1. AN ERRAND THAT CANNOT FINISH MUST NOT HOLD THE SLOT FOR EVER. That is the
     actual defect. A holder keeps the column until it hands it back - the
     `_settle_*` steps in bridge.py already do that when their own queue drains
     - but if it never does, its LEASE runs out and a waiting pass may take it.
     Preemption needs a waiter: an errand nobody else wants is left alone
     however long it runs, because interrupting a working walk that is in
     nobody's way is pure harm.

  2. A RE-ASSERTION DOES NOT RENEW THE LEASE. The clock runs from when the
     errand was first taken, not from the last time its pass said the same
     thing again. Every one of these passes re-asserts its aim on its own
     cycle; a lease renewed by re-assertion would be a lease that never
     expires, which is the bug with an extra mechanism bolted on.

  3. FAIRNESS MUST NOT BECOME STARVATION IN THE OTHER DIRECTION. A cheap
     frequent pass must not permanently outrank a rare important one. So the
     order is longest-waiting-first, and a pass that has just been served
     yields a FREE column to a pass that has been waiting longer than it. The
     yield is bounded: a want that nobody renews goes stale (see
     `WANT_FRESH_SECONDS`) and the column is never held empty for a loop that
     has stopped asking.

WHY A LEASE AND NOT A QUEUE OF ERRANDS. A queue would need this process to own
the errands themselves - to hold them, re-issue them and know when each is done
- and every one of those things already exists once per pass, in the pass, with
the facts it needs (`bank.errand_step`, `towntrip.errand_step`,
`bag_pressure.vendor_errand_step`). Rebuilding that here would be the second
copy of a mechanism this package has been bitten by before. What did not exist
anywhere is arbitration BETWEEN them, and that is all this is.

STATE LIVES IN MEMORY, AND A RESTART COSTS ONE LEASE. There is nowhere to put
it: the overseer tables are mod-overseer's and ship in a db-import image, so a
new table would not reach the realm with this change. A restart therefore
forgets who holds what - and finds the column still set, because the world
keeps it. That case is `Holder.claimant == ""`, an ORPHAN, and it is given
`ORPHAN_LEASE_SECONDS` rather than `LEASE_SECONDS` so that an errand this
process cannot name is never preempted before the world's own backstop would
have given up on it anyway.
"""
from __future__ import annotations

import dataclasses


# HOW LONG ONE PASS MAY KEEP THE TRAVELLER WHILE ANOTHER WAITS.
#
# The number has to clear a real town errand and nothing more. mod-overseer's
# own travel backstop measures a walking bot at 112 yards a minute, and the two
# counters this contention was measured between - the vendor Grog was standing
# at and the Guild Vault the deposit pass wanted - are 121 yards apart in the
# same town. So a town errand's WALK is about a minute, and everything after it
# is the queue draining at the counter, which each pass already ends for itself.
#
# 121 yards at 112 yards a minute is 65 seconds, so 300 is four and a half of
# those walks - and it is also the shortest cycle any of these passes runs on
# (`VENDOR_CYCLE_SECONDS`, `TOWNTRIP_CYCLE_SECONDS` and
# `CRAFT_FORGE_CYCLE_SECONDS` are all 300): a holder therefore always gets at
# least one full cycle of its own to finish and hand back before anything else
# may take the column from it.
LEASE_SECONDS = 300.0

# THE SAME, FOR AN ERRAND THIS PROCESS CANNOT NAME AN OWNER FOR.
#
# After a restart the column can hold an aim with no ledger entry behind it,
# and the honest thing to say about it is "somebody wrote this and it was not
# anybody I remember". mod-overseer gives up on a target it cannot reach after
# TRAVEL_BACKSTOP_SECONDS, which is 20 * 60, so an orphan is left alone for
# exactly that long: past it, the world has stopped believing in the errand
# too, and taking the column is not a race with anything.
ORPHAN_LEASE_SECONDS = 1200.0

# HOW LONG A WANT COUNTS AS LIVE WITHOUT BEING RENEWED.
#
# A want is registered by a pass that ran and was refused, so a living loop
# renews its own want every cycle. The longest of these cycles is 600 seconds
# (bank, guild bank, auction, craft supply); 900 gives a pass one missed cycle
# of slack before the others stop yielding a free column to it. Without this a
# pass that asked once and then stopped needing the traveller could hold the
# whole family's town work still for ever, having walked nowhere, which is the
# bug this module exists to end rather than to re-create facing the other way.
WANT_FRESH_SECONDS = 900.0


# The verdicts. Strings rather than an enum for the reason every other decision
# vocabulary in this package uses strings (`bag_pressure.VENDOR_ERRAND_*`,
# `bank.BANK_ERRAND_*`): they appear in log lines and in test assertions, and a
# name that reads the same in both is worth more than type machinery here.
SLOT_TAKE = "take"
SLOT_HOLD = "hold"
SLOT_WAIT = "wait"
SLOT_PREEMPT = "preempt"
SLOT_CLEAR = "clear"
SLOT_NOT_THE_LEADER = "not the leader"

# The verdicts under which the caller ends up with the traveller. `SLOT_HOLD`
# is in here and writes nothing: the column already says what the caller wanted
# it to say, and re-writing it makes mod-overseer's aim book erase its own state
# and read a standing errand as a brand new one, releasing and re-taking the
# counter hold every time (infra#3708).
GRANTED = (SLOT_TAKE, SLOT_HOLD, SLOT_PREEMPT, SLOT_CLEAR)


@dataclasses.dataclass(frozen=True)
class Holder:
    """Who has the traveller, what they wrote, and since when.

    `claimant` is empty for an ORPHAN - an aim found in the column that this
    process did not put there, or does not remember putting there. `since` is
    a monotonic reading supplied by the caller, never a wall clock: this is a
    duration question and the wall clock moves.
    """
    claimant: str
    character: str
    aim: str
    since: float


@dataclasses.dataclass(frozen=True)
class Want:
    """A pass that asked for the traveller and did not get it.

    Two clocks, and they are different questions. `waiting_since` is how long
    this pass has been starved, which is what decides the order, and it
    survives every re-ask. `last_asked` is whether the pass is still asking at
    all, which is what decides whether anybody should still be yielding to it.
    """
    claimant: str
    waiting_since: float
    last_asked: float


@dataclasses.dataclass(frozen=True)
class Decision:
    """What the caller should do, and the sentence explaining it.

    `release` is the errand that must be handed back BEFORE the write, and it
    is only ever set on a preemption. The caller executes it as a
    compare-and-swap on the aim named here, so a column that changed hands
    between the read that produced this decision and the write that acts on it
    matches nothing and is left alone.
    """
    verdict: str
    reason: str
    claimant: str = ""
    aim: str = ""
    character: str = ""
    release: Holder | None = None
    inherit_since: float | None = None

    @property
    def granted(self) -> bool:
        return self.verdict in GRANTED

    @property
    def writes(self) -> bool:
        """Whether acting on this decision writes the column at all."""
        return self.verdict in (SLOT_TAKE, SLOT_PREEMPT)


def lease_for(holder: Holder | None, lease: float = LEASE_SECONDS,
              orphan_lease: float = ORPHAN_LEASE_SECONDS) -> float:
    """How long this holder may keep the traveller while somebody waits.

    An orphan gets the longer one. See ORPHAN_LEASE_SECONDS: the shorter lease
    is a promise this process can only make about errands it issued itself.
    """
    if holder is None:
        return 0.0
    return orphan_lease if not holder.claimant else lease


def fresh_wants(wants, now: float, want_fresh: float = WANT_FRESH_SECONDS) -> list:
    """The wants still being renewed, oldest wait first.

    Sorted by how long each has been starved, and then by name. The second key
    does nothing on a live realm - two monotonic readings are never equal - and
    exists so the order is the same every run for a test that supplies round
    numbers.

    THE FILTER IS THE HALF THAT MATTERS. A want is registered by a pass that
    ran and was refused, so a living loop renews its own every cycle; one that
    stops being renewed belongs to a pass that no longer wants the traveller,
    and yielding to it would hold the whole family's town work still on behalf
    of nobody.
    """
    live = [w for w in wants if (now - w.last_asked) <= want_fresh]
    return sorted(live, key=lambda w: (w.waiting_since, w.claimant))


def stranded_nonleader_aims(aims, leader: str, *, ground, releasable) -> tuple:
    """Return stale releasable ground aims held by somebody except ``leader``.

    Only the family leader can walk an economy errand. A prior leader change or
    an older writer can leave a positional aim on a follower; mod-overseer then
    refuses to move it, while the non-empty column still suppresses that
    follower's normal drive. The adapter supplies the two policy predicates so
    this function remains pure and does not know which aims are safe to hand
    back.
    """
    if not leader:
        return ()
    return tuple(sorted(
        name for name, aim in (aims or {}).items()
        if name != leader and str(aim or "") and ground(aim) and releasable(aim)
    ))


def _ahead_of(claimant: str, wants, now: float, want_fresh: float) -> list:
    """The live wants that outrank `claimant`'s own."""
    ordered = fresh_wants(wants, now, want_fresh)
    ahead = []
    for want in ordered:
        if want.claimant == claimant:
            break
        ahead.append(want)
    return ahead


def decide(*, claimant: str, character: str, aim: str, leader: str,
           column: str, retaskable, holder: Holder | None, wants,
           last_served, now: float,
           lease: float = LEASE_SECONDS,
           orphan_lease: float = ORPHAN_LEASE_SECONDS,
           want_fresh: float = WANT_FRESH_SECONDS,
           releasable=None) -> Decision:
    """May this pass have the traveller, and what has to happen first.

    Every fact comes in as an argument, including the two the caller has to
    read from the world (`leader` and `column`) and the guard that decides what
    an aim may legally be written over (`retaskable`, which is
    `bridge._retaskable_from(aim)`). Passing that in rather than re-deriving it
    is what keeps this module from becoming a second, quieter copy of the SQL
    guard: THIS NEVER GRANTS A WRITE THE UPDATE WOULD REFUSE, because it asks
    the same tuple the UPDATE's WHERE clause is built from.

    `releasable` answers "could this process hand that aim back?" - it is
    `bridge._is_economy_aim`, and a profession trainer errand answers False, so
    a trainer errand can never be preempted by anybody. Its default is the
    fail-closed one: with no predicate supplied nothing is releasable and
    nothing is ever preempted.

    A STALE `column` CANNOT BECOME A WRONG WRITE, which is the property that
    makes reading it here safe at all. Both effects a decision can carry are
    compare-and-swaps: the release names the exact aim it is handing back, and
    the write carries `_write_trade_errand`'s own `travel_npc IN (...)` guard.
    A column that changed hands in between therefore matches nothing, and the
    worst a stale read costs is one wasted cycle.
    """
    if releasable is None:
        def releasable(_aim):
            return False

    if not aim:
        # A pass with nothing to ask for is not a waiter, and `Slot.want`
        # registers no want for a decision carrying no aim. Answering anything
        # else would let an empty aim hold the column still for a journey
        # nobody wants taken.
        return Decision(
            verdict=SLOT_WAIT,
            reason="%s asked for the traveller without naming an aim, so "
                   "nothing was decided" % claimant,
            claimant=claimant,
            character=character,
        )

    if character != leader:
        # THE ONE SEAT IS THE LEADER'S. mod-overseer refuses to send anybody
        # who is not carrying `new rpg` - "'Ugga' was sent to 'vendor' but does
        # not carry `new rpg` - nothing walks it anywhere" - and it is not
        # merely inert: an aim on a follower is never released, because the
        # arrival check that would release it sits below the refusal, and it
        # bills that character 15 seconds of economy errand budget on every
        # travel poll until it is refused for fifteen minutes.
        return Decision(
            verdict=SLOT_NOT_THE_LEADER,
            reason="%s asked to aim %s, who is not the leader (%s carries "
                   "`new rpg`), so nothing was written - aiming a follower is "
                   "an UPDATE that moves nobody" % (claimant, character, leader or "nobody"),
            claimant=claimant,
            aim=aim,
            character=character,
        )

    holder = _reconcile(holder, leader=leader, column=column, now=now)
    ours = holder is not None and holder.claimant == claimant

    if ours and holder.aim == aim:
        # ALREADY OURS AND ALREADY WRITTEN. Nothing is re-asserted: the column
        # says what this pass wanted it to say, and writing the same word again
        # makes the aim book read a standing errand as a new one. The lease is
        # NOT renewed here, which is rule 2 and the only thing that stops a
        # never-finishing errand living for ever by being asked for again.
        return Decision(
            verdict=SLOT_HOLD,
            reason="%s already holds the traveller %s with %r, taken %ds ago"
                   % (claimant, character, aim, int(now - holder.since)),
            claimant=claimant,
            aim=aim,
            character=character,
            inherit_since=holder.since,
        )

    if holder is not None and holder.aim in tuple(retaskable or ()):
        # A REFINEMENT, AND THE UPDATE WOULD ALLOW IT. `_retaskable_from` lets
        # a named creature entry be written over a plain `vendor` because they
        # are the same errand at two resolutions (infra#3692), and refusing
        # that here would leave that fix inert exactly as an idle-only guard
        # would have. The lease is INHERITED rather than restarted: two passes
        # refining each other's aims must not be able to launder a lease
        # between them and keep the column for ever.
        return Decision(
            verdict=SLOT_TAKE,
            reason="%s refines %s's %r on %s into %r, which is the same errand "
                   "at a sharper resolution" % (
                       claimant, holder.claimant or "an unknown pass",
                       holder.aim, character, aim),
            claimant=claimant,
            aim=aim,
            character=character,
            inherit_since=holder.since,
        )

    if holder is None:
        return _free_column(
            claimant=claimant, character=character, aim=aim, wants=wants,
            last_served=last_served, now=now, want_fresh=want_fresh,
        )
    return _held_column(
        claimant=claimant, character=character, aim=aim, holder=holder,
        wants=wants, now=now, lease=lease, orphan_lease=orphan_lease,
        want_fresh=want_fresh, releasable=releasable,
    )


def decide_idle(*, claimant: str, character: str, leader: str, column: str,
                holder: Holder | None, wants, now: float,
                lease: float = LEASE_SECONDS,
                orphan_lease: float = ORPHAN_LEASE_SECONDS,
                want_fresh: float = WANT_FRESH_SECONDS,
                releasable=None) -> Decision:
    """May this drive have an empty travel column?"""
    if releasable is None:
        def releasable(_aim):
            return False
    if character != leader:
        return Decision(
            verdict=SLOT_NOT_THE_LEADER,
            reason="%s asked to idle %s, who is not the leader" %
                   (claimant, character),
            claimant=claimant,
            character=character,
        )
    holder = _reconcile(holder, leader=leader, column=column, now=now)
    if holder is None:
        return Decision(
            verdict=SLOT_CLEAR,
            reason="%s has the idle traveller; the column was already free" %
                   claimant,
            claimant=claimant,
            character=character,
        )
    return _held_column(
        claimant=claimant, character=character, aim="", holder=holder,
        wants=wants, now=now, lease=lease, orphan_lease=orphan_lease,
        want_fresh=want_fresh, releasable=releasable, clearing=True,
    )


def _free_column(*, claimant: str, character: str, aim: str, wants,
                 last_served, now: float, want_fresh: float) -> Decision:
    """Nobody is holding the traveller. Is it this pass's turn to take it?

    SPLIT OUT OF `decide` RATHER THAN INLINE, so that the three questions -
    "may this pass be aimed at all", "is the column free", "whose turn is it" -
    are three things to read instead of one. `decide` keeps the guards, which
    are the ones a reader has to see first.
    """
    ahead = _ahead_of(claimant, wants, now, want_fresh)
    mine_served = last_served.get(claimant)
    # WHO IS OWED THE NEXT TURN. Only a pass that has been waiting longer than
    # this one (that is what `ahead` means) AND has not had the traveller since
    # this one did. A pass that has never been served at all is owed it
    # outright; a pass that has never been served ITSELF owes nobody, because
    # it cannot have taken a turn from anybody.
    yielded = [] if mine_served is None else [
        want for want in ahead
        if last_served.get(want.claimant) is None
        or mine_served > last_served[want.claimant]
    ]
    if yielded:
        # YIELDING A FREE COLUMN, WHICH IS THE HALF THAT MAKES THIS FAIR. This
        # pass could take it - nobody is holding it - but a pass that has been
        # waiting longer than this one, and that has not had the traveller
        # since this one did, is owed the next turn. Without this a 300-second
        # pass simply wins every race against a 600-second one for ever, which
        # is how the guild bank pass spent its whole life.
        first = yielded[0]
        return Decision(
            verdict=SLOT_WAIT,
            reason="%s stands aside: the column is free but %s has been "
                   "waiting %ds for it and %s had the traveller more "
                   "recently" % (claimant, first.claimant,
                                 int(now - first.waiting_since), claimant),
            claimant=claimant,
            aim=aim,
            character=character,
        )
    return Decision(
        verdict=SLOT_TAKE,
        reason="%s takes the traveller %s for %r; the column was free"
               % (claimant, character, aim),
        claimant=claimant,
        aim=aim,
        character=character,
    )


def _held_column(*, claimant: str, character: str, aim: str, holder: Holder,
                 wants, now: float, lease: float, orphan_lease: float,
                 want_fresh: float, releasable, clearing: bool = False) -> Decision:
    """Somebody else has the traveller. Wait, or take it off them?

    THE ONLY PLACE A PREEMPTION IS DECIDED, and it takes three things to agree:
    the aim must be one this process could hand back, the lease must have run
    out, and no other pass may have been starved longer. Any one of them
    missing is a wait.
    """
    held_for = now - holder.since
    allowed = lease_for(holder, lease, orphan_lease)
    owner = holder.claimant or "an unknown writer"

    if not releasable(holder.aim):
        # NOT OURS TO HAND BACK, SO NOT OURS TO TAKE. A profession trainer
        # errand is a standing plan that outlives a town run and carries
        # `learn_skill` with it; blanking one is mod-overseer#438's bug, and
        # `_release_trade_errand` refuses it for the same reason one step
        # later. A pass waits here however long it takes.
        return Decision(
            verdict=SLOT_WAIT,
            reason="%s waits: %s carries %r, which is not an errand the "
                   "economy may hand back, so no lease applies to it"
                   % (claimant, character, holder.aim),
            claimant=claimant,
            aim=aim,
            character=character,
        )

    if held_for < allowed:
        return Decision(
            verdict=SLOT_WAIT,
            reason="%s waits for %s's %r on %s, held %ds of a %ds lease "
                   "(%ds left)" % (claimant, owner, holder.aim, character,
                                   int(held_for), int(allowed),
                                   int(allowed - held_for)),
            claimant=claimant,
            aim=aim,
            character=character,
        )

    ahead = _ahead_of(claimant, wants, now, want_fresh)
    if ahead:
        # THE LEASE HAS RUN OUT BUT IT IS NOT THIS PASS'S TURN. Somebody has
        # been starved longer, and handing the column to whoever happened to
        # run first at the moment the lease lapsed is the same coin toss this
        # module exists to replace.
        return Decision(
            verdict=SLOT_WAIT,
            reason="%s waits: %s's %r on %s is past its %ds lease, but %s has "
                   "been waiting %ds longer and takes the slot first"
                   % (claimant, owner, holder.aim, character, int(allowed),
                      ahead[0].claimant,
                      int(_own_wait(claimant, wants, now) - ahead[0].waiting_since)),
            claimant=claimant,
            aim=aim,
            character=character,
        )

    issue = "infra#3728" if clearing else "infra#3703"
    return Decision(
        verdict=SLOT_CLEAR if clearing else SLOT_PREEMPT,
        reason="%s takes the traveller %s from %s: %r has held the family's "
               "one travel column for %ds, past its %ds lease, and an errand "
               "that cannot finish must not hold it for ever (%s)"
               % (claimant, character, owner, holder.aim, int(held_for),
                  int(allowed), issue),
        claimant=claimant,
        aim=aim,
        character=character,
        release=holder,
    )


def _own_wait(claimant: str, wants, now: float) -> float:
    """When this pass started waiting, or now if it has not been waiting."""
    for want in wants:
        if want.claimant == claimant:
            return want.waiting_since
    return now


def _reconcile(holder: Holder | None, *, leader: str, column: str,
               now: float) -> Holder | None:
    """What the ledger's holder becomes once the column has been read.

    THE WORLD IS THE AUTHORITY AND THIS MEMORY IS NOT. mod-overseer clears
    `travel_npc` itself when a walk arrives, when its own backstop gives up on
    an unreachable target, and when an errand has killed a character often
    enough to be called off. None of that comes back to this process except as
    an emptied column, so the ledger has to learn it by looking.

      * An empty column means the errand ended, whoever ended it.
      * A column holding something else means somebody wrote it that this
        process did not record - another writer, or this process before a
        restart. It becomes an ORPHAN: a real holder, with no owner, on the
        long lease.
      * A holder recorded against a character who is no longer the leader is
        forgotten. The aim on that row is not this slot's business any more,
        and it moves nobody: only the leader travels.

    IDEMPOTENT, AND CALLED TWICE ON PURPOSE. `Slot.want` runs it to update its
    own memory and `decide` runs it again on the value it is handed, so the
    pure function is correct for a caller that has no ledger at all. The second
    run sees a holder that already matches the column and returns it unchanged,
    clock included.
    """
    if not column:
        return None
    if holder is not None and holder.character == leader and holder.aim == column:
        return holder
    return Holder(claimant="", character=leader, aim=column, since=now)


class Slot:
    """The ledger: who holds the traveller, who is waiting, who was served.

    A plain object with no I/O, held by the bridge for the life of the process.
    `want` decides and records the wait; `settle` records what actually
    happened when the caller acted on the decision. They are separate because
    the write can fail on a race the decision could not see, and a ledger that
    recorded intentions rather than outcomes would be a second source of truth
    that quietly disagrees with the column.
    """

    def __init__(self, lease: float = LEASE_SECONDS,
                 orphan_lease: float = ORPHAN_LEASE_SECONDS,
                 want_fresh: float = WANT_FRESH_SECONDS,
                 releasable=None) -> None:
        self.lease = float(lease)
        self.orphan_lease = float(orphan_lease)
        self.want_fresh = float(want_fresh)
        self.releasable = releasable
        self.holder: Holder | None = None
        self._wants: dict = {}
        self._served: dict = {}

    @property
    def wants(self) -> list:
        """Every registered want, in no particular order. Read for tests and
        for the log line that says how many passes are queued."""
        return list(self._wants.values())

    def want(self, *, claimant: str, character: str, aim: str, leader: str,
             column: str, retaskable, now: float,
             urgent: bool = False) -> Decision:
        """Decide, and register the wait if the answer is no."""
        self.holder = _reconcile(self.holder, leader=leader, column=column,
                                 now=now)
        # A full bag is a loot-blocking failure, not an ordinary queue wait.
        # An orphaned economy aim can otherwise hold the traveller for the
        # world's 20-minute backstop after this process restarts. Urgent callers
        # may shorten only the lease used by the pure decision; the
        # `releasable` predicate still refuses profession or operator aims.
        lease = 0.0 if urgent else self.lease
        orphan_lease = 0.0 if urgent else self.orphan_lease
        decision = decide(
            claimant=claimant, character=character, aim=aim, leader=leader,
            column=column, retaskable=retaskable, holder=self.holder,
            wants=self.wants, last_served=self._served, now=now,
            lease=lease, orphan_lease=orphan_lease,
            want_fresh=self.want_fresh, releasable=self.releasable,
        )
        if decision.verdict == SLOT_WAIT and decision.aim:
            self._note_wait(claimant, now)
        return decision

    def want_idle(self, *, claimant: str, character: str, leader: str,
                  column: str, now: float) -> Decision:
        """Ask for the travel column to become empty, without a successor."""
        self.holder = _reconcile(self.holder, leader=leader, column=column,
                                 now=now)
        decision = decide_idle(
            claimant=claimant, character=character, leader=leader,
            column=column, holder=self.holder, wants=self.wants, now=now,
            lease=self.lease, orphan_lease=self.orphan_lease,
            want_fresh=self.want_fresh, releasable=self.releasable,
        )
        if decision.verdict == SLOT_WAIT:
            self._note_wait(claimant, now)
        return decision

    def settle(self, decision: Decision, taken: bool, now: float) -> None:
        """Record what the world did with the decision.

        `taken` is whether the leader now carries this pass's aim. A refused
        write is not a failure to report here - the guard in
        `_write_trade_errand` can legitimately lose a race - it is a wait like
        any other, and it is registered as one so the pass keeps its place in
        the order rather than starting again from the back.
        """
        if not decision.granted:
            return
        if not taken:
            # THE COLUMN IS NOT OURS, SO THE LEDGER MUST NOT SAY IT IS. A
            # ledger that recorded the intention would hand this pass a lease
            # it is not using, and would tell the next pass to wait for an
            # errand nobody is on.
            self.holder = None
            self._note_wait(decision.claimant, now)
            return
        if decision.verdict == SLOT_CLEAR:
            self.holder = None
            self._wants.pop(decision.claimant, None)
            self._served[decision.claimant] = now
            return
        name = decision.claimant
        since = decision.inherit_since if decision.inherit_since is not None else now
        self.holder = Holder(claimant=name, character=decision.character,
                             aim=decision.aim, since=since)
        self._wants.pop(name, None)
        self._served[name] = now

    def forget(self, claimant: str) -> None:
        """Drop a pass's want without serving it.

        For a pass that has decided it no longer needs the traveller at all.
        Nothing calls this yet; it exists because `WANT_FRESH_SECONDS` is the
        slow way to reach the same state and a pass that KNOWS is allowed to
        say so.
        """
        self._wants.pop(claimant, None)

    def _note_wait(self, claimant: str, now: float) -> None:
        if not claimant:
            return
        existing = self._wants.get(claimant)
        waiting_since = existing.waiting_since if existing else now
        self._wants[claimant] = Want(claimant=claimant,
                                      waiting_since=waiting_since,
                                      last_asked=now)


def report(decision: Decision) -> str:
    """The one sentence every pass logs about the traveller.

    ONE WORDING FOR SEVEN PASSES, on purpose. Before this each pass wrote its
    own version of "could not be aimed", three of them said only "already on
    somebody else's errand", and none of them said for how long or what would
    end it - so a starved pass and a broken one read identically in the log,
    which is what made infra#3703 take a night of measuring to see at all.
    """
    return "town slot: %s" % decision.reason
