# Item plan: what each member keeps, banks, gives, sells or breaks down

Status: design, an unwired prototype (`itemplan.py`) and a measured simulation. Nothing here changes the bridge, the realm or any pass. Last checked 2026-11-07. Ticket: #1967.

## The question

For every stack a guild member carries or banks, in priority order:

1. Never lose a needed thing.
2. Make the working set fit the bags, the personal bank and the guild bank.
3. Route surplus where it creates value.
4. Stay stable and explainable.
5. Stay safe: nothing irreversible without a row the executor can refuse.

## Why the bags are full today

Six passes each own a slice and refuse the rest, so no pass owns the leftover. The sale pass (`bag_pressure.sellable`) refuses any reagent, any stack a family trade uses, anything above common quality and anything with no vendor price. `jev_keep` asks Jev about protected stacks one at a time, in shadow. `bankpolicy`, `clearance`, `disposition` and `guildshare` each route a class of stack. Measured on 2026-11-07, the two level 54 Zug members carry 67 and 60 items, hold 61 and 76 items in the bank (the bank is 28 slots plus bank bags) and share a guild bank tab that is 98 of 98 full. The sale pass saw 2 and 10 candidates.

## The algorithm in plain language

Every stack gets a short list of destinations, best first, from the first rule that claims it. A second step walks the list and takes the first destination that has room. Rooms are allocated in priority order, so the scarce rooms (bag slots, bank slots, guild tab slots) go to the stacks that need them most.

Priority is a goal tier, then vendor copper per slot. Lowest priority leaves a full bag first. The tiers, high to low: quest, equipment, attunement, family upgrade, trade tools, trade skill-up now, raid night, run consumables, trade skill-up next range, gear for later, bag room, recipe, surplus, no use.

### The ordered rules

| Rule | What it decides | Why this order | Extends or replaces |
| --- | --- | --- | --- |
| R1 | A row with an unreadable binding is kept. | Unknown fails closed. | `disposition` |
| R2 | Worn bags, keys and the hearthstone stay. A spare bag larger than a worn bag stays for `bag_upgrade`. A spare bag fits an empty bank bag position first (more bank room), then goes to a sibling with an empty position, then to the vendor. | Bags are room; the cheapest room is a bag already owned. | `bag_upgrade` |
| R3 | Quest items. An open quest names the item: keep. A quest log that was not read keeps every quest-class stack and never sells or destroys one. | Losing a quest item costs the run. | `bag_pressure.QUEST_NEEDED_SQL` |
| R4 | Gear the gear pass says to wear stays. Soulbound or any gear the holder can wear in its level window and the gear pass has not judged: a second set in the personal bank, capped at 6 pieces (`SPARE_SET_MAX`), best first. | Never lose the holder's own upgrade; a set is not a hoard. | `bankpolicy` rule 2, `gear` |
| R5 | A trade tool stays with a member who works the trade, else goes to the sibling who does. | A tool has no level to outgrow. | `disposition.TOOL_TRADES` |
| R6 | Molten Core supplies, their reagents and fire resistance gear: carried on the raid night, held by the member who crafts them, else the Raid Supplies tab, else banked. Never sold. | Raid readiness. | `bankpolicy` rule 3, `raidsupply` |
| R7 | Trade stock and food. Reagents that recipes still giving skill points use at the current range are kept in the bags; the next range's stock is banked; whole stacks, up to the need. The sibling who works the trade gets the others' surplus. | Skill-ups are the family's progress. | `disposition.profession_keeps`, `material_keeps` |
| R8 | Gear by binding. Soulbound gear belongs to its holder only. Bind-on-equip gear goes to the sibling who wears it now (give), or to the Gear for Later tab for a later level. Gear nobody will wear: disenchant if an enchanter at that skill exists, rare gear to the Gear for Later tab, else vendor. Epic gear is never sold. | Binding decides which routes exist. | `bankpolicy` rule 4, `disposition.decide` |
| R9 | Recipes. Kept for a member whose trade reaches it, given to the sibling whose trade reaches it, raid recipes never sold, else the guild tab, else bank if worth it, else vendor. | A recipe is rare; the vendor price is the floor. | `clearance` |
| R10 | Surplus materials: the sibling who works the trade, a guildmate who does, the Materials tab, bank when a stack is worth `BANK_WORTH` per slot (gems always), else vendor. | Materials feed crafters before a vendor. | `clearance`, `guildshare.FEEDS` |
| R11 | Anything else with a price: auction when the price beats the vendor by 4x, else vendor. | Vendor price is the floor. | `disposition.AUCTION_BEATS_VENDOR_BY` |
| R12 | No price and no use: bank while at least 6 bank slots stay free, else destroy. | Destroy is last. | `jev_keep` destroy shadow |

