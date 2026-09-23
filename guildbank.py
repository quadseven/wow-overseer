"""Who has more gold than they need, and how much of it goes to the guild.

DEPOSIT ONLY (mod-overseer#437, infra#2831). Withdrawals need the guild's own
per-rank permission read (`guild_bank_right`) done on THIS side before an aim
is even written, so the module never asks the core to do something the
guild's own rank rules would refuse - that is a separate, harder feature and
is not attempted here. Deposit has no such rank gate: the core's own
`Guild::HandleMemberDepositMoney` performs no rank check at all, only a
bank-full ceiling, so any member may deposit and the only question this
module has to answer is how much of their own purse is actually spare.

THE RULE IS DELIBERATELY SIMPLE FOR A FIRST SLICE: leave every character a
fixed float, deposit whatever sits above it. No per-character judgement about
upcoming trainer costs, repair bills or auction listings - those are exactly
the kind of "surplus" question `disposition.py` answers for items, and a gold
version of that same judgement is future work, not this slice.

ITEM DEPOSIT (mod-overseer, infra#3647): MECHANISM HERE, POLICY IN bank.py.

UPDATE (#233): the policy the next paragraphs say was left for a follow-up
now exists. bank.py's keeper rule decides which carried stacks are stored,
sends the tradable ones here through `format_item_deposit`, and
`_guild_bank_once` queues them from the vault. The guild on the dev realm
has since bought tab 0 and its family ranks carry the deposit-item right,
so the blockers below are the ones `bank.storage_from` checks before it
offers the guild anything.

`format_item_deposit` below produces the exact `bank deposit-item
guid:<n>`/`entry:<n>` command text `GuildVerb::BankDepositItem` parses
(overseer_decisions.cpp) and `DoGuild` executes against the real,
verified-at-the-pinned-SHA `Guild::SwapItemsWithInventory` API
(mod_overseer.cpp). It is deliberately NOT wired into an automatic pass the
way `plan_deposits`/`_guild_bank_once` are for gold: deciding WHICH items a
character should give up - crafted potions above some held count, spare
ore, whatever the profession-supply-chain work landing this session
actually produces - needs real measured inventory data this session had no
way to read (no live pymysql connection, same constraint `guildbank.py`'s
own money-deposit design doc already ran into for the API itself). Inventing
a threshold with no data to check it against is exactly the failure mode
this project's own history warns about, so that policy is left for a
follow-up once real holdings can be read, not guessed here. This function
exists so that follow-up (or an operator, by hand) has a correct command to
enqueue through the same `_insert_guild` path `_guild_bank_once` already
uses for gold - it does not decide anything on its own.

WHY AN ITEM DEPOSIT STILL CANNOT LAND, AND WHAT THAT COSTS THIS MODULE
(infra#3713). An item deposit needs a purchased bank tab to land in;
`Guild::SwapItemsWithInventory` silently no-ops while `tabId >=
_GetPurchasedTabsSize()`. No guild on this realm has ever bought one (counted
live 2026-09-13: 21 guilds, 0 rows in `guild_bank_tab`, 0 in
`guild_bank_item`), so `format_item_deposit`'s perfectly correct command text
has nowhere to go yet.

THE ORDERING INFRA#3713 ASSUMED IS NOT THE REAL ONE, AND GETTING IT
BACKWARDS WOULD STRAND THE GUILD. #3713 reasoned that a tab is paid for out
of `guild.BankMoney`, which is 0, so gold had to be deposited first to fund
it. That is not what the pinned core does. `Guild::HandleBuyBankTab`
(Guild.cpp:1442 at AC_CORE_SHA 47960183) checks
`player->HasEnoughMoney(tabCost)` and then
`player->ModifyMoney(-int32(tabCost))`: the tab comes out of the BUYING
CHARACTER'S OWN PURSE and the guild's funds are never read or debited. So
depositing gold does not fund a tab - it is the one thing that can make the
tab UNBUYABLE, by moving the purchase price somewhere the purchase cannot
reach. That is why `TAB0_COST_COPPER` is held back below while the guild has
no tab, and it is why the reserve lives in this module rather than the pass.
"""

from __future__ import annotations

from dataclasses import dataclass

