"""The guild funds its members' training, and gives the dues back once.

THE OPERATOR'S DECISION (2026-10-10): "Members keep gold for training first,
guild funds the rest", and "give some gold back to people who went broke with
dues". Measured on the dev realm that day at about 12:50 ET: 65 of Cave's 71
members and 63 of Bonkers' held under a gold, 1,569 class spells waited at
their trainers, Cave's guild bank held 155 gold and Bonkers' held none.

WHAT A GUILD OFFICER DOES. The guild master walks to a guild vault, takes gold
out through the game's own guild bank withdraw (`bank withdraw <copper>`, the
module's kind='guild' verb, which the core judges by the master's rank), and
posts it from a mailbox to each member that needs it, through the game's own
mail. Every copper that moves was earned and banked by the guild; nothing is
granted. Two kinds of letter:

  Dues refund         once per member, ever: the guild dues a member posted
                      (the command log's delivered `guilddues:` letters),
                      given back up to what it is short of its reserve, while
                      the bank holds it. The refunded members are the
                      `guildfund:refund:<member>` letters in the command log,
                      so a restart repeats nobody.
  For your training   a member whose purse does not cover the class spells
                      its trainer would sell it now gets the difference, up to
                      MEMBER_DAILY_COPPER a day, the way a guild rank's daily
                      withdraw limit bounds what one member may take. The
                      guild spends at most DAILY_SHARE of its bank a day on it.

WHY THE MASTER AND NOT EACH MEMBER AT THE VAULT. The guild's ranks below
Officer carry no withdraw right and every rank but the master's a daily limit
of 0 (guild_rank on the dev realm, 2026-10-10: rights 67, BankMoneyPerDay 0),
and a member off the roster has no walk to a vault. The master's withdraw
needs neither, and a letter reaches a member wherever it is; the guild post
pass walks it to a mailbox to take the gold out (guildpost.py).

THE RESERVE (`reserve`) is the cost of the class spells trainable now plus a
gear budget (`gear_budget`). The guild dues leave it in a member's purse
(guildwork.dues_for), and a refund fills a member up to it.

PURE MODULE: rows in, a plan and sentences out. No MySQL and no clock.
"""

from __future__ import annotations

from dataclasses import dataclass

LOG_PREFIX = "guild fund:"
SOURCE = "guildfund"
WITHDRAW_SOURCE = SOURCE + ":withdraw"
REFUND = "refund"
TRAIN = "train"
SUBJECTS = {REFUND: "Dues refund", TRAIN: "For your training"}
# The dues letters' source in the command log (guildwork.SOURCE).
DUES_SOURCE = "guilddues"

COPPER_PER_GOLD = 10_000
# What one member may be given for training in a day: ten gold, the size of a
# guild rank's daily money limit for a member. Every class spell a level 30
# character waits on costs under a gold, so this covers a member's whole list.
MEMBER_DAILY_COPPER = 10 * COPPER_PER_GOLD
# The share of the bank the guild spends on training in a day.
DAILY_SHARE = (1, 2)
# Below this a letter is not worth its 30 copper of postage.
MIN_LETTER_COPPER = 50 * 100
# A withdrawal under a gold waits for more letters.
MIN_WITHDRAW_COPPER = COPPER_PER_GOLD
# Letters the master posts in one pass.
LETTERS_PER_PASS = 12
# THE GEAR BUDGET: level cubed in copper, mod-playerbots' own measure of what a
# bot keeps for gear (NeedMoneyFor::gear): 10 silver at level 10, a gold and a
# half at 25, 21 gold at 60.
GEAR_LEVEL_CAP = 60


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def gold(copper) -> str:
    copper = _int(copper)
    g, rest = divmod(copper, COPPER_PER_GOLD)
    s = rest // 100
    if g:
        return "%dg %02ds" % (g, s) if s else "%dg" % g
    return "%ds" % s if s else "%dc" % copper


def gear_budget(level) -> int:
    level = min(max(_int(level), 0), GEAR_LEVEL_CAP)
    return level * level * level


def reserve(training_copper, level) -> int:
    """Copper a member keeps: its waiting class spells and a gear budget."""
    return max(0, _int(training_copper)) + gear_budget(level)


@dataclass(frozen=True)
class Member:
    """One guild member, as the bridge read it."""

    name: str
    guild: str
    level: int
    money: int
    training: int = 0  # copper of the class spells trainable now

    @property
    def reserve(self) -> int:
        return reserve(self.training, self.level)


