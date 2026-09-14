"""What is waiting in the family's mailboxes, and what it takes to get it out.

THE CAPABILITY IS BUILT AND NOTHING USES IT, the third time in this package.
mod-overseer's `2026_09_05_03_overseer_mail.sql` added `kind='mail'` and
`DoMail` implements five verbs against it - `send`, `take-item`, `take-money`,
`return`, `delete` - each driven through the core's own WorldSession mail
handlers with a mailbox in reach. Counted against the live command log on
2026-09-13, `overseer_command` held 182,576 rows and NOT ONE of them was
`kind='mail'`. The executor had never been asked for anything.

IT IS LIVE, WHICH WAS CHECKED RATHER THAN INFERRED FROM THE ENUM. Two probe
rows were issued against the running wow-dev worldserver the same day, both
chosen so that the only possible outcome was a refusal: `probe-not-a-verb` came
back `error` / `malformed mail command` with `"retryable":false`, and
`take-money mail:4294967295` came back `error` / `character is on a flight
path` with `"retryable":true`. A world image that did not carry this executor
would have answered neither.

WHAT THAT HAS COST, MEASURED THE SAME DAY. The realm held 556 letters carrying
538 attachments, of which 21 letters and 9 attachments belonged to the family,
and one of them (`messageType = 2`, an auction house settlement) was sitting on
4,100 copper addressed to a character whose purse the guild bank pass reads
every ten minutes. Nothing in this process had ever read the `mail` table at
all. The auction pass states the same gap from the other end: it BUYS and does
not FEED, because a bought reagent arrives by mail and `DriveCraft` reads the
bags.

WHAT THIS MODULE DECIDES, AND WHAT IT DELIBERATELY DOES NOT. It decides which
letters can be collected right now and in what order, and it budgets the
collection against the room the bags actually have. It does NOT decide whether
an item is worth having: everything already in a character's own mailbox is
that character's, the postage is paid, and `disposition.decide` gets its turn
afterwards through the bank, vendor and give passes that already read the bags.
Asking a second module whether to accept your own post would be a judgement
with no second answer.

    disposition    one item   -> one route, once it is in a bag
    mailbox        one family -> the ordered takes that put it in one

SENDING IS NOT HERE, AND THE REASON IS A GATE RATHER THAN A PREFERENCE.
`DoMail`'s send branch resolves the recipient with
`ObjectAccessor::FindPlayerByName` and refuses `recipient is not online`
otherwise (mod_overseer.cpp), so the executor can only post to a character who
is standing in the world at that moment - which is the case the existing
`kind='give'` and `kind='trade'` passes already cover at close range, and the
opposite of what mail is for. The core's own `HandleSendMail` falls back to
`sCharacterCache->GetCharacterGuidByName` and has no such limit, so this is the
module's narrowing rather than the game's. Filed rather than worked around.

FAIL CLOSED, the same rule `bank.py` and `disposition.py` are written to. A row
that cannot be read is dropped and counted, never guessed at. A letter that has
not been delivered yet is left alone rather than asked for. A take is never
planned for a letter this process cannot see an id for, because the executor's
answer to that is `no mail with that id` and a queue full of those is
indistinguishable from a broken mailbox.

NOT CALLED `mailbox.py`, WHICH IS THE OBVIOUS NAME AND IS A TRAP. `mailbox` is
a Python STANDARD LIBRARY module (the mbox/Maildir reader), and this package is
imported with its own directory first on `sys.path` - both in the image, where
everything is copied flat into /app, and under `unittest discover`. A file with
that name here would silently shadow the stdlib for this process and for
anything it imports, and the symptom would arrive somewhere else entirely. The
trip is what this module plans, so it is named for the trip.

PURE MODULE: no MySQL, no core, no auction house, no browser. Every number here
is arithmetic over rows somebody else fetched.
"""
from __future__ import annotations

from dataclasses import dataclass

