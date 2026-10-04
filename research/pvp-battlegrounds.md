# PvP at level 60: battleground rewards and playerbot battlegrounds

Research for [#520](https://github.com/quadseven/wow-overseer/issues/520), workstream H of the
Ragnaros wayfinder [#512](https://github.com/quadseven/wow-overseer/issues/512).
Measured 2026-10-04 against the wow-dev world (read-only).

## Answer

- Honor buys raid-grade gear at 60 on this server. The legacy rank vendors sell the Field
  Marshal / Warlord sets (ilvl 74), Marshal / General pieces (ilvl 71) and Grand Marshal /
  High Warlord weapons (ilvl 78) for honor alone, RequiredLevel 60, no PvP rank and no
  reputation gate. That is BWL-level gear, above anything Molten Core drops (ilvl 66).
- The battleground reputation vendors sell ilvl 65 epics (AV rings, offhands, shields and
  weapons; WSG legs and bracers; AB shoulders, cloaks and staff) and ilvl 63 blues, also honor
  only. These are pre-raid to MC-grade. None carries a reputation requirement in this
  server's item data.
- Level 60 brackets: WSG 60-69 and AB 60-69 (only 60s meet, since MaxPlayerLevel is 60);
  AV 51-60 (60s share it with 51-59).
- Playerbots queue and play WSG, AB, AV, EotS and IoC with per-map tactics. Random bots only
  queue to fill demand: a real player in the queue, or the auto-join brackets. The shipped
  auto-join brackets name the level-80 brackets, so on this realm bots never start a level-60
  battleground on their own today.
- Group queue: yes. A bot group leader queues its whole party as a group, and any bot accepts
  the invite. The core caps the group at 5 for AV, 10 for WSG and 15 for AB.

## 1. Bracket data

Source: `acore_world.battleground_template`, and `PvpDifficulty.dbc` /
`BattlemasterList.dbc` read from the worldserver's own data directory (the `*_dbc` SQL
tables for these are empty, so the core loads the DBC files).

| BG | battleground_template MinLvl-MaxLvl | min/max per team | Bracket holding level 60 | Max group size (BattlemasterList) |
| --- | --- | --- | --- | --- |
| Alterac Valley (map 30) | 51-80 | 20/40 | id 0 = 51-60 | 5 |
| Warsong Gulch (map 489) | 10-80 | 5/10 | id 5 = 60-69 | 10 |
| Arathi Basin (map 529) | 20-80 | 8/15 | id 4 = 60-69 | 15 |

Full PvpDifficulty rows: WSG 10-19, 20-29, 30-39, 40-49, 50-59, 60-69, 70-79, 80-85
(ids 0-7); AB 20-29 ... 80-85 (ids 0-6); AV 51-60, 61-70, 71-79, 80-85 (ids 0-3).

`MaxPlayerLevel = 60` in the live worldserver.conf, so no 61-69 character exists. In WSG and
AB a 60 only meets other 60s. In AV a 60 is matched with 51-59s, and the AV vendors' honor
gear starts at RequiredLevel 55.

Population on wow-dev at the time of measurement: 171 Alliance and 181 Horde level-60
characters online (461 / 492 in total), enough for any of the three. The natural guilds have
no 60 yet: Cave (Alliance, 71 members) tops out at 59, Bonkers (Horde, 71) at 27.

## 2. Costs

`npc_vendor.ExtendedCost` resolves through `ItemExtendedCost.dbc`. Every cost id below is
honor only: no marks of honor, no arena points, no item tokens. `MaxHonorPoints = 75000`.

| ExtendedCost | Honor | ExtendedCost | Honor |
| --- | --- | --- | --- |
| 427, 428, 497, 520 | 3000 | 501, 541, 465, 746, 748 | 9000 |
| 488, 489, 495, 702, 652, 653, 444 | 5000 | 701 | 12000 |
| 491, 492, 532, 533, 774 | 1600 | 2291 | 13000 |
| 496 | 2400 | 463, 464, 490, 542 | 15000 |
| 747 | 6000 | 567 | 16000 |
| 2257 | 25000 | 1005 (war mount) | 50000 |

Reputation: `item_template.RequiredReputationFaction` and `RequiredReputationRank` are 0 on
every item listed here, and the `conditions` table has no vendor rows (source type 23) for
these NPCs. On this server, buying needs honor and a vendor that is not hostile, nothing
else. `requiredhonorrank` is also 0 on the legacy rank gear.

## 3. Reward table (level 60 relevant rows)

### Alterac Valley: Stormpike (13216, 13217) / Frostwolf (13218, 13219) Supply Officers

| Item | ilvl | Req | Honor | Raid-worthy at 60 |
| --- | --- | --- | --- | --- |
| Don Julio's Band (19325), ring | 65 | 60 | 5000 | Yes, melee hit ring (pre-raid BiS class) |
| Don Rodrigo's Band (21563), ring | 65 | 60 | 5000 | Yes, agility ring |
| The Immovable Object (19321), shield | 65 | 60 | 5000 | Yes, tank shield |
| The Unstoppable Force (19323), 2H mace | 65 | 60 | 5000 | Yes |
| The Lobotomizer (19324), dagger | 65 | 60 | 5000 | Yes, caster |
| Therazane's Touch, Tomes of Arcane Domination / Shadow Force / Ice Lord / Fiery Arcana, Lei of the Lifegiver (offhands) | 65 | 60 | 5000 | Yes, caster / healer offhands |
| Crackling Staff / Whiteout Staff | 65 (blue) | 60 | 3000 | Marginal |
| Electrified Dagger, Stormstrike Hammer / Glacial Blade, Frostbite | 65 (blue) | 60 | 2400 | Marginal |
| Faction belts, cloaks, pendants, quivers | 60 (blue) | 55 | 1600-3000 | No (filler) |

### Warsong Gulch: Silverwing (14753) / Warsong (14754) Supply Officers

| Item | ilvl | Req | Honor | Raid-worthy at 60 |
| --- | --- | --- | --- | --- |
| Sentinel's / Outrider's legs (plate, chain, mail, leather, lizardhide, silk, lamellar) | 65 | 60 | 9000 | Yes, strong pre-raid legs |
| Berserker, Dryad's, Forest Stalker's, Windtalker's bracers | 65 | 60 | 5000 | Yes, pre-raid bracers |
| Bows, swords, blades, staff, rings, cape, medallion | 63 (blue) | 58 | 1600-15000 | Mostly no |

### Arathi Basin: League of Arathor (15127) / Defilers (15126) Supply Officers

| Item | ilvl | Req | Honor | Raid-worthy at 60 |
| --- | --- | --- | --- | --- |
| Highlander's / Defiler's shoulders (all armor types) | 65 | 60 | 9000 | Yes, pre-raid shoulders |
| Cloak of the Honor Guard / Deathguard's Cloak | 65 | 60 | 5000 | Yes |
| Sageclaw / Mindfang (offhand weapon) | 65 | 60 | 9000 | Yes |
| Ironbark Staff | 65 | 60 | 16000 | Yes, feral staff |
| Boots, girdles, talisman | 63 (blue) | 58 | 3000 | Filler |

### Legacy rank gear: Legacy Armor / Weapon Quartermasters (Alliance 12785 / 12784, Horde 12795 / 12794)

| Item group | ilvl | Req | Honor | Raid-worthy at 60 |
| --- | --- | --- | --- | --- |
| Grand Marshal's / High Warlord's weapons and shields | 78 | 60 | 13000 (1H, offhand, ranged) / 25000 (2H) | Yes, BWL-tier and above |
| Field Marshal's / Warlord's chest, helm | 74 | 60 | 15000 each | Yes, T2-class |
| Field Marshal's / Warlord's shoulders | 74 | 60 | 9000 | Yes |
| Marshal's / General's legs | 71 | 60 | 15000 | Yes |
| Marshal's / General's gloves, boots | 71 | 60 | 9000 | Yes |
| Lieutenant Commander's / Champion's helm, shoulders (blue) | 71 | 60 | 5000 / 3000 | Yes, early |
| Knight-Captain's / Legionnaire's chest, legs (blue) | 68 | 60 | 5000 | Yes, early |
| Knight-Lieutenant's / Blood Guard's gloves, boots (blue) | 66 | 60 | 3000 | Yes, early |

The Accessories Quartermasters (12781, 12793, 12799, 12805) also sell Insignia of the
Alliance / Horde (ilvl 60, 2805 honor, a PvP trinket, not a raid item) and ilvl 63 rank
bracers / cape for 1600 honor. Their ilvl 100+ items require level 70.

Raid-worthy in short: the legacy rank sets and weapons outclass Molten Core outright; the
reputation vendors' ilvl 65 epics (AV rings and offhands, WSG legs and bracers, AB
shoulders) are MC-grade pre-raid pieces. All of it is earned through play (honor), not
granted.

