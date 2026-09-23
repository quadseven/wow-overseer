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

     AND THE ORDER IS THE WAIT ITSELF, NOT THE FRESHNESS OF THE LAST ASK
     (infra#4208). Those are two different questions and the second one is
     only ever asked about the passes being yielded TO. `_ahead_of` asked it
     about the ASKER as well, so a pass whose cycle is longer than the
     freshness window was ranked behind every other waiter however long it
     had really been starved - and, measured on wow-dev 2026-09-19, that one
     pass took the whole column down: 3 grants in 3.3 hours against 25, with
     four of seven consumers never served at all. Rule 3 is only worth
     anything if the order it names is the real one.

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

# THE SAME, FOR A WALK THAT LEAVES TOWN (infra#4183).
#
# LEASE_SECONDS is dimensioned for a town errand and says so: "121 yards apart
# in the same town ... 300 is four and a half of those walks". A gathering trip
# is not that walk. The family's crafters out-levelled their professions, so
# the nearest node the weakest gatherer can open is in another zone, and the
# distance was measured twice against the leader's own live position:
#
#     2588 yards  (leader in zone 1377)
#     2344 yards  (leader in zone 490, four minutes later)
#
# mod-overseer logs its own effective rate - straight-line distance against
# wall-clock arrival, so pathing is already inside the number:
#
#     15:41:43  'Ugga' sent to 'at:0:-11208.5,1685.34,25.76' - creature 0 at 2391 yards
#     15:47:28  'Ugga' reached 'at:0:-11208.5,1685.34,25.76' - errand done, releasing
#
# 2391 yards in 345 seconds is 416 yards a minute, which puts those two trips
# at 373 and 338 seconds - both past a 300 second lease, neither near a
# different order of magnitude. So this is a mis-dimensioned constant rather
# than a missing subsystem, and the fix is a value dimensioned for the walk.
#
# 373 for the longest measured trip, plus one GOAL_INTERVAL (60) for the
# arrival to be SEEN, is 433; rounded up to the next half-minute, 450. It is
# derived rather than generous on purpose: this makes gathering the longest
# holder of the family's one column, and the guild bank pass has already been
# measured waiting over twenty minutes for it.
#
# IT IS A LEASE AND NOT AN EXEMPTION, which is the distinction infra#3703
# exists to keep. A gathering aim is a ground aim, so `_is_economy_aim` calls
# it releasable and it stays preemptible - at 450 seconds by a starved pass,
# and immediately by an urgent one, because `Slot.want` zeroes every lease
# when a full bag is blocking loot. The trainer-errand path above is the
# exemption shape, and this deliberately is not it: an errand that cannot
# finish still must not hold the column for ever.
GATHER_LEASE_SECONDS = 450.0

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

# WHY THERE IS NO GRACE ON THE HANDOVER, WHICH WAS MEASURED RATHER THAN
# ASSUMED (infra#4208).
#
# When a lease lapses and somebody has been starved longer than the pass that
# is asking, the asker is refused and the column is kept for the pass whose
# turn it is. The obvious complaint is that nothing bounds that: the dead
# errand goes on holding the family's one column while the pass that is owed
# the turn waits for its own cycle to come round. Measured on wow-dev
# 2026-09-19 over 80 minutes, five holders and every one of them preempted
# rather than handed back, 1742 of 4560 seconds were an errand past its lease
# that nobody was allowed to take.
#
# SO A GRACE WAS BUILT AND IT MADE BOTH NUMBERS WORSE. Simulating the seven
# real pass cycles over six hours, "the asker takes it once the owed pass has
# had N seconds to turn up":
#
#     no grace    42 grants / 6h   worst wait  3300s   nobody starved
#     1200s       42 grants / 6h   worst wait  3300s   nobody starved
#      600s       40 grants / 6h   worst wait  4500s   nobody starved
#      300s       36 grants / 6h   worst wait 21600s   4 of 7 never served
#
# The grace is rule 3 being repealed by degrees: every turn it takes from a
# slow pass is handed to a fast one, so the slow pass waits another whole
# round, and at a short enough value it never wins at all. That is the failure
# `TheFreeColumnIsYieldedToWhoeverIsOwedIt` exists to prevent, arriving through
# a different door.
#
# WHAT ACTUALLY BOUNDED IT was `_ahead_of` ranking a pass by its own recorded
# wait instead of by the freshness of its last ask. The unbounded hold in that
# 80 minute window - 840 seconds and still running when the window closed -
# was not the honest deferral at all. It was two passes being told in turn to
# stand aside for each other, which needed one of them to be ranked behind a
# pass that started waiting later, and `_ahead_of` can no longer say that. The
# deferrals that remain are bounded by the owed pass's own cycle, which is the
# thing that ends them; the three in that window ran 330, 204 and 362 seconds.
# A safety valve for a state the ordering can no longer reach would be a
# mechanism with nothing behind it.

# HOW LONG AN URGENT PASS THAT ACHIEVED NOTHING WAITS BEFORE IT MAY PREEMPT
# AGAIN (infra#4191).
#
# `Slot.want` zeroes every lease for an urgent caller and `_free_column` /
# `_held_column` let it skip the queue, because a full bag blocks loot and
# waiting 300 seconds to fix that throws drops away. Both are right. What was
# missing is the counterpart to infra#3703's rule: an errand that cannot
# finish must not hold the column for ever. #3703 bounds an ORDINARY holder
# with a lease; nothing bounded an urgent one, so a pass justified by a
# pressure it is structurally unable to relieve re-took the traveller every
# cycle, indefinitely.
#
# Measured on wow-dev over 20 minutes (infra#4191): the vendor pass took the
# column urgently on three consecutive cycles, found no vendor within reach
# each time, sold nothing, and the family moved 21 yards. `gather` won the
# column once and lost it 28 seconds later.
#
# THE SHAPE IS THE ONE THE PACKAGE ALREADY USES for a repeated action that
# keeps not working: `SHARE_RETRY_MINUTES * 2**n` capped at
# `SHARE_BACKOFF_CAP_HOURS`, where "a delivered share resets the streak"
# (infra#2892, 167 identical attempts). Same three parts here - double on
# each fruitless grant, cap it, and let a grant that actually did something
# clear the streak.
#
# The base is one vendor cycle (VENDOR_CYCLE_SECONDS is 300), so the first
# suppression costs exactly one turn rather than a guess. The cap is
# ORPHAN_LEASE_SECONDS, reusing this file's existing ceiling on the same
# grounds it was chosen for: past 1200 seconds the world has stopped
# believing in the errand too.
#
# SUPPRESSED URGENCY IS NOT A REFUSAL. The pass still asks, still queues,
# still gets the ordinary lease and its ordinary place in line. It loses only
# the right to cut in front of everything else on the strength of a pressure
# it has repeatedly failed to relieve. That is the difference between a bound
# and a ban, and it is the same difference infra#3703 drew.
URGENT_BACKOFF_SECONDS = 300.0
URGENT_BACKOFF_CAP_SECONDS = ORPHAN_LEASE_SECONDS

# A WALK THE WORLD CANNOT FINISH IS GIVEN UP BY ITS OWNER (#227).
#
# Measured on wow-dev 2026-09-23: clearance aimed the Horde leader at the
# Crossroads mailbox, and mod-overseer said of it "made no progress in 18
# attempts - releasing the errand before upstream can teleport it". The world
# lets go of a walk like that and leaves the column alone, because the aim is
# not its to blank. Clearance asked again every cycle, got `hold`, and held the
# traveller for as long as it kept asking. A pass that says how far its leader
# is from its aim is measured against that here: no `PROGRESS_YARDS` of ground
# gained in `STALL_SECONDS`, while still further out than `ARRIVED_YARDS`, is a
# walk that cannot land. The owner hands it back and does not ask for that aim
# again for `SPENT_SECONDS`, so it can pick another target or drop the trip.
STALL_SECONDS = 240.0
PROGRESS_YARDS = 5.0
ARRIVED_YARDS = 15.0
SPENT_SECONDS = 1800.0


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
# The owner hands back an aim it cannot reach (#227). Not granted.
SLOT_GIVE_UP = "give up"

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


def lease_for(
    holder: Holder | None,
    lease: float = LEASE_SECONDS,
    orphan_lease: float = ORPHAN_LEASE_SECONDS,
    long_leases=None,
) -> float:
    """How long this holder may keep the traveller while somebody waits.

    An orphan gets the longer one. See ORPHAN_LEASE_SECONDS: the shorter lease
    is a promise this process can only make about errands it issued itself.

    `long_leases` is {claimant: seconds} for the passes whose walk is longer
    than a town errand's, and it is keyed on the CLAIMANT rather than on the
    aim (infra#4183). The aim cannot carry it: a gathering aim and a forge aim
    are both `at:<map>:<x>,<y>,<z>` and nothing in the string says which walk
    it is. The claimant is the pass that asked, which is exactly the thing
    whose trip length is known.

    A claimant with no entry gets `lease`, so adding one pass's longer walk
    cannot quietly change anybody else's.
    """
    if holder is None:
        return 0.0
    if not holder.claimant:
        return orphan_lease
    if long_leases:
        try:
            return float(long_leases.get(holder.claimant, lease))
        except (TypeError, ValueError):
            return lease
    return lease


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
    return tuple(
        sorted(
            name
            for name, aim in (aims or {}).items()
            if name != leader and str(aim or "") and ground(aim) and releasable(aim)
        )
    )


@dataclasses.dataclass(frozen=True)
class Cohort:
    """One family from `overseer_roster.family`, and who walks it (#150).

    `key` is the roster's own `family` value, `leader` the character carrying
    `lead = 1` in that family (the one mod-overseer walks), and `names` every
    enabled member. The bridge keeps one `Slot` per key, because each family
    has its own traveller and its own column.
    """

    key: str
    leader: str
    names: tuple = ()


def other_cohorts(rows, own_names) -> tuple:
    """Every roster family this bridge does not already drive, with a leader.

    `rows` carry name, family and lead, one per enabled roster row. A family
    sharing any name with `own_names` is this bridge's own and is left out, so
    no character is passed twice. The leader is the `lead = 1` row; failing
    that, the member whose name is the family key (the column defaults to the
    head's name); failing both, the family is left out, because without a
    traveller a vendor errand has nobody to walk and every aim would be
    stranded.
    """
    own = {str(name) for name in own_names}
    grouped: dict = {}
    leads: dict = {}
    for row in rows:
        key = str(row.get("family") or "").strip()
        name = str(row.get("name") or "").strip()
        if not key or not name:
            continue
        grouped.setdefault(key, set()).add(name)
        try:
            if int(row.get("lead") or 0) == 1:
                leads.setdefault(key, set()).add(name)
        except (TypeError, ValueError):
            continue
    out = []
    for key in sorted(grouped):
        names = grouped[key]
        if names & own:
            continue
        lead = sorted(leads.get(key, ()))
        leader = lead[0] if lead else (key if key in names else "")
        if not leader:
            continue
        out.append(Cohort(key=key, leader=leader, names=tuple(sorted(names))))
    return tuple(out)


def urgent_ground_release(*, aim: str, pressure: bool, in_run: bool, ground) -> bool:
    """Whether bag pressure may interrupt a stale positional town aim."""
    return bool(pressure and not in_run and str(aim or "") and ground(aim))


def _ahead_of(claimant: str, wants, now: float, want_fresh: float) -> list:
    """The live wants that outrank `claimant`'s own.

    RANKED BY THIS PASS'S OWN RECORDED WAIT, NOT BY WHETHER ITS LAST ASK IS
    STILL FRESH (infra#4208). Freshness answers "is this loop still asking?",
    which is the right filter for the passes being yielded TO. It is the wrong
    filter for the pass DOING the asking, because a pass that is asking right
    now is by definition still asking.

    WHAT THE OLD READING COST. The previous version walked `fresh_wants` and
    stopped at the claimant's own entry - so a claimant whose entry was not in
    that list, because its cycle is longer than `WANT_FRESH_SECONDS`, fell off
    the end of the loop and was handed the WHOLE live queue as "ahead of me",
    however long it had actually been starved. Measured on wow-dev 2026-09-19,
    three minutes apart, with a dead `auctioneer` aim on an expired 300s lease
    sitting between the two passes the whole time:

        14:36:49 guild bank waits: ... but flight has been waiting 1020s
                 longer and takes the slot first
        14:39:48 flight waits: ... but guild bank has been waiting -1020s
                 longer and takes the slot first

    THE TWO NUMBERS ARE THE SAME MAGNITUDE WITH OPPOSITE SIGNS, and that is the
    whole proof. `flight` began waiting at 13:39:48 and `guild bank` at
    13:56:48, so the gap between them really is 1020 seconds and `flight` really
    is the older. The first line reads that correctly. The second has the two
    roles the wrong way round, because `flight`'s own last ask had just gone
    stale and it was therefore ranked behind every live want - including one
    that started seventeen minutes after it. Each pass is told in turn to stand
    aside for the other, neither ever takes the column, and that dead errand
    went on being held for another eight minutes. In a seven-pass simulation of
    the same cycles one such pass drops the whole column from 25 grants in 3.3
    hours to 3, with four of the seven never served at all.

    A claimant with no want AT ALL is unchanged: `_own_wait` answers `now` for
    it, every live want sorts before that, and a first ask still queues behind
    everybody exactly as it did before.
    """
    mine = (_own_wait(claimant, wants, now), claimant)
    return [
        want
        for want in fresh_wants(wants, now, want_fresh)
        if (want.waiting_since, want.claimant) < mine
    ]


def decide(
    *,
    claimant: str,
    character: str,
    aim: str,
    leader: str,
    column: str,
    retaskable,
    holder: Holder | None,
    wants,
    last_served,
    now: float,
    urgent: bool = False,
    lease: float = LEASE_SECONDS,
    orphan_lease: float = ORPHAN_LEASE_SECONDS,
    long_leases=None,
    want_fresh: float = WANT_FRESH_SECONDS,
    releasable=None,
) -> Decision:
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
        #
        # AN ORPHAN'S CLOCK IS NOT INHERITED (#225). Laundering takes two
        # owners, and an orphan has none. It also runs on the 1200s orphan
        # lease, so the old clock carried over to the ordinary 300s lease is
        # already spent. Measured on wow-dev: the bag trip refined an orphan
        # '3487' 730s after it was first seen, held a lease that was 430s
        # expired on arrival, and lost the leader to clearance 17 yards from
        # the bag vendor.
        return Decision(
            verdict=SLOT_TAKE,
            reason="%s refines %s's %r on %s into %r, which is the same errand "
            "at a sharper resolution"
            % (
                claimant,
                holder.claimant or "an unknown pass",
                holder.aim,
                character,
                aim,
            ),
            claimant=claimant,
            aim=aim,
            character=character,
            inherit_since=holder.since if holder.claimant else None,
        )

    if holder is None:
        return _free_column(
            claimant=claimant,
            character=character,
            aim=aim,
            wants=wants,
            last_served=last_served,
            now=now,
            want_fresh=want_fresh,
            urgent=urgent,
        )
    return _held_column(
        claimant=claimant,
        character=character,
        aim=aim,
        holder=holder,
        wants=wants,
        now=now,
        lease=lease,
        orphan_lease=orphan_lease,
        long_leases=long_leases,
        want_fresh=want_fresh,
        releasable=releasable,
        urgent=urgent,
    )


def decide_idle(
    *,
    claimant: str,
    character: str,
    leader: str,
    column: str,
    holder: Holder | None,
    wants,
    now: float,
    lease: float = LEASE_SECONDS,
    orphan_lease: float = ORPHAN_LEASE_SECONDS,
    long_leases=None,
    want_fresh: float = WANT_FRESH_SECONDS,
    releasable=None,
) -> Decision:
    """May this drive have an empty travel column?"""
    if releasable is None:

        def releasable(_aim):
            return False

    if character != leader:
        return Decision(
            verdict=SLOT_NOT_THE_LEADER,
            reason="%s asked to idle %s, who is not the leader" % (claimant, character),
            claimant=claimant,
            character=character,
        )
    holder = _reconcile(holder, leader=leader, column=column, now=now)
    if holder is None:
        return Decision(
            verdict=SLOT_CLEAR,
            reason="%s has the idle traveller; the column was already free" % claimant,
            claimant=claimant,
            character=character,
        )
    return _held_column(
        claimant=claimant,
        character=character,
        aim="",
        holder=holder,
        wants=wants,
        now=now,
        lease=lease,
        orphan_lease=orphan_lease,
        long_leases=long_leases,
        want_fresh=want_fresh,
        releasable=releasable,
        clearing=True,
    )


def _free_column(
    *,
    claimant: str,
    character: str,
    aim: str,
    wants,
    last_served,
    now: float,
    want_fresh: float,
    urgent: bool = False,
) -> Decision:
    """Nobody is holding the traveller. Is it this pass's turn to take it?

    SPLIT OUT OF `decide` RATHER THAN INLINE, so that the three questions -
    "may this pass be aimed at all", "is the column free", "whose turn is it" -
    are three things to read instead of one. `decide` keeps the guards, which
    are the ones a reader has to see first.
    """
    # A loot-blocking bag failure is not an ordinary fairness wait. If the
    # column is free, urgent maintenance takes it even when an older auction
    # or bank want is registered.
    ahead = [] if urgent else _ahead_of(claimant, wants, now, want_fresh)
    mine_served = last_served.get(claimant)
    # WHO IS OWED THE NEXT TURN. Only a pass that has been waiting longer than
    # this one (that is what `ahead` means) AND has not had the traveller since
    # this one did. A pass that has never been served at all is owed it
    # outright; a pass that has never been served ITSELF owes nobody, because
    # it cannot have taken a turn from anybody.
    yielded = (
        []
        if mine_served is None
        else [
            want
            for want in ahead
            if last_served.get(want.claimant) is None
            or mine_served > last_served[want.claimant]
        ]
    )
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
            "recently"
            % (claimant, first.claimant, int(now - first.waiting_since), claimant),
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


def _held_column(
    *,
    claimant: str,
    character: str,
    aim: str,
    holder: Holder,
    wants,
    now: float,
    lease: float,
    orphan_lease: float,
    want_fresh: float,
    releasable,
    clearing: bool = False,
    urgent: bool = False,
    long_leases=None,
) -> Decision:
    """Somebody else has the traveller. Wait, or take it off them?

    THE ONLY PLACE A PREEMPTION IS DECIDED, and it takes three things to agree:
    the aim must be one this process could hand back, the lease must have run
    out, and no other pass may have been starved longer. Any one of them
    missing is a wait.

    THE THIRD ONE RANKS ON THE WAIT AND NOT ON THE ASK (infra#4208). `ahead`
    comes from `_ahead_of`, which compares every live want against this
    claimant's own recorded `waiting_since`, so nothing in it can be a pass
    that started waiting later. When that was not true, two passes each got
    told in turn to stand aside for the other and a lapsed lease stayed held by
    nobody's errand for as long as both kept asking.
    """
    held_for = now - holder.since
    allowed = lease_for(holder, lease, orphan_lease, long_leases)
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
            "(%ds left)"
            % (
                claimant,
                owner,
                holder.aim,
                character,
                int(held_for),
                int(allowed),
                int(allowed - held_for),
            ),
            claimant=claimant,
            aim=aim,
            character=character,
        )

    # Urgent bag pressure may preempt an expired releasable errand even when a
    # different pass has been waiting longer. Ordinary fairness is unchanged.
    ahead = [] if urgent else _ahead_of(claimant, wants, now, want_fresh)
    if ahead:
        # THE LEASE HAS RUN OUT BUT IT IS NOT THIS PASS'S TURN. Somebody has
        # been starved longer, and handing the column to whoever happened to
        # run first at the moment the lease lapsed is the same coin toss this
        # module exists to replace.
        return Decision(
            verdict=SLOT_WAIT,
            reason="%s waits: %s's %r on %s is past its %ds lease, but %s has "
            "been waiting %ds longer and takes the slot first"
            % (
                claimant,
                owner,
                holder.aim,
                character,
                int(allowed),
                ahead[0].claimant,
                int(_own_wait(claimant, wants, now) - ahead[0].waiting_since),
            ),
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
        % (claimant, character, owner, holder.aim, int(held_for), int(allowed), issue),
        claimant=claimant,
        aim=aim,
        character=character,
        release=holder,
    )