# The working float, in copper: what a character keeps for themselves no
# matter how much the guild would like it.
#
# TEN GOLD, AND THE NUMBER IS BORROWED RATHER THAN INVENTED. Two other
# modules in this package have already had to draw the same line, and both
# measured it against this family:
#
#   - `needs.py:102` `THIN_COPPER = 10 * wealth.COPPER_PER_GOLD`, whose own
#     comment says the floor "is what a character needs to get out of trouble
#     on their own: a full repair, and a bag to put the next thing in".
#   - `digest.py:116` `BROKE_COPPER = 1 * COPPER_PER_GOLD`, "under this and a
#     character cannot pay a trainer, which is how a character stops gaining
#     spells without anything looking wrong".
#
# This constant was ONE GOLD until infra#3713, which is exactly `digest.py`'s
# broke line - so the rule deposited every character down onto the precise
# threshold another module in this same package exists to report as a
# problem, and one repair bill or trainer visit then put them under it. Ten
# gold is `needs.py`'s floor, the one of the two chosen to mean "can still
# get out of trouble unaided", and that is the property a float wants.
#
# NOT IMPORTED FROM `needs.py` ON PURPOSE, though it must not drift from it:
# `needs` imports `wealth`, which imports `bonds`, `family`, `armory` and
# `panel`, and this module is deliberately dependency-free so the pass can
# import it without dragging the view layer in. `tests/test_guildbank.py`
# pins the two numbers equal instead, so a later change to either side fails
# a test rather than silently parting company.
FLOAT_COPPER = 100_000

# What the guild's FIRST bank tab costs, in copper. One hundred gold.
#
# READ FROM THE REALM, NOT FROM A WIKI AND NOT FROM MEMORY. The price is not a
# constant in the core at all - `_GetGuildBankTabPrice` (Guild.cpp:94 at the
# pinned AC_CORE_SHA 47960183) returns
# `sWorld->getIntConfig(CONFIG_GUILD_BANK_TAB_COST_0)`, a CONFIG value, so the
# only honest source is the config the realm is actually running. Confirmed on
# 2026-09-13 by reading `Guild.BankTabCost0 = 1000000` out of the deployed
# worldserver.conf inside the running wow-dev worldserver pod. It agrees with
# the core's own `worldserver.conf.dist` default at the pinned SHA, and nothing
# in this repo overrides it. `Guild.BankInitialTabs = 0` there too, so no guild
# is given a free tab at creation, which is why the realm has none.
#
# WHY A PYTHON MODULE HOLDS A COPY OF A SERVER CONFIG VALUE. It is duplicated
# here for the same reason `overseer_decisions.h` duplicates the core's money
# ceiling: this module cannot read worldserver.conf, and the number's only job
# here is to decide how much NOT to deposit. Being wrong high is safe (the
# family keeps more than it needed); being wrong low is the exact failure this
# constant exists to prevent. If the realm's config ever changes, the symptom
# is a tab that cannot be afforded, not a corrupted deposit.
TAB0_COST_COPPER = 1_000_000


@dataclass(frozen=True)
class Deposit:
    name: str
    copper: int


@dataclass(frozen=True)
class SetupAction:
    """One guild-bank setup command for the already surveyed leader."""

    target: str
    command: str


def plan_setup(
    *,
    leader: str,
    purchased_tabs: int,
    rank_ids: tuple[int, ...] = (),
    deposit_rank_ids: tuple[int, ...] = (),
    purse: int | None = None,
) -> tuple[SetupAction, ...]:
    """Plan the one-time tab and deposit-rights setup, without doing I/O.

    Tab 0 is bought by the guild master from that character's purse. Once it
    exists, the same master opens tab 0 to every non-master rank that lacks the
    deposit right. The returned commands are idempotent when the caller reads
    the persisted state before planning, and malformed state fails closed.

    `purse` is the buyer's `characters.money` when the caller read it. A buyer
    holding less than `TAB0_COST_COPPER` is not asked (#246): the core
    refuses the purchase, and the row would cost a walk to the vault for
    nothing. None keeps the old answer, so a caller that has not read the
    purse still asks.
    """
    if not isinstance(leader, str) or not leader.strip():
        return ()
    if not isinstance(purchased_tabs, int) or purchased_tabs < 0:
        return ()
    if purchased_tabs == 0:
        if purse is not None and not can_buy_tab(purse):
            return ()
        return (SetupAction(leader, "bank buy-tab"),)
    try:
        ranks = sorted({int(r) for r in rank_ids if int(r) > 0})
        granted = {int(r) for r in deposit_rank_ids if int(r) > 0}
    except (TypeError, ValueError):
        return ()
    return tuple(
        SetupAction(leader, f"bank grant-deposit rank:{rid}")
        for rid in ranks
        if rid not in granted
    )


