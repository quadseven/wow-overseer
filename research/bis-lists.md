# Level-60 best-in-slot lists per class and spec, and where each item comes from

Research for [#537](https://github.com/quadseven/wow-overseer/issues/537), workstreams E, F and G of
the Ragnaros wayfinder [#512](https://github.com/quadseven/wow-overseer/issues/512).
Snapshot taken 2026-10-04. Server facts were read from the wow-dev world DB (`acore_world`), read-only.

## Answer

- All 18 raid specs have a Wowhead Classic pre-raid list and a Molten Core list, ranked per slot
  with alternatives. That makes 36 lists with 770 distinct item ids, stored under
  [`research/bis/`](bis/) as ids, slots and rank order only.
- Every one of the 770 ids exists in this server's `item_template`. 758 can be obtained by a
  level 60. The 12 that cannot are Onyxia's classic loot and quest rewards (Onyxia is level 83
  here), the quest legendaries and Sulfuras (no source row), and two oddities (a conjured
  Spellstone and a quest-only wand).
- Every pre-raid best pick for every spec can be obtained on this server. On the Molten Core
  lists, 249 of 272 best picks can be. The gaps are mostly the Onyxia items above.
- Pre-raid gear comes mostly from dungeons, then quests, crafting, world drops, chests and honor
  vendors. Molten Core best picks come 43% from Molten Core itself and 28% from dungeons.
- This server sells ilvl 71-78 honor gear for honor alone. The guides rank
  none of the ilvl 74 sets or ilvl 78 weapons, because on retail Classic those needed a high PvP rank.
  The per-class honor sets are listed in `situational.json` so the scorer can weigh them.
- For stat weights, use wowsims/classic (MIT). Sixty Upgrades' terms forbid reusing its data or
  preset weights. Wowhead's stat guides supply the priority order and caps, plus numeric weights
  for feral only.
- Storage: one JSON file per spec, `data/bis/<class>-<spec>.json`, plus `items.json`,
  `situational.json` and `weights-wowsims.json`. Refresh the guide lists by a manual,
  rate-limited snapshot once per content change. Regenerate the server sources from the DB on
  every world DB update.

## 1. Sources

Guide lists come from Wowhead Classic. The current guides are the Season of Mastery and Classic
Era revisions of the 2019 guides. They were fetched once each on 2026-10-04: 36 guide pages,
17 stat pages, 1 fire resistance page and 9 class hubs, with a 2 second gap between requests.
Each guide's ranked tables carry one row per item (`[item=ID]`) under a slot heading. Only the
id, the slot and the row order were kept, and the rank label only as a "best" flag. No guide
text was copied. The `source_url` in each list is the attribution.

| Spec file | Pre-raid guide | Molten Core guide | Stat guide |
| --- | --- | --- | --- |
| warrior-fury | [link](https://www.wowhead.com/classic/guide/fury-warrior-dps-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-fury-warrior-dps-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/warrior/fury/dps-stat-priority-attributes-pve) |
| warrior-protection | [link](https://www.wowhead.com/classic/guide/warrior-tank-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-warrior-tank-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/warrior/tank-stat-priority-attributes-pve) |
| rogue-dps | [link](https://www.wowhead.com/classic/guide/rogue-dps-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-rogue-dps-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/rogue/dps-stat-priority-attributes-pve) |
| hunter-dps | [link](https://www.wowhead.com/classic/guide/hunter-dps-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-hunter-dps-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/hunter/dps-stat-priority-attributes-pve) |
| mage-dps | [link](https://www.wowhead.com/classic/guide/mage-dps-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-mage-dps-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/mage/dps-stat-priority-attributes-pve) |
| warlock-dps | [link](https://www.wowhead.com/classic/guide/warlock-dps-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-warlock-dps-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/warlock/dps-stat-priority-attributes-pve) |
| priest-holy | [link](https://www.wowhead.com/classic/guide/priest-healing-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-priest-healing-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/priest/healer-stat-priority-attributes-pve) |
| priest-shadow | [link](https://www.wowhead.com/classic/guide/shadow-priest-dps-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-shadow-priest-dps-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/priest/shadow/dps-stat-priority-attributes-pve) |
| druid-restoration | [link](https://www.wowhead.com/classic/guide/druid-healing-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-druid-healing-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/druid/healer-stat-priority-attributes-pve) |
| druid-feral-tank | [link](https://www.wowhead.com/classic/guide/feral-druid-tank-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-feral-druid-tank-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/druid/feral/tank-stat-priority-attributes-pve) |
| druid-feral-dps | [link](https://www.wowhead.com/classic/guide/feral-druid-dps-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-feral-druid-dps-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/druid/feral/dps-stat-priority-attributes-pve) |
| druid-balance | [link](https://www.wowhead.com/classic/guide/balance-druid-dps-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-balance-druid-dps-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/druid/balance/dps-stat-priority-attributes-pve) |
| paladin-holy | [link](https://www.wowhead.com/classic/guide/paladin-healing-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-paladin-healing-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/paladin/healer-stat-priority-attributes-pve) |
| paladin-protection | [link](https://www.wowhead.com/classic/guide/wow-classic-paladin-tank-pre-raid-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/wow-classic-paladin-tank-molten-core-best-in-slot-gear) | none published |
| paladin-retribution | [link](https://www.wowhead.com/classic/guide/paladin-dps-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-paladin-dps-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/paladin/dps-stat-priority-attributes-pve) |
| shaman-restoration | [link](https://www.wowhead.com/classic/guide/shaman-healing-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-shaman-healing-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/shaman/healer-stat-priority-attributes-pve) |
| shaman-enhancement | [link](https://www.wowhead.com/classic/guide/enhancement-shaman-dps-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-enhancement-shaman-dps-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/shaman/enhancement/dps-stat-priority-attributes-pve) |
| shaman-elemental | [link](https://www.wowhead.com/classic/guide/elemental-shaman-dps-pre-raid-best-in-slot-bis-gear-wow-classic) | [link](https://www.wowhead.com/classic/guide/wow-classic-elemental-shaman-dps-molten-core-best-in-slot-gear) | [link](https://www.wowhead.com/classic/guide/classes/shaman/elemental/dps-stat-priority-attributes-pve) |

Tank fire resistance sets: [Fire Resistance BiS Gear Guide for Tanks](https://www.wowhead.com/classic/guide/best-classic-wow-fire-resistance-tank-gear).

Notes on the sources:

- The gear-set page the operator gave (`/classic/gear-set/60-pre-raid-bis-25754`) embeds one
  set as `"slots":{...}` JSON. That is a single user-made set with no alternatives, so the guides
  are the better source.
- Wowhead refuses requests sent with a full browser user agent (403), and WebFetch returned
  only the page header. A plain `curl -A 'Mozilla/5.0'` returned the full page.
- Fallback checked but not used: the BiSTracker addon data
  ([Zentarg/BiSTracker](https://github.com/Zentarg/BiSTracker), no license file;
  [menevia16a/BiSTracker](https://github.com/menevia16a/BiSTracker), archived). Both were
  scraped from the 2019 Wowhead guides and give one item per slot, with no alternatives.

## 2. Coverage per spec

Columns: alternatives (ids / slots covered), best picks obtainable at 60 / best picks, and ids
that cannot be obtained at 60 across both lists. Every id in every list exists in
`item_template`.

| Spec | Pre-raid ids / slots | Pre-raid best obtainable | MC ids / slots | MC best obtainable | Not obtainable at 60 |
| --- | --- | --- | --- | --- | --- |
| warrior-fury | 56 / 15 | 29/29 | 51 / 16 | 14/17 | 3 |
| warrior-protection | 115 / 15 | 32/32 | 68 / 15 | 15/16 | 1 |
| rogue-dps | 54 / 15 | 19/19 | 53 / 15 | 16/18 | 2 |
| hunter-dps | 50 / 16 | 18/18 | 51 / 15 | 12/15 | 3 |
| mage-dps | 60 / 16 | 19/19 | 51 / 16 | 16/16 | 1 |
| warlock-dps | 113 / 16 | 13/13 | 49 / 16 | 16/16 | 2 |
| priest-holy | 62 / 15 | 22/22 | 49 / 16 | 15/16 | 2 |
| priest-shadow | 88 / 15 | 22/22 | 47 / 16 | 14/15 | 1 |
| druid-restoration | 74 / 16 | 17/17 | 44 / 15 | 12/13 | 1 |
| druid-feral-tank | 69 / 14 | 25/25 | 43 / 15 | 14/15 | 1 |
| druid-feral-dps | 66 / 14 | 21/21 | 39 / 15 | 14/15 | 1 |
| druid-balance | 68 / 16 | 13/13 | 48 / 16 | 14/16 | 3 |
| paladin-holy | 43 / 15 | 17/17 | 37 / 14 | 13/14 | 1 |
| paladin-protection | 58 / 14 | 14/14 | 51 / 14 | 13/14 | 1 |
| paladin-retribution | 58 / 14 | 17/17 | 40 / 13 | 11/13 | 2 |
| shaman-restoration | 52 / 16 | 25/25 | 41 / 15 | 14/15 | 1 |
| shaman-enhancement | 50 / 16 | 22/22 | 39 / 14 | 12/13 | 3 |
| shaman-elemental | 51 / 16 | 23/23 | 42 / 15 | 14/15 | 1 |

A "best" count can be higher than the slot count when a guide marks several items "Best" (two
rings, two trinkets, or tied picks). Slot totals below 16 mean the guide has no table for that
slot, for example a paladin or druid relic, or a two-hand slot for a dual wielder.

### Source mix

Distinct items. An item with several sources counts once in each of them.

| Source type | Pre-raid, all (601) | Pre-raid, best (220) | MC, all (391) | MC, best (156) |
| --- | --- | --- | --- | --- |
| Dungeon boss or trash (creature_loot_template, reference loot) | 282 | 108 | 154 | 44 |
| Quest reward (quest_template RewardItem / RewardChoiceItemID) | 115 | 44 | 36 | 5 |
| World drop (25 or more distinct droppers) | 70 | 18 | 45 | 7 |
| Crafted (recipe spell in craftbook.json) | 61 | 26 | 40 | 17 |
| Dungeon chest (gameobject_loot_template) | 54 | 12 | 30 | 8 |
| Container (item_loot_template) | 49 | 7 | 27 | 2 |
| Honor vendor (npc_vendor, ExtendedCost > 0) | 47 | 14 | 0 | 0 |
| Open-world NPC (fewer than 25 droppers) | 18 | 4 | 21 | 8 |
| Raid (Molten Core 90 and Blackwing Lair 9 in the MC lists) | 4 | 1 | 99 | 67 |
| No source row | 1 | 0 | 9 | 9 |

Each item's sources are in `research/bis/items.json`: creature ids per map, chest object ids,
vendor npc and ExtendedCost, quest ids, recipe spell and profession, and container items.

## 3. What this server changes

- **Onyxia is level 83.** Her loot table is the level-80 reference 34000 (ilvl 232). The classic
  drops (Vis'kag 17075, Deathbringer 17068, Sapphiron Drape 17078, Shard of the Scale 17064) have
  no loot row. The Head of Onyxia (18422, 18423) has no row either, so the head turn-in rewards
  are out of reach: Onyxia Tooth Pendant 18404 and Onyxia Blood Talisman 18406 (quests 7491 and
  7496). This matches `research/molten-core-prep.md` on its branch. Every "mc" list therefore
  means Molten Core plus dungeons, crafting and quests, without Onyxia.
- **Summoned bosses have no `creature` spawn row.** Ragnaros, Nefarian, the Ring of Law
  champions, Gyth, Urok, Kirtonos, Ramstein, Balnazzar, Hel'nurath, Avatar of Hakkar and the
  0.5 set bosses (Valthalak, Mor Grayhoof, Isalien, Kormok) have none. Their map was assigned by
  a fixed npc-to-map table in the build script. Without that table, 84 items looked sourceless.
  Code that places loot by `creature.map` (for example preraid.py) misses these bosses the
  same way.
- **No source row at all:** Rhok'delar 18713 and Lok'delar 18715 (quest 7636 now rewards only
  18707), Benediction 18608 (made from Anathema by a spell), Sulfuras 17182, Egan's Blaster
  13289 (a quest tool), and Major Spellstone 13603 (conjured, DEPRECATED name).
- **Item stats are classic-shaped.** Hit, crit and healing on old items are equip spells
  (Lionheart Helm 12640: spells 7598 and 15465), not 3.3.5 ratings. Classic weights apply
  unchanged through the committed `spells.json`.
- **`spell_dbc` has no create-item rows** for any of the 770 items. Crafted sources come from
  `craftbook.json`, which maps each skill line to spell and created item, built from the DBCs.

## 4. PvP gear as pre-raid

Per `research/pvp-battlegrounds.md` (#520), honor alone buys the level-60 rank sets here, with no
rank or reputation gate:

- Field Marshal / Warlord sets: ilvl 74.
- Marshal / General pieces: ilvl 71.
- Grand Marshal / High Warlord weapons: ilvl 78.
- Battleground reputation epics: ilvl 65.

Wowhead's pre-raid guides list 47 honor-vendor items as alternatives:

- 37 are battleground reputation or low-rank pieces at ilvl 60-65.
- 10 are rank pieces at ilvl 66-71.
- None are the ilvl 74 sets or the ilvl 78 weapons, because Classic gated those behind ranks 10
  to 14.

`situational.json` gives:

- `pvp_honor_by_class`: 318 class-locked entries across 9 classes and 8 armour slots, with
  ilvl, faction and ExtendedCost.
- `battleground_reputation`: 109 entries in 10 slots, open to every class.

The scorer should rate these with the spec weights against the pre-raid list. It should not
assume either side wins. Example: the warrior ilvl 74 helm against the Lionheart Helm 12640
comes down to the weights: the PvP helm's stamina against the Lionheart's hit and crit.

## 5. Stat priority and weights

- **Priority and caps** come from the Wowhead stat guides. They are stored as normalized stat
  tokens in each spec file's `stat_priority.order`, for example
  `["melee_hit_to_9pct","strength","attack_power","agility","crit"]` for fury.
  - Three specs have no ranked list: druid-restoration (the source puts healing first and leaves
    the rest to the build), warrior-protection (only the hit cap is listed), and
    paladin-protection (no Classic stat guide is published).
  - The feral pages publish numeric weights normalized to 1 AP. These are kept as
    `weights_alt`.
- **Numeric weights** come from [wowsims/classic](https://github.com/wowsims/classic): MIT,
  "Copyright (c) 2024 wowsims team", level cap 60. They are `defaults.epWeights` in
  `ui/<spec>/sim.ts`, pinned at the commit recorded in `weights-wowsims.json`. Units: per point,
  per 1% for hit, crit and haste, and per weapon DPS point for the Dps pseudo-stats. Fury, as an
  example: Str 2.51, Agi 1.86, AP 1, Hit 28.67, Crit 25.1, MH DPS 11.92, OH DPS 4.69.
  Some sets need care before use:
  - protection_paladin: Dodge 219.45 and Parry 217.72 against Armor 1, an unnormalized scale.
  - holy_paladin and restoration_druid: identical sets, likely a placeholder.
  - healing_priest: Int 2.73 above SP 1, which suits mana-limited fights rather than raw
    throughput.

  Each of these is flagged `caution` in its spec file.
- **Sixty Upgrades** ([sixtyupgrades.com/forever](https://sixtyupgrades.com/forever/)):
  - How it ranks: weight sets it calls "Equivalency Points". Each class gets preset sets, each
    preset credits an outside author, and users can edit sets, keep several per character and
    filter by phase and level. It has no built-in fire resistance, tank or PvP categories.
  - Data access: a client app over a GraphQL API that requires request signing, not a public
    API. Sets export as link, JSON or CSV. No source code is on GitHub.
  - Terms: [sixtyupgrades.com/terms](https://sixtyupgrades.com/terms) permits personal,
    non-commercial, transitory viewing only, and forbids copying, mirroring and reverse
    engineering. Its preset weights and data cannot be reused.
  - What to adopt: the model only. Each member keeps a pre-raid target, then a BiS target, each
    scored by weights, plus named situational sets kept in the bank. wowsims supplies the numbers.

## 6. Situational sets kept in the bank

`situational.json` holds:

- `tank_fire_resistance`: Wowhead tank FR sets (warrior and druid, pre-raid and post-raid), one
  id per slot.
- `fire_resistance_by_slot`: 143 server items with fire resistance of 10 or more at
  RequiredLevel 50-60, best first, with item class and subclass for armour filtering.
- `pvp_honor_by_class` and `battleground_reputation`: see section 4.
- `bank_sets_by_role`:

| Role | Sets to keep |
| --- | --- |
| Tank | main tank list; fire resistance (Ragnaros, Magmadar, Garr adds); threat or DPS set (fury list, feral DPS list); PvP honor set |
| Healer | main healer list; fire resistance by slot (Ragnaros healers in melee range); PvP set |
| Melee | main list; fire resistance by slot (Ragnaros melee); PvP set |
| Ranged / caster | main list; fire resistance by slot (low priority in MC); PvP set |
| Hybrid (paladin, druid, shaman, priest) | the second spec's list from the same class |

## 7. Storage proposal

Data shape, as committed under `research/bis/` and proposed for `data/bis/`:

```
data/bis/<class>-<spec>.json
{
  "spec": "warrior-fury", "class": "warrior", "spec_name": "fury", "role": "melee",
  "snapshot": "2026-10-04",
  "stat_priority": {"order": [...], "caps": {"melee_hit_pct": 9}, "source_url": "..."},
  "weights": {"source": "...", "source_url": ".../sim.ts@<sha>", "units": "...", "values": {...}},
  "lists": {
    "preraid": {"source_url": "...", "phase": "preraid",
                "slots": {"head": [12640, 22411, 12587, 13404], ...},
                "best":  {"head": [12640], ...},
                "unreachable_at_60": [...]},
    "mc": {... same shape ...}
  }
}
data/bis/items.json          id -> name, ilvl, req, slot, quality, fire_res, sources[], reachable_at_60
data/bis/situational.json    fire resistance, PvP honor, battleground reputation, bank sets by role
data/bis/weights-wowsims.json  all 18 weight sets with the MIT notice and commit
```

The format follows these rules:

- Slots use the server's InventoryType. A one-hand weapon goes in `main_hand`, unless the guide
  ranked it under off hand.
- A list is ordered by preference, best first. Code takes the first item the member can obtain
  and use, and an alternative when the best is out of reach.
- Spec files hold guide facts only. Server facts live in `items.json`, which is regenerated
  separately.

The weights in `statweights.py` and preraid.py's `ROLES` are mirrored by hand from mod-overseer's
C++. They should read these files instead, so one table serves the gear, loot and crafting code.
That keeps one source of truth. It is a separate implementation ticket.

### Refresh plan

1. **Guide lists:** a manual snapshot, not a crawler. A small script fetches the 36 guide pages
   listed in section 1, one request every 2 seconds, about 40 requests in total. It parses the
   ranked tables into ids and slots and writes the spec files. A person reviews the diff before
   commit. Run it only when Wowhead revises a guide, or when the realm moves to a new content
   phase. Wowhead's terms rule out scraping at scale, and this stays well below that: a single
   fetch of public guide pages, keeping facts only, with attribution.
2. **Server sources:** regenerate `items.json` with the read-only DB script after every world DB
   change (upstream rebase, loot patch). Run it in the overseer pod, the same way as this
   research.
3. **Weights:** pin a wowsims commit and bump it by hand. Review the flagged sets before
   enabling them.

## Method and caveats

- Parsing: the ranked tables under each slot heading, where each row holds a rank cell, an item
  cell and a source cell. The paladin tank and fire resistance guides use one row per slot with
  several items. Both layouts are parsed. Rank labels vary by guide ("Best", "Good",
  "Optional"), so only "Best" is kept, as the `best` flag.
- Some guide tables mix phases. The pre-raid guides were revised for Season of Mastery and
  include Dire Maul, 0.5 set pieces and battleground rewards. All of these exist at 60 here. The
  MC guides include a few BWL items (9 of 391).
- World drop means 25 or more distinct creatures drop the item. The source type of an item that
  drops in both a dungeon and the open world is `world_drop`.
- The server queries were read-only SELECTs, run by a script copied into the overseer pod and
  deleted afterwards.

https://claude.ai/code/session_01TTixe8XCvTjiuqSLhi98KX