## 4. How playerbots fight battlegrounds

Code read from `quadseven/mod-playerbots` master (`7bae1b5c`); the files below are
byte-identical at `7a593fa2`, the build wow-dev runs per the infra wow-dev kustomization.

Queueing (`src/Ai/Base/Actions/BattleGroundJoinAction.cpp`, `src/Bot/RandomPlayerbotMgr.cpp`):

- The non-combat strategy `bg` (trigger `often` -> action `bg join`) is added in
  `AiFactory.cpp` only for random bots that are ungrouped or lead their group, when
  `AiPlayerbot.RandomBotJoinBG = 1`.
- `BGJoinAction::isUseful` refuses when: BG joining is disabled, the bot is in a battleground
  or a queue, logged in under 120 s ago, below level 10, has a real-player master, is a
  non-leader group member, in combat, or a deserter.
- `shouldJoinBg` queues only into demand. `RandomPlayerbotMgr::CheckBgQueue` sets
  `activeBgQueue` for a bracket when a real player sits in that queue, or, with
  `RandomBotAutoJoinBG = 1`, for each configured auto-join bracket below its battle count.
  Bots then join per faction until each side reaches `TeamSize * (activeBgQueue + running
  instances)`.
- `JoinQueue` sends `CMSG_BATTLEMASTER_JOIN` with `joinAsGroup = true` when the bot leads a
  group, and counts the whole party against the bracket.