# How long one pass may keep the traveller reserved (#225). The orphan lease,
# the ceiling this file already puts on an errand nobody can hand back.
RESERVE_SECONDS = ORPHAN_LEASE_SECONDS


@dataclasses.dataclass(frozen=True)
class Reservation:
    """One pass owns the traveller for a stated reason, from `since`."""

    claimant: str
    since: float
    why: str

    def live(self, now: float, limit: float = RESERVE_SECONDS) -> bool:
        return now - self.since < limit


def reserved_wait(
    claimant: str, character: str, aim: str, reservation, now: float
) -> Decision | None:
    """A wait for any other pass while a live reservation stands, else None.

    THE ONE OWNER OF THE AIM (#225). A campaign withheld for bag space is
    cured only by a vendor stop. Fairness handed the traveller to clearance
    17 yards short of the bag vendor, so the campaign stayed withheld and
    the family walked off to post letters. While the reservation is live,
    every other pass waits. The reserving pass gets no new rights: it still
    asks the slot like any other pass.
    """
    if reservation is None or not reservation.live(now):
        return None
    if claimant == reservation.claimant:
        return None
    return Decision(
        verdict=SLOT_WAIT,
        reason="%s waits: %s owns the traveller %s while %s (%ds of %ds)"
        % (
            claimant,
            reservation.claimant,
            character,
            reservation.why,
            int(now - reservation.since),
            int(RESERVE_SECONDS),
        ),
        claimant=claimant,
        aim=aim,
        character=character,
    )


