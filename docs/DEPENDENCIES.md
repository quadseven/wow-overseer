# The realm's upstream modules and what they already ship

The worldserver this project drives is built from a core plus six modules, each
pinned to a commit. The largest, the playerbots module, already ships raid
strategies (Molten Core included), class and role AI, gathering, travel and
questing. A behaviour that looks missing from the bots may already exist in a
pinned module. Check before you write or file one.

## The rule

1. Before you write or file a bot behaviour, search the pinned module's source
   for an existing mechanism: its strategy, trigger and action creator tables,
   its `conf/*.conf.dist`, and the directory for that area.
2. Never copy a commit from memory. The realm's build pins each module to a
   commit; ask the operator or read the build's pins file.
3. Read the source at the pinned commit, not the default branch. The playerbots
   module is a fork and differs from upstream.
4. A mechanism that exists but is switched off is a config key, not a feature.
5. Where you did not read the code, say "not read".

## The modules

| Repo | Purpose | What it already ships | On the dev realm |
|---|---|---|---|
| `mod-playerbots/azerothcore-wotlk` | The core: AzerothCore on the `Playerbot` branch, with the hooks the playerbots module needs. | Game server, boss scripts, auction house, mail, trainers. | Yes. |
| `quadseven/mod-playerbots` | The operator's fork of the playerbots module. The AI engine for every bot. | Strategy engine, class AI for ten classes, 19 raid strategies, 21 dungeon strategies, RPG, gathering, travel, quests, loot rolls, trading, guild tasks. | Yes. Instance strategies apply on map entry. |
| `DustinHendrickson/mod-ollama-chat` | LLM chat voice for bots. | Personalities, chat memory, sentiment, event and guild chatter. | Yes, event and guild chatter on, whisper replies off. |
| `quadseven/mod-dungeon-clear` | A tank bot leads a party through a whole dungeon. | Navmesh routing, trash pulls, scripted events, looting, resting, resurrection. | Yes. |
| `quadseven/mod-overseer` | This project's control plane inside the worldserver. | `overseer_command` verbs, run drivers, recovery, snapshots and records. | Yes. |
| `noisiver/mod-junk-to-gold` | Sells grey loot on pickup. | One loot hook; grey items become money and are destroyed. | Yes. |
| `NathanHandley/mod-ah-bot-plus` | An auction house bot. | Seller, buyer, pricing and listing rules. | Installed, its seller is intentionally not used (below). |

## What the playerbots module ships

Read at the pinned commit: the README, `AGENTS.md`, `conf/playerbots.conf.dist`,
the file tree, the Molten Core files, the raid and dungeon trigger tables and
`PlayerbotAI::ApplyInstanceStrategies`. Not read: class rotations, `AiFactory`,
the travel manager, the other raid actions.

- **Strategy system.** Each bot has an engine per state (combat, non-combat,
  dead, react). An engine holds strategies; a strategy is a list of triggers
  with the actions they fire. A bot gets a strategy from the factory defaults
  at login, from the config keys `CombatStrategies`, `NonCombatStrategies` and
  `ReactStrategies`, from chat commands (`co +name`, `nc +name`), from bridge
  orders, and on entering an instance. A runtime toggle is lost on restart.
- **Instance strategies.** With `ApplyInstanceStrategies = 1` (the dist
  default) the bot's map id selects a strategy on entry: 409 `moltencore`,
  249 `onyxia`, 469 `bwl`, 509 `aq20`, 533 `naxx`, 532 `karazhan`, 534 `hyjal`,
  544 `magtheridon`, 548 `ssc`, 550 `tempestkeep`, 564 `blacktemple`,
  565 `gruulslair`, 568 `zulaman`, and Wrath and TBC dungeon maps.
- **Raid folders** (`src/Ai/Raid/`): MC, Ony, BWL, Aq20, Naxx, Kara, Gruul, Mag,
  SSC, TK, Hyjal, BT, ZA, EoE, OS, VoA, Uld, RS, ICC.