- Invites: the `bg status` trigger lives in the default world-packet strategy, so every bot,
  random or not, answers `STATUS_WAIT_JOIN` with `CMSG_BATTLEFIELD_PORT` and enters.

In the battleground (`AiFactory.cpp` battleground switch, `BattlegroundStrategy.cpp`,
`BattleGroundTactics.cpp`), for any bot inside a battleground:

- `battleground`: move to start, then to objective; re-pick the objective on death.
- `warsong`: flag carrier logic (pick up, run home, protect FC, attack enemy FC), buffs.
- `arathi`: node capture (`bg check flag`), buffs.
- `alterac`: objective paths per team (graveyards, towers, bosses), snowfall graveyard
  trigger. `GetBotStrategyForTeam` picks a per-team plan.
- `eye` and `isle` also exist; arenas use `arena`.

Group queue for guild bots: yes. The core's `Group::CanJoinBattlegroundQueue` accepts the
group when it is not an LFG group, fits BattlemasterList `maxGroupSize` (AV 5, WSG 10,
AB 15), all members share the bracket and faction, and none is a deserter or already queued.
Two ways to get a guild party in:

1. A real player (or selfbot) leads the party and queues "join as group"; bot members port
   in through `bg status`.
2. A random-bot leader with the `bg` strategy self-queues its party, but only into demand
   as above. Natural-guild members (Cave, Bonkers) are random bots, and no wow-dev patch
   touches the battleground paths (patches 0024 and 0030 only mention `InBattleground` in
   context lines).

## 5. Current wow-dev configuration

Neither `production/oke/manifests/wow-dev/config/playerbots.overrides.conf` nor the base
`../wow/config/playerbots.overrides.conf` sets a battleground key, so the live
`playerbots.conf` carries the shipped defaults (read from the running worldserver):

| Key | Live value | Effect at 60 |
| --- | --- | --- |
| `AiPlayerbot.RandomBotJoinBG` | 1 | Random bots fill queues a player opens |
| `AiPlayerbot.RandomBotAutoJoinBG` | 0 | Bots never open a queue themselves |
| `AiPlayerbot.RandomBotAutoJoinWSBrackets` | 7 (80) | Inert at 60; 60 is bracket 5 |
| `AiPlayerbot.RandomBotAutoJoinABBrackets` | 6 (80) | Inert at 60; 60 is bracket 4 |
| `AiPlayerbot.RandomBotAutoJoinAVBrackets` | 3 (80) | Inert at 60; 60 is bracket 0 |
| `AiPlayerbot.RandomBotAutoJoinBG{WS,AB,AV}Count` | 1, 1, 0 | AV count 0 |
| `AiPlayerbot.FastReactInBG` | 1 | |

Worldserver: `Battleground.InvitationType = 0`, `Battleground.PremadeGroupWaitForMatch =
1800000`, `Battleground.CastDeserter = 1`, `Battleground.GiveXPForKills = 0`,
`MaxHonorPoints = 75000`.

To have bots run level-60 battlegrounds without a player in the queue: set
`RandomBotAutoJoinBG = 1`, `RandomBotAutoJoinWSBrackets = 5`,
`RandomBotAutoJoinABBrackets = 4`, `RandomBotAutoJoinAVBrackets = 0`, and a non-zero
`RandomBotAutoJoinBGAVCount`. Upstream notes over-queuing with many brackets, and the
auto-join waits until `playerBots.size() >= GetMaxAllowedBotCount()`.

## Sources

- Live world DB (`acore_world`): `battleground_template`, `battlemaster_entry`,
  `npc_vendor`, `item_template`, `creature_template`, `conditions`; `acore_characters` for
  population counts.
- Worldserver data directory: `PvpDifficulty.dbc`, `ItemExtendedCost.dbc`,
  `BattlemasterList.dbc`; live `worldserver.conf`, `modules/playerbots.conf`.
- `quadseven/mod-playerbots`: `src/Ai/Base/Actions/BattleGroundJoinAction.cpp`,
  `src/Ai/Base/Actions/BattleGroundTactics.cpp`, `src/Ai/Base/Strategy/BattlegroundStrategy.cpp`,
  `src/Bot/Factory/AiFactory.cpp`, `src/Bot/RandomPlayerbotMgr.cpp`, `conf/playerbots.conf.dist`.
  Upstream `mod-playerbots/mod-playerbots` (`037c014`) differs only by a constant name in the
  join action.
- `mod-playerbots/azerothcore-wotlk` at `7f12e89e`: `src/server/game/Groups/Group.cpp`
  (`CanJoinBattlegroundQueue`), `src/server/shared/DataStores/DBCStructure.h`
  (`BattlemasterListEntry.maxGroupSize`).
- infra: `production/oke/manifests/wow-dev` and `production/oke/manifests/wow`
  (config overrides, kustomization).