# The two verbs this module emits, spelled exactly as `ParseMailRequest` reads
# them (overseer_decisions.cpp). The other three in the grammar are argued
# about below: `send` in the docstring above, `return` and `delete` here.
#
# `return` AND `delete` ARE NOT EMITTED, AND THAT IS A SAFETY DECISION RATHER
# THAN A GAP. Deleting a letter DESTROYS what is on it - `Player::_SaveMail`
# issues CHAR_DEL_ITEM_INSTANCE for every attachment of a mail left in
# MAIL_STATE_DELETED - and the executor guards that with two refusals of its
# own (`mail still carries an attachment`, `mail still carries money`) because
# the core does not. A pass that tidied the mailbox would be one bug away from
# destroying the very reagents this pass exists to rescue, and nothing is
# gained: an uncollected letter expires on its own after thirty days.
TAKE_ITEM = "take-item"
TAKE_MONEY = "take-money"

# How many takes one visit to a mailbox is allowed to queue per character.
#
# A judgement, not a game constant, which is why it is named - and it is
# `bank.VISIT_LIMIT`'s number for `bank.VISIT_LIMIT`'s reason, restated because
# a reader should not have to open that file to check it. The family reaches a
# mailbox by one leader walking there and the rest following, and a pass that
# queued forty rows against that one arrival would spend the whole retry window
# on a journey that may not have finished. Eight is roughly what a person clears
# out in one stop, and the next cycle takes the rest.
#
# NOT IMPORTED FROM `bank.py`. The two numbers are equal today and are answers
# to two different questions - how much a character shifts across a bank counter
# in one stop, and how much they pull out of a mailbox - so tying them together
# would make a later change to either one a change to both.
VISIT_LIMIT = 8


@dataclass(frozen=True)
class Letter:
    """One letter in one character's mailbox, as the caller measured it.

    `attachments` is a tuple of `item_instance.guid`, one per thing hanging off
    the letter, because `take-item` addresses exactly one attachment by guid
    (`take-item mail:<id> item:<guid>`). It is NOT a count: the executor refuses
    `mail does not carry that item` for a guid that is not on the letter, and a
    count would give this module no way to name which one it means.

    `delivered` is the caller's answer to `deliver_time <= now`, computed where
    the clock is rather than here, because a pure module has no clock and a
    process clock that disagreed with the worldserver's would be a second
    opinion on a question the core already answers by refusing.

    `cod` IS CARRIED EVEN THOUGH THE FAMILY NEVER SENDS ONE. Counted live on
    2026-09-13, every one of the realm's 556 letters had `cod = 0` - but the
    auction house and other players can both post one, `take-item` refuses a
    COD letter by name and permanently, and a field that is only ever zero on
    the day it was written is exactly the field that is not zero on the day it
    matters.
    """
    holder: str
    mail_id: int
    money: int
    cod: int
    delivered: bool
    expire_time: int
    attachments: tuple = ()


@dataclass(frozen=True)
class Take:
    """One mail command, with the reason it is worth sending written into it."""
    character: str
    verb: str        # TAKE_ITEM or TAKE_MONEY
    mail_id: int
    item_guid: int   # 0 for TAKE_MONEY
    why: str


@dataclass(frozen=True)
class Plan:
    """The ordered takes, and everything the pass refused to do and why.

    `notes` is not decoration, for the reason `bank.Plan` gives for its own: a
    mail pass that plans nothing looks identical whether the mailboxes are
    empty, the rows would not parse, the letters have not been delivered yet or
    the bags are full - and those four want four different responses from a
    person reading the log.
    """
    takes: tuple = ()
    notes: tuple = ()