@dataclass(frozen=True)
class Letter:
    """One letter of the guild's gold from the master to one member."""

    master: str
    member: str
    copper: int
    kind: str
    dues_paid: int = 0
    money: int = 0
    reserve: int = 0

    @property
    def command(self) -> str:
        return "send money:%d subject:%s" % (int(self.copper), SUBJECTS[self.kind])

    @property
    def source(self) -> str:
        return "%s:%s:%s" % (SOURCE, self.kind, self.member)

    @property
    def said(self) -> str:
        if self.kind == REFUND:
            return (
                "%s Dues refund: %s posts %s to %s (dues paid %s; it holds %s "
                "against a %s reserve)"
                % (
                    LOG_PREFIX,
                    self.master,
                    gold(self.copper),
                    self.member,
                    gold(self.dues_paid),
                    gold(self.money),
                    gold(self.reserve),
                )
            )
        return (
            "%s For your training: %s posts %s to %s (it holds %s; its "
            "trainer's spells cost %s)"
            % (
                LOG_PREFIX,
                self.master,
                gold(self.copper),
                self.member,
                gold(self.money),
                gold(self.reserve),
            )
        )


@dataclass(frozen=True)
class Ledger:
    """What the command log says the fund has done, for one master."""

    withdrawn: int = 0  # applied `bank withdraw` rows, all time
    posted: int = 0  # fund letters not refused, all time
    refunded: frozenset = frozenset()  # members with a refund letter
    given_today: dict = None  # member -> copper of training letters, 24 hours
    spent_today: int = 0  # all training letters, 24 hours

    @property
    def carried(self) -> int:
        """The fund's gold the master has withdrawn and not posted yet."""
        return max(0, self.withdrawn - self.posted)


def _letter_copper(command) -> int:
    words = str(command or "").split()
    if len(words) >= 2 and words[0] == "send" and words[1].startswith("money:"):
        return _int(words[1].split(":", 1)[1])
    return 0


def _withdrawn(row) -> int:
    """Copper an applied `bank withdraw` row of the fund took out; else 0."""
    words = str(row.get("command") or "").split()
    if str(row.get("status")) != "applied" or len(words) != 3:
        return 0
    return _int(words[2]) if words[:2] == ["bank", "withdraw"] else 0


def _letter_kind(row) -> tuple:
    """(kind, member) of a fund letter the world did not refuse; else None."""
    parts = str(row.get("source") or "").split(":", 2)
    if len(parts) != 3 or parts[0] != SOURCE or str(row.get("status")) == "error":
        return None
    return parts[1], parts[2]


def ledger(rows, master) -> Ledger:
    """The fund's ledger for this master over the command log's rows.

    `rows` carry target_name, target_arg, command, source, status and age
    (minutes). A withdrawal counts once applied; a letter counts unless the
    world refused it ('error').
    """
    withdrawn = posted = spent = 0
    refunded, given = set(), {}
    mine = [r for r in rows or () if str(r.get("target_name") or "") == master]
    for row in mine:
        if str(row.get("source") or "") == WITHDRAW_SOURCE:
            withdrawn += _withdrawn(row)
            continue
        letter = _letter_kind(row)
        if letter is None:
            continue
        kind, member = letter
        copper = _letter_copper(row.get("command"))
        posted += copper
        if kind == REFUND:
            refunded.add(member)
        elif kind == TRAIN and _int(row.get("age"), 99999) < 24 * 60:
            given[member] = given.get(member, 0) + copper
            spent += copper
    return Ledger(withdrawn, posted, frozenset(refunded), given, spent)


def dues_paid(rows, renames=None) -> dict:
    """member -> copper of guild dues it posted, under the name it has now.

    `rows` are the command log's dues letters (target_name, source, status);
    only a delivered letter counts. `renames` maps a name a letter was posted
    under to the character's name now (the approved lineup renamed most of the
    guild after the dues were taken).
    """
    renames = renames or {}
    out = {}
    for row in rows or ():
        source = str(row.get("source") or "")
        if (
            not source.startswith(DUES_SOURCE + ":")
            or str(row.get("status")) != "delivered"
        ):
            continue
        copper = _int(source.rsplit(":", 1)[1])
        name = str(row.get("target_name") or "")
        name = renames.get(name, name)
        if name and copper > 0:
            out[name] = out.get(name, 0) + copper
    return out


@dataclass(frozen=True)
class Plan:
    """One guild's fund this pass: the letters, and what to withdraw for them."""

    letters: tuple = ()
    withdraw: int = 0
    notes: tuple = ()

    @property
    def total(self) -> int:
        return sum(x.copper for x in self.letters)


def daily_budget(bank) -> int:
    num, den = DAILY_SHARE
    return max(0, _int(bank)) * num // den


def _refunds(master, pool, book, paid, purse) -> tuple:
    """(letters, notes, purse left): once each, up to the dues paid and what
    the member is short of its reserve, while the purse holds it."""
    letters, notes = [], []
    for m in sorted(pool, key=lambda m: (m.money - m.reserve, m.name)):
        dues = _int(paid.get(m.name))
        if dues <= 0 or m.name in book.refunded:
            continue
        copper = min(dues, m.reserve - m.money, purse)
        if m.reserve <= m.money:
            notes.append(
                "%s paid %s of dues and holds its %s reserve; no refund"
                % (m.name, gold(dues), gold(m.reserve))
            )
        elif copper < MIN_LETTER_COPPER:
            notes.append(
                "%s waits for a refund: the bank holds %s" % (m.name, gold(purse))
            )
        else:
            purse -= copper
            letters.append(
                Letter(master, m.name, copper, REFUND, dues, m.money, m.reserve)
            )
    return letters, notes, purse