def can_buy_tab(purse) -> bool:
    """Whether a purse, in copper, pays for tab 0; unreadable reads as no."""
    try:
        return int(purse) >= TAB0_COST_COPPER
    except (TypeError, ValueError):
        return False


def tab_waits_line(buyer: str, purse) -> str:
    """The pass's sentence for a tab its buyer cannot pay for yet (#246)."""
    try:
        held = max(0, int(purse or 0))
    except (TypeError, ValueError):
        held = 0
    return (
        "guild bank setup: tab 0 waits - %s holds %dg of the %dg it costs, "
        "and the guild's dues are what fill that purse"
        % (buyer or "nobody", held // 10_000, TAB0_COST_COPPER // 10_000)
    )


def plan_deposits(members: list[dict], *, guild_has_tab: bool = False) -> list[Deposit]:
    """One Deposit per character holding more than the reserve, or none.

    `members` is a list of {"name": str, "money": int, "in_guild": bool}. A
    character not in a guild is skipped rather than raising - the guild-bank
    errand is meaningless for them and the caller should not have to filter
    first. `money` missing or non-positive is treated as nothing to deposit,
    not an error: a stale or absent read should never manufacture a deposit
    order, only ever suppress one.

    `guild_has_tab` says whether the guild has already bought its first bank
    tab. It DEFAULTS TO FALSE, the cautious answer, on purpose: a caller that
    has not been taught to read `guild_bank_tab` yet gets the reserve that
    keeps the tab affordable rather than the one that spends it, so wiring
    that read in later can only ever release gold, never strand it. While it
    is False every member holds back `TAB0_COST_COPPER` on top of the float,
    so whichever character is eventually asked to buy the tab can still pay
    for it out of their own purse - see this module's docstring for why the
    purchase cannot be paid for out of the guild's funds.

    HOLDING THE PRICE BACK FROM EVERY MEMBER, NOT JUST THE LIKELY BUYER, IS
    DELIBERATE. Nothing on the Python side can name the buyer yet: no verb for
    buying a tab exists in the pinned `GuildVerb` at all (infra#3713's
    finding, filed against mod-overseer), so there is no character this module
    could point at and no way to check afterwards that it was that one who
    paid. Reserving from everybody costs the guild some pooled gold for as
    long as it has no tab and guarantees the price is present in SOMEBODY's
    purse; reserving from a guessed buyer would be cheaper and could be wrong,
    and being wrong here is unrecoverable without an operator moving gold by
    hand.

    `money` is read from `characters.money`, which LAGS for ordinary play: at
    the pinned core, only the guild-bank withdraw and mail-money handlers call
    `SaveGoldToDB` immediately. Quest rewards, vendor sales, loot, and trainer
    costs are written by `Player::SaveToDB` on `PlayerSaveInterval` (900s), so
    a reading can remain stale until that periodic save. That is the other
    reason the reserve is generous rather than exact: a purse that
    reads high because of a stale trainer visit must still clear the tab price.
    """
    reserve = FLOAT_COPPER if guild_has_tab else FLOAT_COPPER + TAB0_COST_COPPER
    deposits: list[Deposit] = []
    for member in members:
        if not member.get("in_guild"):
            continue
        name = member.get("name")
        if not name:
            continue
        money = member.get("money") or 0
        if not isinstance(money, int) or money <= reserve:
            continue
        deposits.append(Deposit(name=name, copper=money - reserve))
    return deposits


def format_item_deposit(
    *, item_guid: int | None = None, entry: int | None = None
) -> str:
    """The `bank deposit-item guid:<n>` / `entry:<n>` command text
    `GuildVerb::BankDepositItem` parses (overseer_decisions.cpp) and `DoGuild`
    executes against `Guild::SwapItemsWithInventory` (mod_overseer.cpp).

    Exactly one of `item_guid` (the specific `item_instance.guid` to move) or
    `entry` (an item type - whichever matching item the character happens to
    be carrying) must be given, the same guid-preferred/entry-fallback
    convention DoGive's own item spec already uses. This is a pure command
    formatter, not a decision: it does not choose which item to deposit, only
    renders the request once something else - an operator, or a future
    policy module reading real holdings - has already chosen. See this
    module's own top-of-file docstring for why no such policy is written
    here yet.

    IT STILL CANNOT LAND TODAY, AND NOT FOR A REASON THIS FUNCTION CAN FIX:
    the guild has no purchased tab, and beyond that a freshly bought tab
    grants deposit rights to the GUILD MASTER ALONE. Both blockers, and the
    order they have to be cleared in, are spelled out by
    `tab_deposit_blockers` below and recorded in infra#3713.
    """
    if (item_guid is None) == (entry is None):
        raise ValueError("give exactly one of item_guid or entry")
    if item_guid is not None:
        if not isinstance(item_guid, int) or item_guid <= 0:
            raise ValueError("item_guid must be a positive integer")
        return f"bank deposit-item guid:{item_guid}"
    if not isinstance(entry, int) or entry <= 0:
        raise ValueError("entry must be a positive integer")
    return f"bank deposit-item entry:{entry}"


def tab_deposit_blockers(*, purchased_tabs: int, ranks_with_deposit: int) -> list[str]:
    """Why an item deposit would not land, in the order it has to be fixed.

    Returns one human-readable line per blocker, and an empty list when there
    is none. `purchased_tabs` is the guild's `guild_bank_tab` row count;
    `ranks_with_deposit` is how many of its ranks actually carry
    `GUILD_BANK_RIGHT_DEPOSIT_ITEM` on tab 0, counted from `guild_bank_right`.

    THIS EXISTS BECAUSE BOTH FAILURES ARE SILENT. The core refuses an item
    deposit by doing nothing at all: `Guild::SwapItemsWithInventory` no-ops
    while `tabId >= _GetPurchasedTabsSize()`, and `BankMoveItemData::
    HasStoreRights` (Guild.cpp:835) refuses a member whose rank lacks the
    right, also by doing nothing. An operator watching the family stand at a
    vault and post correct commands cannot tell those two apart, or tell
    either of them from a walk that never arrived. Naming them is the point.

    THE SECOND BLOCKER IS THE SURPRISING ONE, AND IT OUTLIVES THE PURCHASE.
    Buying a tab does NOT open it to the guild. `Guild::_CreateNewBankTab`
    calls `RankInfo::CreateMissingTabsIfNeeded`, which sets
    `GUILD_BANK_RIGHT_FULL` only `if (m_rankId == GR_GUILDMASTER)`; every
    other rank gets a default-constructed `GuildBankRightsAndSlots`, which is
    `rights(0), slots(0)` (Guild.h:267). On this realm guild 23 "Cave" is one
    Guild Master and four Officers, so the moment the tab is bought exactly
    ONE of the five characters can put anything into it and the other four
    fail silently - the precise opposite of the pooling the tab was bought
    for. Clearing it needs `Guild::HandleSetRankInfo`, which has no verb
    either.
    """
    blockers: list[str] = []
    if purchased_tabs <= 0:
        blockers.append(
            "the guild has no purchased bank tab, so an item deposit has "
            f"nowhere to land (tab 0 costs {TAB0_COST_COPPER // 10_000} gold, "
            "paid from the buying character's own purse)"
        )
    if ranks_with_deposit <= 0:
        blockers.append(
            "no guild rank carries GUILD_BANK_RIGHT_DEPOSIT_ITEM on tab 0, so "
            "every member's item deposit is refused silently"
        )
    elif ranks_with_deposit == 1:
        blockers.append(
            "only one guild rank carries GUILD_BANK_RIGHT_DEPOSIT_ITEM on "
            "tab 0 - a freshly bought tab opens to the Guild Master alone, so "
            "every other rank still fails silently"
        )
    return blockers