def _int(value, default=0):
    """Read a number a database driver may hand over as almost anything."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def letters_from_rows(rows, names):
    """One Letter per (character, mail id) the caller could see, sorted.

    `rows` carry holder, mail_id, money, cod, delivered, expire_time and
    item_guid, as the bridge's SQL names them, ONE ROW PER ATTACHMENT - a
    LEFT JOIN onto `mail_items`, so a letter carrying nothing arrives as a
    single row whose item_guid is NULL and a letter carrying three arrives as
    three rows. Folding them back together is this function's whole job, and it
    is done here rather than in SQL so it can be tested against rows written by
    hand.

    A NAME WITH NO ROWS GETS NO LETTERS, which needs no special case: an empty
    mailbox and an unreadable one are genuinely the same thing to a pass that
    can only ever ask for what it can see. What tells them apart is the bridge's
    own error handling, which logs, and `Plan.notes`, which explains.

    SORTED BY WHAT EXPIRES FIRST. Mail keeps for thirty days and then the letter
    and everything on it are gone, so when the visit limit bites, the letter
    closest to that deadline is the one worth spending the trip on. `mail_id`
    breaks the tie rather than leaving the order to the database, because a plan
    that reordered itself between cycles would make the retry window useless and
    the log unreadable - `bank._stack_order` makes the same argument about two
    identical stacks of cloth.
    """
    wanted = list(dict.fromkeys(names))
    seen = set(wanted)
    letters: dict = {}
    attachments: dict = {}
    for row in rows:
        holder = row.get("holder")
        if holder not in seen:
            continue
        mail_id = _int(row.get("mail_id"))
        if mail_id <= 0:
            # The executor reads a zero mail id as malformed and refuses it
            # without reaching the world. A row this process cannot name a
            # letter from is a row it must not ask about.
            continue
        key = (holder, mail_id)
        if key not in letters:
            letters[key] = Letter(
                holder=holder,
                mail_id=mail_id,
                money=max(0, _int(row.get("money"))),
                cod=max(0, _int(row.get("cod"))),
                delivered=bool(row.get("delivered")),
                expire_time=_int(row.get("expire_time")),
            )
            attachments[key] = []
        guid = _int(row.get("item_guid"))
        if guid > 0 and guid not in attachments[key]:
            attachments[key].append(guid)

    built = [
        Letter(
            holder=letter.holder, mail_id=letter.mail_id, money=letter.money,
            cod=letter.cod, delivered=letter.delivered,
            expire_time=letter.expire_time,
            attachments=tuple(sorted(attachments[key])),
        )
        for key, letter in letters.items()
    ]
    return tuple(sorted(
        built, key=lambda one: (one.holder, one.expire_time, one.mail_id)))


def room_for(name: str, free_slots: dict, already_asked: dict) -> int:
    """How many attachments this character may be asked for this pass.

    THE BAG READING IS A CEILING ON A MODE THIS PASS IS ALREADY IN, never the
    thing that starts it, which is the discipline `craft_rhythm.py` is the
    worked example of. Collecting the post is unconditional - it is the
    character's own property and the postage is paid - and bag room only ever
    ENDS a collection early. So a reading that is wrong costs lateness, and the
    letter keeps for thirty days.

    AND THE MAIL HALF OF THAT READING IS NOT STALE AT ALL, which was checked
    rather than assumed. `character_inventory` is normally written on
    `PlayerSaveInterval` (900s on this realm), but `WorldSession::
    HandleMailTakeItem` does not wait for it: at the pinned AC_CORE_SHA
    47960183 it commits `player->SaveInventoryAndGoldToDB(trans)` and
    `player->_SaveMail(trans)` in its own transaction (MailHandler.cpp:621-623),
    and `HandleMailTakeMoney` commits `SaveGoldToDB` and `_SaveMail` the same
    way (:669-672). So a collection this pass made is visible to the next pass
    immediately, in BOTH tables: the bag reading falls as the mailbox empties,
    and a collected attachment vanishes from `mail_items` rather than being
    proposed again.

    WHAT IS STILL STALE IS EVERYTHING ELSE THE BAGS DO. A loot, a craft or a
    trade five minutes ago is not in `character_inventory` yet, so `free_slots`
    can read HIGH by whatever those put in the bags. That error has exactly one
    direction and it is the survivable one - the pass asks for one attachment
    too many and the executor answers `no room in the bags`, a retryable refusal
    that changes nothing - but an unbounded version of it would re-ask every
    cycle for ever. `already_asked` is what bounds it: every attachment this
    pass has already asked for inside the retry window is spent budget, so the
    room a character has only ever falls within a window, whatever the bag rows
    say.

    A NAME THE CALLER COULD NOT MEASURE GETS ZERO, not a default: a character
    whose room is unknown gets no takes rather than takes that will be refused.
    """
    free = max(0, _int(free_slots.get(name)))
    spent = max(0, _int(already_asked.get(name)))
    return max(0, free - spent)


# The note both budget exhaustions produce, and it is one string because it is
# one fact: this arrival has been asked to do as much as one arrival is allowed
# to. Written once rather than twice so the two places that can reach it cannot
# drift into two slightly different sentences describing the same stop.
_VISIT_NOTE = ("%s has more in the mailbox than one visit carries; the rest "
               "waits for the next trip")


def _attachment_takes(holder, letter, room, budget):
    """The takes for one letter's attachments, and what they spent.

    Returns `(takes, room, budget, note)` - the room and the budget AFTER this
    letter, so the caller's arithmetic stays in one direction and there is no
    second place that could forget to subtract. `note` is the empty string when
    nothing stopped it.

    LIFTED OUT OF `plan` RATHER THAN INLINED FOR ITS OWN SAKE. `plan` was one
    function holding a loop over characters, a loop over letters and a loop over
    attachments, with four early exits threaded through all three - which is a
    shape a reader has to hold entirely in their head to be sure the money still
    gets collected when the bags are full. The split is along the seam the
    ordering rule already draws: what costs a bag slot, and what does not.
    """
    takes, note = [], ""
    for guid in letter.attachments:
        if budget <= 0:
            note = _VISIT_NOTE % holder
            break
        if room <= 0:
            note = ("%s has no room in the bags for what letter %d is "
                    "carrying, so it stays in the mailbox" % (
                        holder, letter.mail_id))
            break
        room -= 1
        budget -= 1
        takes.append(Take(
            character=holder, verb=TAKE_ITEM, mail_id=letter.mail_id,
            item_guid=guid,
            why="letter %d is holding an attachment the bags have room for"
                % letter.mail_id))
    return takes, room, budget, note


def _one_mailbox(holder, mine, room, visit_limit):
    """One character's takes, money first, and every reason something was left.

    Returns `(money_takes, item_takes, notes)` as three lists rather than one
    ordered list, because the ORDER IS THE CALLER'S RULE and keeping the two
    kinds apart until it applies them is what makes that rule impossible to get
    wrong here by accident.

    RUNNING OUT OF BAG ROOM DOES NOT END THE CHARACTER'S TURN, which is easy to
    lose in a rewrite and is the whole reason the money is collected separately.
    A letter whose attachment cannot be carried still has its coins taken, and so
    does every letter after it - room only ever stops `take-item`.
    """
    money_takes, item_takes, notes = [], [], []
    budget = visit_limit
    for letter in mine:
        if budget <= 0:
            notes.append(_VISIT_NOTE % holder)
            break
        if not letter.delivered:
            # `mail has not been delivered yet` is what the executor says to a
            # letter still in transit, and it is retryable. An hour is the
            # realm's configured delay for a cross-account item, which is every
            # letter the family sends itself, so this is an ordinary state
            # rather than a fault.
            notes.append(
                "%s's letter %d has not been delivered yet, so it is left "
                "where it is" % (holder, letter.mail_id))
            continue
        if letter.money > 0:
            money_takes.append(Take(
                character=holder, verb=TAKE_MONEY, mail_id=letter.mail_id,
                item_guid=0,
                why="letter %d is carrying %d copper" % (
                    letter.mail_id, letter.money)))
            budget -= 1
        if not letter.attachments:
            continue
        if letter.cod:
            # `mail is cash on delivery` is a PERMANENT refusal of `take-item`:
            # the core would charge the COD out of this character's purse and
            # the executor declines to spend it. A row for one is a row that can
            # only ever fail. The money above is NOT withheld, because
            # `take-money` carries no such check and inventing one here would be
            # a rule the world does not have.
            notes.append(
                "%s's letter %d is cash on delivery, so its %d "
                "attachment(s) are not this pass's to take" % (
                    holder, letter.mail_id, len(letter.attachments)))
            continue
        taken, room, budget, note = _attachment_takes(
            holder, letter, room, budget)
        item_takes.extend(taken)
        if note:
            notes.append(note)
    return money_takes, item_takes, notes


def plan(letters, free_slots, already_asked=None, *, visit_limit=VISIT_LIMIT):
    """Every take worth asking for, in the order it should be sent.

    MONEY BEFORE ITEMS, PER CHARACTER, and the ordering is not arbitrary: a
    `take-money` costs no bag slot at all, so putting it first means a character
    with one free slot and a letter carrying both still gets the coins. Running
    it the other way round would make a full bag swallow the money as well as
    the goods, on exactly the characters whose bags are full because nobody has
    collected their post.

    THE VISIT LIMIT COUNTS BOTH VERBS. It is a budget on how much one arrival at
    one mailbox is asked to do, and a queue of thirty `take-money` rows outlives
    a journey exactly as well as a queue of thirty `take-item` rows does.

    `already_asked` IS ATTACHMENTS, NOT ROWS, and it is optional so a caller
    that has not been taught to count them yet gets the bag reading raw - the
    cautious direction is the other one, and wiring the count in later can only
    ever narrow the budget, never widen it. See `room_for` for why it exists.

    THE PER-CHARACTER WORK IS `_one_mailbox`'s; this is the loop and the
    ordering. A character whose letters nobody could read contributes nothing
    and no note, which is the honest answer rather than a manufactured one.
    """
    spent = dict(already_asked or {})
    takes, notes = [], []
    for holder in sorted({letter.holder for letter in letters}):
        money_takes, item_takes, mine_notes = _one_mailbox(
            holder,
            [letter for letter in letters if letter.holder == holder],
            room_for(holder, free_slots, spent),
            visit_limit,
        )
        takes.extend(money_takes)
        takes.extend(item_takes)
        notes.extend(mine_notes)
    return Plan(takes=tuple(takes), notes=tuple(dict.fromkeys(notes)))


def command(take):
    """The exact command text mod-overseer's DoMail takes for one take.

    `mail:` and `item:` and nothing else, in the order `ParseMailRequest` reads
    them - though the parser accepts the keys in any order, this writes one
    order so that the retry window's `(character, command)` key is stable
    between cycles. Both ids must be non-zero: the parser refuses a zero of
    either by name, because the core reads a zero item guid as an invalid
    attachment and a mail id that matches nothing as an internal error, and
    answers both only with a packet a bot never sees.
    """
    if take.verb == TAKE_MONEY:
        return "%s mail:%d" % (TAKE_MONEY, take.mail_id)
    return "%s mail:%d item:%d" % (TAKE_ITEM, take.mail_id, take.item_guid)


def attachments_asked(commands) -> dict:
    """character -> how many attachments were already asked for, from the window.

    Takes the `(character, command)` pairs the bridge reads back out of
    `overseer_command` and counts only the `take-item` ones, because only those
    spend a bag slot. Counting the money takes as well would shrink the budget
    for a reason that does not exist, and a budget that is wrong in the
    cautious direction still stops the pass collecting post somebody is waiting
    for.

    A PURE FUNCTION OVER TEXT, deliberately, so the one piece of arithmetic that
    decides how much staleness this pass tolerates is testable without a
    database - the same reason `bank.members_from_rows` counts free slots in
    Python rather than in SQL.
    """
    counts: dict = {}
    for name, text in commands:
        if not str(text).startswith(TAKE_ITEM + " "):
            continue
        counts[name] = counts.get(name, 0) + 1
    return counts


def lines(takes):
    """One log line per take, for a person reading the pass afterwards.

    Takes the takes rather than the Plan so the caller can log what it actually
    WROTE, the argument `bank.lines` makes: a pass that logs its plan and writes
    half of it, because the other half was already queued inside the retry
    window, is a log that lies about what the family did.
    """
    return ["%s: %s (%s) - %s"
            % (take.character, take.verb, command(take), take.why)
            for take in takes]