def _own_wait(claimant: str, wants, now: float) -> float:
    """When this pass started waiting, or now if it has not been waiting."""
    for want in wants:
        if want.claimant == claimant:
            return want.waiting_since
    return now


def _reconcile(
    holder: Holder | None, *, leader: str, column: str, now: float
) -> Holder | None:
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


def campaign_owns_traveller(active_job: str, leader_job: str, withheld: bool) -> bool:
    """Whether a family's campaign wants its leader for staging right now (#227).

    `active_job` is the dungeon job of the family's active queue entry ("" when
    none is active), `leader_job` is the job on the leader's roster row, and
    `withheld` is `jev_activity.withheld` for the family. The queue writes the
    job when it starts or re-asserts an entry and a withhold or a Jev
    interlude takes it off again, so a leader carrying the head's job is a
    leader the coordinator is about to stage. Town errands resume the moment
    any of the three says otherwise.
    """
    job = str(active_job or "").strip().lower()
    return bool(job) and str(leader_job or "").strip().lower() == job and not withheld


def stalled(best: float, best_at: float, distance: float, now: float) -> bool:
    """Whether a walk that is `distance` yards out has stopped closing (#227).

    `best` is the nearest the leader has been to this aim and `best_at` when
    that was. A leader inside `ARRIVED_YARDS` has arrived and is not stalled.
    """
    if distance <= ARRIVED_YARDS:
        return False
    return now - best_at >= STALL_SECONDS and distance > best - PROGRESS_YARDS


