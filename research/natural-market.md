# Natural market: what bots loot, gather and craft, and whether they can trade on the auction house

Research for [#516](https://github.com/quadseven/wow-overseer/issues/516), workstream D of the
[Ragnaros wayfinder map](https://github.com/quadseven/wow-overseer/issues/512). Measured
read-only on the wow-dev realm on 2026-10-04 (UTC), against the code pinned below.

Sources:

- Upstream mod-playerbots `master` at `037c014` (2026-10-02), and our fork at the
  vendored pin `60e6555` (`UPSTREAM-PINS.env`).
- The playerbots core fork `azerothcore-wotlk` at `4796018` (`AC_CORE_SHA`).
- mod-overseer at `ec7645a`; this repo at `b1b7626`.
- mod-junk-to-gold at `2134690`.
- Live `acore_characters` and the worldserver's own config files, read with SELECTs only.

## Short answer

1. Natural supply is real but unrecorded. About 490 random bots are online, and 352
   of them are factory level 60s. A 29-minute window of new item rows puts their
   looted and gathered supply at a floor of about 2,000 trade-good units an hour:
   - mostly Runecloth, meat and leather
   - about 80 herbs and 50 ore
   - about 220 loose BoE greens and 65 recipes
   - nothing crafted

   Factory refills (ammo, oils, soul shards, Outland consumables) arrive mixed in
   with it. The realm records none of this as loot. `item_loot` covers only rare and
   better drops for the 10 story characters, about 2,000 rows in 12 days.
2. Playerbots cannot post or buy auctions natively. Upstream's only auction-posting
   code, `StoreLootAction::AuctionItem`, is commented out in upstream and in our fork.
   No action buys from the house. An item the bot rates `ITEM_USAGE_AH` is sold to a
   vendor or destroyed. The auctioneer appears only as an RPG travel target.
   Our own path works: mod-overseer's `DoAuction` has delivered 119 buys and 8 listings.
3. The realm keeps no complete sale history. It has to be recorded from now on. The core fires
   `OnAuctionSuccessful` and `OnAuctionExpire` script hooks on every sale and expiry.
   A mod-overseer `AuctionHouseScript` writing one row per outcome is the only
   complete source. Mail keeps 30 days of our own characters' outcomes. `log_money` and the log files keep nothing usable.

## 1. What enters the world

### Who is playing

| Group | Characters | Online | Notes |
|---|---|---|---|
| Random bots (`RNDBOT%` accounts) | 1,621 | 490 | 352 online at level 60, 121 at level 10-19 |
| Our accounts (both families plus others) | 12 | 10 | Levels 26 to 41 |

Online random bots average 1,393 gold each. `MinRandomBots = MaxRandomBots = 500`,
`RandomBotMaxLevel = 60`.

### Random-bot bags are factory stock, not loot

The table shows unequipped item rows held by random bots, by item class and quality,
for groups over 20 rows.

| Class | Quality | Rows | Units |
|---|---|---|---|
| 0 Consumable | 1 common | 7,330 | 86,290 |
| 7 Trade goods | 1 common | 4,552 | 26,406 |
| 15 Misc | 1 common | 2,137 | 30,239 |
| 2 Weapon | 1 common | 1,448 | 1,448 |
| 12 Quest | 1 common | 1,260 | 3,323 |
| 0 Consumable | 2 uncommon | 776 | 15,333 |
| 6 Projectile | 3 rare (flag) | 773 | 763,177 |
| 4 Armor | 2 uncommon | 612 | 612 |
| 3 Gem | 2 uncommon | 408 | 1,031 |

Equipped random-bot gear is 13,406 rare armor pieces and 1,417 rare weapons, which is
`RandomItemMgr` gear-init, not drops. Professions are granted at the cap. Every row
below is a random bot holding the skill, at its average value:

| Skill | Bots | Avg |
|---|---|---|
| 129 First Aid | 1,054 | 294 |
| 185 Cooking / 356 Fishing | 988 | 300 |
| 171 Alchemy | 583 | 300 |
| 393 Skinning | 293 | 294 |
| 333 Enchanting | 248 | 300 |
| 186 Mining | 240 | 282 |
| 182 Herbalism | 179 | 282 |
| 202 Engineering | 163 | 299 |

The guild rule bars this stock from a natural market. A random bot's bag cannot be
the supply, because nothing in it was found. A natural engine has to count items at
the moment they are created by loot, gathering or crafting, and list only those.

### What the realm records about loot, gathering and crafting

- `overseer_event kind='item_loot'`: 2,020 rows from 2026-09-22 to now. mod-overseer
  writes them from `OnPlayerLootItem` and `OnPlayerGroupRollRewardItem`, but only
  when `IsNotableItemQuality` and `ShouldRecordItemLoot` pass (story characters,
  notable quality). In the last 7 days every row was quality 3 or 4 (rare or epic),
  mostly armor (287) and weapons (160), from dungeon bosses. Common trade goods,
  cloth, herbs and ore never appear.
- `overseer_event kind='craft'`: 16 rows, 101 crafts, all on 2026-10-04: Rough
  Sharpening Stone, Rough Blasting Powder, Minor Healing Potion, Bolt of Linen
  Cloth, Light Leather.
- `overseer_event kind='fish'`: 6 rows, 101 catches, on 2026-09-28.
- There is no gathering event. Herbs, ore and skins are invisible.
- mod-junk-to-gold destroys every grey on loot in `OnPlayerLootItem` and pays the
  vendor price. Greys never reach a bag, and so never reach a market.
- The playerbots debug log (`Playerbots.log`) traces actions for the debug-enabled
  bots only. In its first ten minutes after a restart: `store loot` OK 80 times,
  `add gathering loot` FAILED 2,699 of 2,699 tries. It is not a population measure.

### Flow

Method: note `MAX(item_instance.guid)` (8,904,143 at 19:12:17 UTC), then 29.3
minutes later (19:41:34, 498 characters online) count every persisted item row with a
higher guid by owner, location, class and quality. The core allocated 5,630 item guids
in the window, about 11,500 per hour. That is the ceiling on item creation of every
kind. Most of them never persist, because an item sold, destroyed or used before the
owner's next save leaves no row. The persisted counts are therefore a floor.

| Owner | New rows | Per hour |
|---|---|---|
| Random bots, in bags | 2,156 | about 4,400 |
| AH bot seller, new listings | 105 | about 215 |
| Our 10 characters, in bags | 32 | about 65 |

The random-bot rows mix two sources:

- Factory refills, not found:
  - ammunition: Doomshot and Miniature Cannon Balls, 79,801 units in 80 rows
  - Adamantite weightstones and sharpening stones, exactly 40 bots each
  - Soul Shards and Major Soulstones
  - conjured and vendor water, wizard and mana oils
  - Skinning Knives, Runed Arcanite Rods
  - Outland consumables a Classic-era bot cannot have found, such as Star's
    Lament and Filtered Draenic Water
- Loot and gathering. In trade goods alone, leaving out the Runed Arcanite Rod, the
  window held 485 stacks of 988 units:

| Kind | Units in window | Examples |
|---|---|---|
| Cloth | about 366 | Runecloth 359 (82 stacks, 81 bots), Mageweave 7 |
| Meat and cooking | about 300 | Mystery Meat, White Spider Meat, Bear Flank, wolf meats, Giant Egg |
| Leather, hide, scale | about 130 | Rugged Leather 57, Thick Leather 18, Heavy Scorpid Scale 17, dragonscales 8 |
| Reagent drops | about 110 | Thick Spider's Silk, Ichor of Undeath, Shadow Silk, Ironweb Spider Silk, venom sacs |
| Herbs | about 40 | Plaguebloom 9, Dreamfoil 7, Black Lotus 5, Silverleaf 4, Mountain Silversage 3 |
| Ore, stone, bars | about 24 | Solid Stone 11, Thorium Ore 6, Dense Stone 4, Truesilver Bar 2 |
| Elementals and essences | about 15 | Elemental Air/Earth/Fire, Essence of Earth/Undeath, Living Essence |

Loose equipment and recipes in random-bot bags in the window: 100 green armor, 4
green and 2 blue weapons, 2 blue armor, 29 green and 3 blue recipes, and 28 green gems.
Factory gear goes straight to equipment slots, so loose BoE greens are most likely
drops.

Our characters' 32 rows were dungeon greens and blues, Linen and Wool Cloth, Lion Meat, Mountain Lion Blood, Moss Agate and
Lesser Moonstone, and two recipes.

### What a natural market would hold per hour

Scaling the window to an hour, at about 490 online random bots, almost all level 60,
and 10 story characters, gives this floor:

| Natural supply | Per hour (floor) |
|---|---|
| Cloth (Runecloth dominant) | about 750 units |
| Meat and cooking drops | about 600 units |
| Leather, hide, scale | about 270 units |
| Reagent drops (silk, ichor, venom) | about 220 units |
| Herbs | about 80 units |
| Ore, stone, bars | about 50 units |
| Elementals and essences | about 30 units |
| Loose BoE greens and blues (armor, weapons) | about 220 items |
| Recipes | about 65 |
| Green gems | about 55 |
| From our 10 characters | about 65 rows, mostly dungeon greens |

The AH bot creates about 215 listings an hour across three houses, at a steady 749
per house. Natural trade-good supply is in the same order of magnitude, but the mix
differs: almost all level-60 cloth and meat, little ore and few herbs, and nothing
crafted. Random bots have maxed gathering skills (179 herbalists, 240 miners, 293
skinners), yet gathering yields stay small. Every `add gathering loot` the debug log
traced failed, and that path looks weak.

Caveats:

- The window is one half hour on one evening.
- The floor misses everything a bot vendors or destroys before its save. `SellAction`
  vendors anything rated `ITEM_USAGE_AH` once bags pass 80 percent.
- The level mix decides the item mix. A population leveling from 1 would supply Linen
  and Copper instead of Runecloth and Thorium.
- Random bots own maxed professions, but no crafted item appeared in the window. A
  natural market would hold no crafted goods unless the engine crafts them.

## 2. Can playerbots post or buy auctions natively?

No, in either direction.

- Posting. `StoreLootAction::AuctionItem` and `RoundPrice` sit inside a `/* ... */`
  block in `src/Ai/Base/Actions/LootAction.cpp` (upstream lines 303-397; our fork
  256-350). Nothing calls them. Even uncommented, the code minted a fresh item with
  `Item::CreateItem` at `BuyPrice` times a multiplier. It was an AH-bot shim, not a
  bot selling its own loot.
- Item usage. `ItemUsageValue` returns `ITEM_USAGE_AH` for any non-soulbound,
  non-BoP item of common quality or better with a sell price
  (`ItemUsageValue.cpp:152-158`). Then:
  - `SellAction`'s `SellVendorItemsVisitor` sells `ITEM_USAGE_AH` to a vendor exactly
    like `ITEM_USAGE_VENDOR`.
  - `CanSellValue` counts both.
  - `DestroyItemAction` puts `ITEM_USAGE_AH` on the destroy list when bags are full.
  - `LootRollAction` greeds on it.
- Buying. `BuyAction` only buys from an NPC vendor in range.
- The auctioneer. `UNIT_NPC_FLAG_AUCTIONEER` appears in `PossibleRpgTargetsValue`,
  `ChooseTravelTargetAction` and `TravelMgr` as a place to walk to.
  `TravelMgr::SelectAuctioneerByMap` is declared and never defined. No action opens
  an auction window.

So a market engine has to issue every list and buy itself, through mod-overseer.

### Our path through mod-overseer

`DoAuction` (`mod_overseer.cpp`) handles `kind='auction'` with four verbs:

- `list guid:<item> bid:<c> buyout:<c> hours:<12|24|48>`
- `buy auction:<id>`
- `bid auction:<id> bid:<c>`
- `cancel auction:<id>`

It sends the real `CMSG_AUCTION_*` packets from within 5.5 yards of an auctioneer.
The house comes from the auctioneer's faction. `AllowTwoSide.Interaction.Auction = 0`,
so the three houses (2 Alliance, 6 Horde, 7 neutral) are disjoint.

[#478](https://github.com/quadseven/wow-overseer/issues/478) says auction rows never
execute. That is stale. All `kind='auction'` rows to date:

| Verb | Status | Detail | Rows | First | Last |
|---|---|---|---|---|---|
| buy | delivered | | 119 | 2026-09-14 | 2026-10-04 |
| buy | error | auction not found | 24 | 2026-09-14 | 2026-10-04 |
| buy | error | auctioneer not in range | 13 | 2026-09-13 | 2026-10-04 |
| list | error | auctioneer not in range | 9 | 2026-09-26 | 2026-10-02 |
| list | delivered | | 8 | 2026-09-29 | 2026-10-04 |
| other | error | not online / in combat | 3 | | |

The 8 listings were Malachite, Tigerseye and two BoE recipes, buyouts 193 to 4,146
copper. None of the 8 item guids exists any more. Two of them provably sold to the AH
bot's buyer (`AuctionHouseBot.Buyer.Enabled = true`). Bork still holds the sale mails:
Tigerseye x3 for 1,458 copper (cut 72) and Malachite for 193 (cut 9). Each mail body
names the counterparty as `244`, which is GUID 580 in hex. The other six left no record.
`auction.plan_buys` and `auction.plan_sales` are the live callers, from `bridge.py`
and `raidsupply.py`. `plan_sales` refuses an item with no `market_price`, and
`bridge.py` sets that to the cheapest live per-unit listing. With the AH bot gone,
that price is zero for almost every entry, and the sale pass goes quiet.

### The house today is entirely the AH bot

All 2,247 live listings belong to one character, the AH bot seller (GUID 580,
`AuctionHouseBot.GUIDs = 580`), at exactly 749 per house. Not one listing has a bid.
The heaviest groups are:

- white trade goods: 454 listings, average 3,299 copper per unit
- green gems: 329
- green trade goods: 238
- blue trade goods: 141

Removing the module (charting decision 6 on
[#511](https://github.com/quadseven/wow-overseer/issues/511)) leaves the house empty.
It also removes the only buyer. Nothing on the realm would buy a bot's listing except
another `buy` row from our engine.

## 3. Where price history can come from

The realm keeps none today.

| Source | What it holds | Usable? |
|---|---|---|
| `auctionhouse` | Live listings only. `AuctionEntry::DeleteFromDB` removes the row on sale or expiry. | Asking prices now. No outcomes. |
| `mail` | Auction mails (`messageType` 2). Subject `entry:0:response:auctionId:count`, where response 1 means won and 2 means sold. Body `counterparty:bid:buyout:deposit:cut`. 20 rows live, all to our characters. A mail lives 30 days and is gone sooner if the character deletes it. Random bots never trade, so they hold none. | Partial: our characters, 30 days |
| `log_money` | `SendAuctionSuccessfulMail` inserts a row only when `auction->bid >= 500 * GOLD` (`AuctionHouseMgr.cpp:225-237`). 37 rows, none from auctions. | No |
| Log files | `entities.player.auctionhouse` writes created, bid, bought out, sold, won, expired and cancelled lines at INFO. `Logger.root=2` (errors only), with no logger for that channel. Appenders open in `w` mode, so each restart truncates the file. | Not as configured |
| `overseer_command.result` | Our own `DoAuction` JSON: auction id, house, buyout, item, count, money before and after. | Our trades only |
| Script hooks | `AuctionHouseScript::OnAuctionAdd`, `OnAuctionRemove`, `OnAuctionSuccessful`, `OnAuctionExpire`. `OnAuctionSuccessful` fires on buyout (`AuctionHouseHandler.cpp:569`) and on a bid won at expiry (`AuctionHouseMgr.cpp:551`). `OnAuctionExpire` fires at `:541`. | Yes: complete |

The recommended source is a mod-overseer `AuctionHouseScript` that writes one
`overseer_auction_outcome` row per hook call: entry, count, house, buyout, final bid,
seller, buyer, listed and closed times. Every sale and expiry passes through those
two hooks, including trades the engine did not issue. That gives a per-item
sold-versus-expired series to price from.

Until enough rows exist, the vendor price is a floor and the engine's own unsold
expiries are the only signal. `disposition.py` measured the AH bot's prices at 46x to
3,881x vendor for trade goods. They are a constant-floor artifact
(`PriceMinimumCenterBase.TradeGood = 850`), not observed demand, so they should not
seed the series.

For supply, the same approach applies. Widen the existing `OnPlayerLootItem`,
`OnPlayerGroupRollRewardItem` and `OnPlayerStoreNewItem` path to count every looted
or crafted stack by entry and source kind (creature, game object, item), aggregated
per hour. That covers all characters, not just notable items on story characters.
`OnPlayerCreateItem` covers crafting. A game-object loot GUID separates gathering from
corpse loot. Only items counted this way should be listable under the
natural-progression rule.

## Open points for the engine design

- Demand. With the AH bot's buyer gone, the only buyers are rows the engine itself
  issues. Who buys, and with whose gold, is a design question this research does not
  answer.
- House segregation. Supply listed at a Horde auctioneer is invisible to the Alliance
  family, and the reverse.
- Random-bot gear and stock. The factory bags and maxed professions are themselves
  unearned. Whether random bots may sell anything at all depends on how far the
  natural-progression rule extends to them, and that is a decision for
  [#512](https://github.com/quadseven/wow-overseer/issues/512).