def _training(master, pool, book, skip, budget) -> tuple:
    """(letters, notes): the difference to the trainer's price, a day's limit
    a member, the budget in all."""
    letters, notes = [], []
    given = dict(book.given_today or {})
    for m in sorted(pool, key=lambda m: (m.training - m.money, -m.level, m.name)):
        short = m.training - m.money
        if m.name in skip or short <= 0:
            continue
        room = MEMBER_DAILY_COPPER - given.get(m.name, 0)
        copper = min(short, room, budget)
        if room < MIN_LETTER_COPPER:
            notes.append(
                "%s has had today's %s for training"
                % (m.name, gold(MEMBER_DAILY_COPPER))
            )
        elif copper >= MIN_LETTER_COPPER:
            budget -= copper
            letters.append(
                Letter(master, m.name, copper, TRAIN, 0, m.money, m.training)
            )
    return letters, notes


def plan(master, members, bank, book, paid, roster=frozenset()) -> Plan:
    """The refunds first, then the training letters, inside the bank.

    `members` are Member rows of the master's guild; `bank` the guild bank's
    money; `book` the master's Ledger; `paid` dues_paid's map. `roster` names
    the family, whose own passes fund it. The master's carried fund gold
    counts as money the bank already gave. The training letters share, a
    day, DAILY_SHARE of what the refunds left.
    """
    roster = {str(n) for n in roster or ()}
    pool = [m for m in members or () if m.name != master and m.name not in roster]
    refunds, notes, purse = _refunds(
        master, pool, book, paid, max(0, _int(bank)) + book.carried
    )
    budget = min(purse, daily_budget(purse) - book.spent_today)
    training, more = _training(master, pool, book, {x.member for x in refunds}, budget)
    letters = refunds + training
    total = sum(x.copper for x in letters)
    withdraw = min(max(0, total - book.carried), max(0, _int(bank)))
    if withdraw < MIN_WITHDRAW_COPPER:
        withdraw = 0
    return Plan(tuple(letters), withdraw, tuple(notes + more))


def postable(plan_, carried, limit=LETTERS_PER_PASS) -> tuple:
    """The letters the master can post now from the fund gold it carries,
    refunds first, in the plan's order."""
    out, left = [], max(0, _int(carried))
    for letter in plan_.letters:
        if len(out) >= limit:
            break
        if letter.copper <= left:
            out.append(letter)
            left -= letter.copper
    return tuple(out)


def pass_line(guild, bank, carried, plan_, refunded) -> str:
    """The fund pass's one line for the log."""
    kinds = [x.kind for x in plan_.letters]
    return (
        "%s %s: the bank holds %s, the master carries %s of it; %d refund(s) and "
        "%d training letter(s) planned for %s, %s to withdraw; %d member(s) "
        "refunded so far"
        % (
            LOG_PREFIX,
            guild or "?",
            gold(bank),
            gold(carried),
            kinds.count(REFUND),
            kinds.count(TRAIN),
            gold(plan_.total),
            gold(plan_.withdraw),
            len(refunded),
        )
    )


def members_from_rows(rows, guild, dues) -> list:
    """Member rows out of the bridge's guild rows and classtrain.due's map
    (name -> a Due, whose `copper` is the training due)."""
    out = []
    for r in rows or ():
        name = str(r.get("name") or "")
        if name:
            due = (dues or {}).get(name)
            out.append(
                Member(
                    name,
                    guild,
                    _int(r.get("level")),
                    _int(r.get("money")),
                    _int(getattr(due, "copper", 0)),
                )
            )
    return out


def withdraw_open(rows) -> bool:
    """Whether a fund withdrawal is still waiting for the world's answer."""
    return any(
        str(r.get("source")) == WITHDRAW_SOURCE
        and str(r.get("status")) in ("pending", "claimed", "verifying")
        for r in rows or ()
    )


def withdraw_command(copper) -> str:
    """The master's guild bank withdrawal, the module's kind='guild' verb."""
    return "bank withdraw %d" % int(copper)


def hold_back(rows, carried_by_master) -> list:
    """The guild bank pass's money rows with the fund's carried gold taken out
    of each master's purse, so it is not deposited back before it is posted."""
    out = []
    for row in rows or ():
        row = dict(row)
        held = _int((carried_by_master or {}).get(str(row.get("name") or "")))
        if held:
            row["money"] = max(0, _int(row.get("money")) - held)
        out.append(row)
    return out