### Skill ranges, from the recipe tables

The current range runs from the member's skill to the top of its 75-point range. The next range is the following 75. A recipe whose grey value is under the member's skill gives no skill-up and asks for nothing. A recipe in the current range stocks 12 casts (`craft_rhythm.STOCK_CASTS`); one in the next range stocks 3. One recipe is cast at a time, so a trade's need for a material is its largest recipe's need; trades add. Inputs come from `craft.RECIPES` (the ladders with their grey edges), `craft_rhythm.GATHERED`, `craft_supply.REAGENTS` and the bolt chain (`craft_rhythm.BOLT_FED`). A unit cap of 120 per material per member (`disposition.MATERIAL_KEEP`) bounds any need.

For a trade the tables do not cover (enchanting, jewelcrafting), a documented band rule applies: a material that `guildshare.FEEDS` to a trade the member works is kept when its tier (item level) is within the current and next range, up to 40 units.

### Capacity and hysteresis

Each member protects 8 free carried slots (the town-first guard and dungeon admission) plus a margin of 2. Eviction starts when free carried slots fall under 10 and stops at 12. The gap is the hysteresis: a stack evicted at 9 free is not pulled back at 10. Evictions walk the stack's own destination list (bank, guild tab, vendor), so a needed reagent goes to the bank before it goes anywhere else.

The plan also keeps last pass's routes (`Context.previous`). A stack planned for a bank is not pulled back by a discretionary goal. A planned sale changes only when a real need appears. An auction listing needs 4x the vendor price to start and holds down to 3x. Nothing depends on random order: stacks sort by (tier, value, key).

### Guild bank tabs

A tab holds 98 slots. The realm sells tabs at 100, 250, 500, 1000, 2500 and 5000 gold (`guildbank.TAB_COSTS_COPPER`). Both guilds own tab 0 and it is full. The second tab costs 250 gold, 2.55 gold per slot. The plan does not buy anything. A tab pays for itself only when the stacks it holds are worth more to guild crafters than their vendor price by about 2.55 gold per stack on average. In the simulation, the 687 stacks that wanted a tab and found none have a combined vendor value of 133 gold, so the vendor price alone does not repay a 250 gold tab; use needs to (see "Needs a person").

### Safety

DESTROY needs vendor price 0, no market price, quality 2 or less and a stack no rule claimed. Every SELL_VENDOR, DISENCHANT and DESTROY row carries `irreversible` and `refusable`; the executor may skip it and the next pass asks again. A sale of quality 3 or better, or worth 1 gold or more, also carries `confirm`: shadow shows it and a release (a person, or a later rollout step) unlocks it. A quality 4 stack is never sold or destroyed.

## Data it needs, and where the bridge gets it

| Input | Source | In the dump? |
| --- | --- | --- |
| Item rows (entry, class, subclass, quality, count, vendor price, binding, required and item level) | `item_template` and `item_instance`, as `bag_pressure` reads them | yes |
| Member level, class, skills (value, max) | `characters`, `character_skills` | yes |
| Worn bags and bank bag positions bought | character inventory, `characters.bankSlots` | partly: no bag slot, no `ContainerSlots` |
| Guild bank tab contents | `guild_bank_item` | yes |
| Quest log (open quests naming an item) | `QUEST_NEEDED_SQL` | no |
| Equipped gear, inventory type, stats | character inventory, `item_template` | no |
| Fire resistance per item | `item_template.fire_res` | no |
| Auction prices | the auction pass's quotes (`bag_market`, `auction`) | no |
| Recipe required skill rank | `item_template.RequiredSkillRank` | no |
| Soulbound flag of a bind-on-equip piece | `item_instance.flags` | no |
| Guild roster by trade and online state | `guildshare`, `guildcorps` | no |

Where a field is absent the plan fails closed, and the follow-up ticket for the missing data lists each one.

## Simulation