class Slot:
    """The ledger: who holds the traveller, who is waiting, who was served.

    A plain object with no I/O, held by the bridge for the life of the process.
    `want` decides and records the wait; `settle` records what actually
    happened when the caller acted on the decision. They are separate because
    the write can fail on a race the decision could not see, and a ledger that
    recorded intentions rather than outcomes would be a second source of truth
    that quietly disagrees with the column.
    """

    def __init__(
        self,
        lease: float = LEASE_SECONDS,
        orphan_lease: float = ORPHAN_LEASE_SECONDS,
        want_fresh: float = WANT_FRESH_SECONDS,
        releasable=None,
        long_leases=None,
    ) -> None:
        self.lease = float(lease)
        self.orphan_lease = float(orphan_lease)
        self.want_fresh = float(want_fresh)
        self.releasable = releasable
        # {claimant: seconds} for passes whose walk leaves town (infra#4183).
        # Empty by default, so a caller that names none behaves exactly as it
        # did before this existed.
        self.long_leases = dict(long_leases or {})
        self.holder: Holder | None = None
        self._wants: dict = {}
        self._served: dict = {}
        # {claimant: (consecutive fruitless urgent grants, suppressed until)}
        # for infra#4191. Empty for every pass that never claims urgency, and
        # cleared the moment one of them achieves something.
        self._fruitless: dict = {}
        # The pass that owns the traveller for a stated reason (#225), or None.
        self.reservation: Reservation | None = None
        # Why the family's campaign owns the traveller (#227), or "" when it
        # does not. Set and cleared by the bridge's queue pass every cycle.
        self.campaign = ""
        # Orphan ground aims already handed back for the campaign (#227).
        self._yielded: set = set()
        # {(claimant, aim): (best distance, when)} for walks with a distance.
        self._progress: dict = {}
        # {(claimant, aim): when given up} for walks that could not land.
        self._spent: dict = {}

    def reserve(self, claimant: str, now: float, why: str) -> None:
        """Give `claimant` the traveller until it unreserves or the hold ends.

        NOT RENEWED BY ASKING AGAIN, for rule 2's reason: a hold renewed on
        every cycle never ends. A new claimant replaces the old one.
        """
        if not claimant:
            return
        if self.reservation is not None and self.reservation.claimant == claimant:
            return
        self.reservation = Reservation(claimant=claimant, since=now, why=why)

    def reserved_by(self, claimant: str, now: float) -> bool:
        """Whether `claimant` holds a live reservation right now."""
        r = self.reservation
        return r is not None and r.claimant == claimant and r.live(now)

    def unreserve(self, claimant: str) -> None:
        """End `claimant`'s reservation; another pass's is left alone."""
        if self.reservation is not None and self.reservation.claimant == claimant:
            self.reservation = None

    def yield_to_campaign(self, why: str) -> None:
        """The family's campaign owns the traveller until `campaign_over` (#227)."""
        self.campaign = str(why or "")

    def campaign_over(self) -> None:
        """Town errands may ask for the traveller again (#227)."""
        self.campaign = ""

    def campaign_release(
        self, *, leader: str, column: str, now: float, ground
    ) -> Holder | None:
        """The aim on the leader the bridge must hand back for the campaign.

        ONLY WHAT A BRIDGE PASS WROTE (#227). The coordinator's own staging,
        corridor and berth aims are `at:` aims too, so the column alone cannot
        say whose an `at:` aim is. Three answers, in order:

          * an aim this ledger records for a named pass is that pass's, and
            the bridge is its owner;
          * a keyword or creature-entry aim is written by the bridge and never
            by the coordinator;
          * an ORPHAN ground aim (one this process does not remember writing,
            which is every aim after a restart) is handed back only after it
            has stood unchanged for `LEASE_SECONDS`, and only once per aim.
            If it was the coordinator's after all, the coordinator re-arms it
            on its next poll and says so at WARN; once per aim string bounds
            that to one re-arm per point per process.

        A trainer aim is not `releasable` and is not answered here: the bridge
        hands that one back through its own compare-and-swap.
        """
        self.holder = _reconcile(self.holder, leader=leader, column=column, now=now)
        holder = self.holder
        if holder is None or not self.releasable or not self.releasable(holder.aim):
            return None
        if holder.claimant or not ground(holder.aim):
            return holder
        if holder.aim in self._yielded or now - holder.since < self.lease:
            return None
        self._yielded.add(holder.aim)
        return holder

    def released_for_campaign(self, holder: Holder, released: bool) -> None:
        """Record that `campaign_release`'s answer was acted on."""
        if released and self.holder is not None and self.holder.aim == holder.aim:
            self.holder = None

    def spent(self, claimant: str, aim: str, now: float) -> bool:
        """Whether `claimant` gave `aim` up as unreachable within SPENT_SECONDS."""
        at = self._spent.get((claimant, aim))
        return at is not None and now - at < SPENT_SECONDS

    def gave_up(self, decision: Decision, released: bool, now: float) -> None:
        """Record that a SLOT_GIVE_UP was acted on (#227)."""
        self._progress.pop((decision.claimant, decision.aim), None)
        if released and self.holder is not None and self.holder.aim == decision.aim:
            self.holder = None
            self._served[decision.claimant] = now

    def urgency_suppressed_until(self, claimant: str) -> float:
        """When this claimant may preempt on urgency again (0.0 = now).

        Read by the caller for its log line, so "this pass is in backoff" is a
        state somebody can see rather than an absence of one.
        """
        return self._fruitless.get(claimant, (0, 0.0))[1]

    def fruitless(self, claimant: str, now: float) -> float:
        """Record that an urgent grant to `claimant` achieved nothing.

        Returns the moment its urgency comes back. The caller decides what
        "nothing" means - this module cannot see whether a sale was written -
        and the streak doubles for as long as the answer keeps being nothing.
        """
        if not claimant:
            return 0.0
        streak = self._fruitless.get(claimant, (0, 0.0))[0] + 1
        wait = min(
            URGENT_BACKOFF_SECONDS * (2 ** (streak - 1)), URGENT_BACKOFF_CAP_SECONDS
        )
        until = now + wait
        self._fruitless[claimant] = (streak, until)
        return until

    def productive(self, claimant: str) -> None:
        """Record that an urgent grant to `claimant` did something.

        Clears the streak outright rather than decrementing it: the pass has
        demonstrated it can finish, so the next failure starts from one turn
        again and not from wherever the last bad run left off.
        """
        self._fruitless.pop(claimant, None)

    @property
    def wants(self) -> list:
        """Every registered want, in no particular order. Read for tests and
        for the log line that says how many passes are queued."""
        return list(self._wants.values())

    def want(
        self,
        *,
        claimant: str,
        character: str,
        aim: str,
        leader: str,
        column: str,
        retaskable,
        now: float,
        urgent: bool = False,
        distance: float | None = None,
    ) -> Decision:
        """Decide, and register the wait if the answer is no.

        `distance` is how many yards the leader stands from a ground aim, for
        a pass that can say. It is what lets an owner give up a walk the world
        cannot finish (#227); a pass that passes None is never given up on.
        """
        self.holder = _reconcile(self.holder, leader=leader, column=column, now=now)
        if self.campaign:
            # THE CAMPAIGN FIRST, AHEAD OF EVERY RESERVATION AND LEASE (#227).
            # Not registered as a wait: the order is rebuilt when town errands
            # resume, rather than handing the first free column to whichever
            # pass happened to ask most often during a run.
            return Decision(
                verdict=SLOT_WAIT,
                reason="%s waits: the family's campaign owns the traveller %s "
                "(%s), and town errands resume when it is withheld or done"
                % (claimant, character, self.campaign),
                claimant=claimant,
                aim=aim,
                character=character,
            )
        if self.spent(claimant, aim, now):
            return Decision(
                verdict=SLOT_WAIT,
                reason="%s gave up %r on %s as a walk that cannot land, and "
                "does not ask for it again for %ds"
                % (claimant, aim, character, int(SPENT_SECONDS)),
                claimant=claimant,
                aim=aim,
                character=character,
            )
        held = reserved_wait(claimant, character, aim, self.reservation, now)
        if held is not None:
            self._note_wait(claimant, now)
            return held
        # AN URGENT PASS THAT KEEPS ACHIEVING NOTHING STOPS BEING URGENT, for
        # as long as its backoff runs (infra#4191). This is deliberately the
        # first thing that happens to `urgent`, so everything below - the
        # zeroed leases, the skipped queue - reads the bounded answer rather
        # than the claimed one. A pass in backoff is not refused; it falls
        # back to the ordinary lease and its ordinary turn.
        if urgent and now < self.urgency_suppressed_until(claimant):
            urgent = False
        # A full bag is a loot-blocking failure, not an ordinary queue wait.
        # An orphaned economy aim can otherwise hold the traveller for the
        # world's 20-minute backstop after this process restarts. Urgent callers
        # may shorten only the lease used by the pure decision; the
        # `releasable` predicate still refuses profession or operator aims.
        lease = 0.0 if urgent else self.lease
        orphan_lease = 0.0 if urgent else self.orphan_lease
        # ZEROED WITH THE OTHER TWO, and that is the whole reason a long lease
        # is safe to grant (infra#4183). A gathering walk is the longest hold
        # on this column, so the one thing that must still cut through it is a
        # full bag blocking loot. Leaving it out here would make the longer
        # lease an exemption rather than a lease.
        long_leases = {} if urgent else self.long_leases
        decision = decide(
            claimant=claimant,
            character=character,
            aim=aim,
            leader=leader,
            column=column,
            retaskable=retaskable,
            holder=self.holder,
            wants=self.wants,
            last_served=self._served,
            now=now,
            urgent=urgent,
            lease=lease,
            orphan_lease=orphan_lease,
            long_leases=long_leases,
            want_fresh=self.want_fresh,
            releasable=self.releasable,
        )
        if decision.verdict == SLOT_WAIT and decision.aim:
            self._note_wait(claimant, now)
        if decision.verdict == SLOT_HOLD and distance is not None:
            return self._measure(decision, float(distance), now)
        return decision

    def _measure(self, decision: Decision, distance: float, now: float) -> Decision:
        """A held walk that has stopped closing becomes a give-up (#227)."""
        key = (decision.claimant, decision.aim)
        best, best_at = self._progress.get(key, (distance, now))
        if stalled(best, best_at, distance, now):
            self._spent[key] = now
            return Decision(
                verdict=SLOT_GIVE_UP,
                reason="%s gives up %r on %s: %d yards out and no %d yards "
                "gained in %ds, so it is a walk the world cannot finish and "
                "is not asked for again for %ds"
                % (
                    decision.claimant,
                    decision.aim,
                    decision.character,
                    int(distance),
                    int(PROGRESS_YARDS),
                    int(now - best_at),
                    int(SPENT_SECONDS),
                ),
                claimant=decision.claimant,
                aim=decision.aim,
                character=decision.character,
                release=self.holder,
            )
        if key not in self._progress or distance <= best - PROGRESS_YARDS:
            self._progress[key] = (distance, now)
        return decision

    def want_idle(
        self, *, claimant: str, character: str, leader: str, column: str, now: float
    ) -> Decision:
        """Ask for the travel column to become empty, without a successor."""
        self.holder = _reconcile(self.holder, leader=leader, column=column, now=now)
        held = reserved_wait(claimant, character, "", self.reservation, now)
        if held is not None:
            self._note_wait(claimant, now)
            return held
        decision = decide_idle(
            claimant=claimant,
            character=character,
            leader=leader,
            column=column,
            holder=self.holder,
            wants=self.wants,
            now=now,
            lease=self.lease,
            orphan_lease=self.orphan_lease,
            long_leases=self.long_leases,
            want_fresh=self.want_fresh,
            releasable=self.releasable,
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
        if decision.writes:
            # A new walk is measured from where it starts (#227).
            self._progress.pop((name, decision.aim), None)
        since = decision.inherit_since if decision.inherit_since is not None else now
        self.holder = Holder(
            claimant=name, character=decision.character, aim=decision.aim, since=since
        )
        self._wants.pop(name, None)
        self._served[name] = now

    def adopt(self, *, claimant: str, character: str, aim: str, now: float) -> None:
        """Record a write this ledger did not arbitrate (infra#4194).

        NOT A CLAIM, AND DELIBERATELY NOT ONE. `want` decides whose turn it is;
        this says only "that value in the column is mine" about a write that
        has already happened. Three passes write `travel_npc` without asking
        for a turn - `_aim_for_plea`, `_send_trade_errand` and
        `_goal_drive_quest` - because none of them is a town errand queueing
        for the traveller. Making them queue would be a different change with a
        different argument; this one only stops the ledger mistaking their
        writes for a stranger's.

        WHAT IT COSTS TO LEAVE THEM UNRECORDED, measured on wow-dev. `_reconcile`
        rebuilds the holder from the column on every `want()`, and any value it
        does not recognise becomes `Holder(claimant="", since=now)` - an ORPHAN
        on the 1200s lease, with the clock starting again. So an unledgered
        write does not merely go unnoticed: it evicts the pass that legitimately
        held the column and re-arms a twenty-minute lease against nobody. Three
        passes doing that on their ordinary cycle is why the stall had no upper
        bound rather than costing one lease per restart.

        A RELEASE NEEDS NO EQUIVALENT. An unledgered release empties the column,
        and `_reconcile`'s first branch already turns an empty column into
        `None` - the honest answer, and the same one the world's own clearing
        produces. Only writes manufacture orphans, which is why this takes an
        aim and there is no `disown`.

        THE LEASE IS THE ORDINARY ONE. An adopted holder is a real holder with a
        real owner, so it expires like any other and `long_leases` applies if the
        claimant has one. That is the point: the column stops being held by a
        stranger nobody can out-wait.
        """
        if not claimant or not character or not aim:
            return
        self.holder = Holder(claimant=claimant, character=character, aim=aim, since=now)

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
        self._wants[claimant] = Want(
            claimant=claimant, waiting_since=waiting_since, last_asked=now
        )


def report(decision: Decision) -> str:
    """The one sentence every pass logs about the traveller.

    ONE WORDING FOR SEVEN PASSES, on purpose. Before this each pass wrote its
    own version of "could not be aimed", three of them said only "already on
    somebody else's errand", and none of them said for how long or what would
    end it - so a starved pass and a broken one read identically in the log,
    which is what made infra#3703 take a night of measuring to see at all.
    """
    return "town slot: %s" % decision.reason