- **Molten Core, by trigger name.** Shadow or fire resistance for Lucifron,
  Magmadar, Gehennas, Garr, Baron Geddon, Sulfuron, Golemagg, Majordomo and
  Ragnaros; the living bomb carrier moves from the group; Baron Geddon's
  inferno makes the group move away; Shazzrah ranged move away; Golemagg main
  tank, assist tank on the Core Ragers, boss marking, magma splash back off and
  healer position; core hound marking; move out of lava. The source carries a
  TODO for Magmadar's fear. What each trigger's code does was read only for
  the Molten Core folder.
- **Other raids, by boss.** Onyxia: tail, deep breath, whelps, eggs. BWL:
  Razorgore, Vaelastrasz, Broodlord, the three drakes, Chromaggus, Nefarian.
  Naxx: every wing boss. Kara, Gruul, Magtheridon, SSC, TK, Hyjal, BT, ZA,
  Ulduar, Ruby Sanctum and Icecrown also have per-boss triggers.
- **Dungeon folders** (`src/Ai/Dungeon/`): Wrath AN, AK, CoS, DTK, FoS, GD, HoL,
  HoS, Nex, OC, PoS, TOC, UK, UP, VH; TBC AC, Mech, MgT, Ramp, Seth, UB.
  Classic dungeons have no folder; mod-dungeon-clear covers them.
- **Class AI.** `src/Ai/Class/` for death knight, druid, hunter, mage, paladin,
  priest, rogue, shaman, warlock and warrior.
- **Gathering, travel, RPG, quests.** `src/Ai/World/Rpg/` (new RPG strategy,
  gather, outdoor PvP), gather node manager, travel manager and travel actions,
  quest strategies, fishing and sell actions. Behaviour not read. Keys:
  `EnableNewRpgStrategy`, `RpgStatusProbWeight.*`, `AutoDoQuests`,
  `EnableRandomBotTrading`, `EnableGuildTasks`.
- **Key prefix.** The keys are `Playerbots.*`. Older docs say `AiPlayerbot.*`.
- **Random-bot gate.** Many upstream systems return early unless the bot is a
  random bot. Roster characters use named accounts, so they are not. Check that
  gate first when an upstream feature "does not run" for roster characters.

## Auction house

The auction house is a real economy: only listings that real bot characters post
from what they gathered, crafted or looted. The auction house bot module is
installed and its seller and buyer are off by default and not configured on the
dev realm, so an empty house is expected. Do not enable it or propose generated
listings. The playerbots module has no live auction posting strategy; its one
auction function is inside a comment block.

## The other modules

- **mod-dungeon-clear.** `.dc on` in a party led by a bot tank. Keys:
  `DungeonClear.Enable`, `RestHealthPct`, `RestManaPct`, `SmartRest*`,
  `PostCombatRez`, `StrandedRecovery`, `Pull*`, `CombatRegroup*`,
  `HealReposition*`, `LootMinQuality`, `DungeonQueueFill.*`.
- **mod-ollama-chat.** Keys: `OllamaChat.Enable`, `Provider`, `Url`, `Model`,
  `MaxConcurrentQueries`, `EnableWhisperReplies`, `EnableRandomChatter`,
  `EnableEventChatter`, `EnableRPPersonalities`, `EnableSentimentTracking`,
  `EnableChatHistory`, `EnableRAG`.
- **mod-junk-to-gold.** No keys. Grey loot never reaches a bag or the auction house.
- **mod-ah-bot-plus.** Keys: `AuctionHouseBot.EnableSeller`, `GUIDs`,
  `ItemsPerCycle`, `Buyer.Enabled`, `ListProportion.*`, `AdvancedPricing.*`.
- **mod-overseer.** Keys: `Overseer.Recruit.*`, `Raid.*`, `RequireClient`,
  `HeadlessRoster`, `Recovery.*`, `DungeonFinder.*`, `GuildFinder.*`,
  `PartyWalk.*`, `FarWalk.*`, `Hunt.*`, `Cross.*`, `Individual.Enable`, `Natural.*`.