`tools/itemplan_simulate.py` runs the plan over every member of both families from the 2026-11-07 TSV dump (1,299 rows). The dump itself holds character names and stays out of the repository.

Assumptions the run states: the quest log is unread, so every quest-class stack is kept (13 stacks for each of the two members below); no market price exists, so nothing is auctioned and the vendor price is the floor; no guild roster exists, so no guildmate takes a gift; equipped gear is absent, so the gear pass's verdict is "unjudged"; bag sizes come from `bag_slots` (issue-confirmed sizes for the Runecloth Bag, Huge Brown Sack and Large Knapsack, an item-level band for the rest). Bank capacity for the Zug pair is 88 and 78 slots under that model, and 61 and 76 are in use now.

| Member (level 54) | Carried slots | Free now | Free after the plan | Free after, vendor out of reach | Carried stacks to bank | to vendor | to destroy | to disenchant | to give | Vendor gold, carried stacks | Vendor gold, whole plan | 8-slot bar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Oz (mage, tailor) | 72 | 5 | 53 | 14 | 8 | 35 | 2 | 2 | 1 | 4.24 | 6.81 | reached |
| Zork (druid) | 64 | 4 | 47 | 14 | 10 | 30 | 3 | 0 | 0 | 10.34 | 25.23 | reached |

All ten members reach the bar, from 4 to 12 free now to 44 to 58 free after (14 to 26 with no vendor). The plan also sells stacks sitting in the bank (27 stacks of Oz's, 43 of Zork's), which is where the rest of the whole-plan gold comes from.

### Sensitivity

If the bank bags are not usable room (bank held to its 28 base slots), Oz reaches 52 free (10 with no vendor) and Zork 47 (9 with no vendor), with one of Oz's stacks stuck. Both still clear 8, narrowly, without a vendor. So the answer does not depend on the bag size table to reach the bar, but the margin does. The slots that stay carried hold 13 quest stacks, 3 food or drink stacks, the hearthstone and, for Oz, 2 tailoring stacks.

### What else they need

- The plan alone reaches 8 with no gold or items granted. Without a vendor the margin is thin (9 to 14), so the vendor reach tickets (#1592, #1813) still matter: the vendor is what takes 47 to 53 free instead of 9 to 14.
- Reading the quest log would free up to 13 more slots each: most of those 13 stacks are leftovers (an Everlook report, a riding pamphlet held three times), but the plan cannot tell without the log.
- A second guild tab (250 gold) is not needed to reach 8. It holds surplus materials and later-level gear that the plan otherwise vendors. The family's gold is 121 (Oz) and 251 (Zork), so a tab costs more than either holds; it needs the guild's money (the guild bank has no withdraw route here, see `guildbank.py`) or a pooled deposit.
- Disenchanting needs an enchanter. The only one is Oz, at enchanting 1, who can break down item level 25 and under, so 2 stacks. Raising the skill is the lever, not a bank.

## What is not decided and needs a person

- Whether to buy a second guild bank tab (250 gold) and who pays.
- Whether `confirm` sales release by hand or after a quiet shadow period.
- The gear pass's own judgement of unjudged soulbound pieces (the plan banks six per member).
- Selling recipes for pennies when no crafter is in reach (the plan banks any worth 50 silver or more).
- Guild bank cleanup: the full tabs hold 85 recipes and patterns; selling or giving them is a guild decision.

## Rollout, matching how `jev_keep` went from shadow to action

1. Shadow. Run the plan beside the current passes each economy tick, log the plan and its disagreements with each pass, change nothing.
2. Act on one route at a time, reversible first: personal bank, then give to a sibling, then guild bank deposits, then sell, then disenchant, then auction. Each route has its own switch and its own threshold, and acts only where the current protection would keep the stack.
3. Destroy last, and only the rows the shadow log shows no other route could take.
4. Retire the pass a route replaces once the route has run clean for a week.

Each executor route has its own ticket, and each ticket refers to #1967.

## Scope notes

`itemplan.py` imports this repository's tables and nothing else. No module imports it yet, so `tests/test_bridge_image_modules.py` lists it in `KNOWN_UNREACHED`; the shadow ticket (#1972) removes it from that list when it wires the module in. The `Dockerfile` copies it because every top-level module is copied. It is not `item_plan.py`, the sale-retry memo: the names are close and the jobs are not.
