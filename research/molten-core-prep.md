# Molten Core prep on this 3.3.5 core: what is required and where each piece comes from

Research for [wo#518](https://github.com/quadseven/wow-overseer/issues/518), workstream F of [wo#512](https://github.com/quadseven/wow-overseer/issues/512). Read 2026-10-04. Read-only: no row was written anywhere.

## Sources

| Source | What was read |
|---|---|
| Core scripts, [mod-playerbots/azerothcore-wotlk `Playerbot` @ f19a1879][ac] | `MoltenCore/instance_molten_core.cpp`, `molten_core.h`, `boss_majordomo_executus.cpp`; `game/Entities/GameObject/GameObject.cpp` (meeting stone, summoning ritual); `game/Spells/Spell.cpp` (summon-player checks); `game/Maps/MapMgr.cpp` (raid-only entry); `scripts/Spells/spell_generic.cpp`; `scripts/Kalimdor/zone_orgrimmar.cpp` |
| Live world DB `acore_world` | `dungeon_access_template`, `dungeon_access_requirements`, `areatrigger_teleport`, `quest_template(_addon)`, `conditions`, `gossip_menu_option`, `smart_scripts`, `creature_onkill_reputation`, `item_template`, `creature_loot_template`, `reference_loot_template`, `gameobject_loot_template`, `npc_vendor`, `trainer_spell`, `creature_default_trainer`, `gameobject_template`, `creature` |
| Live client data | `Spell.dbc` and `SkillLineAbility.dbc` from the running worldserver (craft spell to item, reagents, spell focus, acquire method). The DB `spell_dbc` table holds only overrides and `skilllineability_dbc` is empty. |
| Live config | `worldserver.conf` `Instance.IgnoreRaid = 0`, `Instance.IgnoreLevel = 0`; `playerbots.conf` world-buff and summon keys |

[ac]: https://github.com/mod-playerbots/azerothcore-wotlk/tree/f19a18799a35f7c24bdcdc9ea399c601f166259b/src/server/scripts/EasternKingdoms/BlackrockMountain/MoltenCore

## Summary table

| Piece | Verdict | Source on this server | Effort |
|---|---|---|---|
| Level 50+ and a raid group | Required | `dungeon_access_template` id 24: map 409 min_level 50; `MapMgr.cpp` returns `CANNOT_ENTER_NOT_IN_RAID`; `Instance.IgnoreRaid = 0` | None at 60 |
| Attunement to the Core (7848 / 7487) | Not needed to enter | No `dungeon_access_requirements` rows for map 409. Only gates Lothos Riftwaker's teleport gossip | Small (one BRD fragment) |
| Hydraxian Waterlords rep, Aqual Quintessence, rune dousing | Not needed | Majordomo spawns from boss states only; runes open themselves on boss death | Skip |
| Fire resistance gear | Optional (tank comfort at Ragnaros) | Thorium Brotherhood recipes (Lokhtos, BRD), Volcanic and Wizardweave patterns, BRS/LBRS/Sunken Temple drops | Large (rep grind plus MC mats) |
| Greater Fire Protection Potion | Optional | Recipe drops from Firebrand Invoker / Pyromancer in Blackrock Spire (about 4.3%) | Medium |
| Flasks (Titans, Distilled Wisdom, Supreme Power) | Optional | Recipe drops 3-4%: Drakkisath (UBRS), Balnazzar (Stratholme), Ras Frostwhisper (Scholomance). Needs Black Lotus. No lab needed on 3.3.5 | Large |
| Elixir of the Mongoose, other elixirs | Optional | Mongoose recipe drops in Felwood/Azshara; Greater Arcane Elixir and Major Healing are trainer-taught | Medium |
| Field Repair Bot 74A | Not obtainable | Craft spell 22704 exists in `Spell.dbc`, but nothing teaches it: schematic 18235 has no teach spell, no trainer row, no loot, no vendor | n/a |
| World buffs | Optional, mostly closed at 60 | Songflower (Felwood) and DM tribute open; Warchief's Blessing Horde-only via Rend's head; Rallying Cry only via Nefarian at 60 (Onyxia is level 80+) | Small to medium |
| Warlock Ritual of Summoning | Optional | Spell 698, trained at level 20, one Soul Shard, warlock plus 2 clickers | Small |
| Meeting stone summon | Optional | Stone 179587 (min level 55) / 179586 (min 48) on Blackrock Mountain | None |
| Onyxia | Not needed | Onyxia's Lair is min_level 80 on 3.3.5; no attunement row | Skip |

## 1. Entry and attunement

- `areatrigger_teleport` sends three triggers into map 409: 2886 "The Molten Bridge", 3528 "The Molten Core Window Entrance", 3529 "The Molten Core Window(Lava) Entrance", all to (1091.89, -466.985, -105.084).
- `dungeon_access_template` row 24 for map 409: difficulty 0, min_level 50, max_level 0, min_avg_item_level 0. `dungeon_access_requirements` has no row for that template. No quest or item gates the trigger.
- Raid entry needs a raid group (`MapMgr.cpp` line 178, `CANNOT_ENTER_NOT_IN_RAID`), and `Instance.IgnoreRaid = 0` on the live server.
- The attunement quests 7848 (Alliance, AllowableRaces 1101) and 7487 (Horde, 690) are given by Lothos Riftwaker (14387, Blackrock Mountain, map 0). Each needs one Core Fragment (18412), looted from gameobject 179553 inside Blackrock Depths (map 230). The reward is the condition behind Lothos's gossip option (menu 5750, conditions type 8 on 7848 or 7487), which casts "Teleport to Molten Core DND" (25139). It is a shortcut, not a gate. `raidready.py` already treats it this way.

## 2. Hydraxian Waterlords, quintessence, and runes

How Majordomo appears (`instance_molten_core.cpp`):

- `SetBossState` for any boss below `DATA_MAJORDOMO_EXECUTUS` reaching `DONE` despawns that boss's circle, calls `rune->UseDoorOrButton` on that boss's rune itself, then runs `CheckMajordomoExecutus()`.
- `CheckMajordomoExecutus()` returns true when Ragnaros is not `DONE`, every boss index 0 to 7 except Lucifron (`if (i == DATA_LUCIFRON) continue;`) is `DONE`, and Ragnaros is not present. Then `SummonMajordomoExecutus()` spawns him.
- So the summon reads boss states only. Runes are never checked. Lucifron is not needed either.
- Ragnaros is started from Majordomo's gossip (menu 4108). `boss_majordomo_executus.cpp` `sGossipSelect` has no condition, and `conditions` has no row for menu 4108.

The rune gameobjects (176951 to 176957) are type 1 buttons with lock 1459. Aqual Quintessence (17333, charges -1) and Eternal Quintessence (22754, reusable) cast spell 21358 to open them. Dousing does nothing the boss kill does not already do.

If the quintessence is wanted anyway:

- Duke Hydraxis (13278, Kalimdor) gossip menu 5065. Option 0 gives Aqual Quintessence when Honored with faction 749 (conditions mask 224) and quest 6824 "Hands of the Enemy" is rewarded. Option 1 gives Eternal Quintessence at Revered (mask 192), same quest requirement.
- Chain: 6805 "Stormers and Rumblers" (kill 15 Dust Stormer, 15 Desert Rumbler), 6821 "Eye of the Emberseer" (Pyroguard Emberseer, UBRS), 6822 "The Molten Core" (kill a Molten Giant and a Firelord inside MC), 6823 "Agent of Hydraxis" (needs faction 749 value 9000, that is Honored), 6824 "Hands of the Enemy" (17332, a Hand from MC bosses), 7486 "A Hero's Reward" (Tidal Loop or Ocean's Breeze, 15 fire resistance each).
- Rep sources (`creature_onkill_reputation`): Desert Rumbler / Dust Stormer / Greater Obsidian Elemental give 5 up to Friendly; MC trash 20 to 40 up to Honored; MC bosses 100 up to Revered; Golemagg 150 and Ragnaros 200 up to Exalted. Honored needs MC kills, so the runes cannot be ready before the first clear.

## 3. Fire resistance

`item_template` holds 246 items with fire_res at RequiredLevel 60 or less and ItemLevel 92 or less. The reachable pre-MC ones, by source:

Thorium Brotherhood, sold by Lokhtos Darkbargainer (12944, Blackrock Depths). His gossip needs Friendly with faction 59; each recipe has a `conditions` type 23 rank mask:

| Recipe | Item (fire res) | Profession, skill | Rep |
|---|---|---|---|
| Plans: Dark Iron Helm 19206 | Dark Iron Helm (35) | Blacksmithing 300 | Honored |
| Plans: Dark Iron Leggings 17052 | Dark Iron Leggings (30) | Blacksmithing 300 | Revered |
| Plans: Dark Iron Boots 20040 | Dark Iron Boots (28) | Blacksmithing 300 | Exalted |
| Plans: Dark Iron Gauntlets 19207 | Dark Iron Gauntlets (28) | Blacksmithing 300 | Revered |
| Plans: Dark Iron Bracers 17051 | Dark Iron Bracers (18) | Blacksmithing 295 | Friendly |
| Plans: Fiery Chain Shoulders 17053 | Fiery Chain Shoulders (25) | Blacksmithing 300 | Revered |
| Plans: Fiery Chain Girdle 17049 | Fiery Chain Girdle (24) | Blacksmithing 295 | Honored |
| Pattern: Flarecore Gloves 17018 | Flarecore Gloves (25) | Tailoring 300 | Friendly |
| Pattern: Flarecore Mantle 17017 | Flarecore Mantle (24) | Tailoring 300 | Honored |
| Pattern: Flarecore Robe 19219 | Flarecore Robe (15) | Tailoring 300 | Honored |
| Pattern: Flarecore Leggings 19220 | Flarecore Leggings (16) | Tailoring 300 | Revered |
| Pattern: Molten Helm 17023 | Molten Helm (29) | Leatherworking 300 | Friendly |
| Pattern: Corehound Boots 17022 | Corehound Boots (24) | Leatherworking 295 | Friendly |
| Pattern: Black Dragonscale Boots 17025 | Black Dragonscale Boots (24) | Leatherworking 300 | Honored |
| Pattern: Lava Belt 19330 | Lava Belt (26) | Leatherworking 300 | Honored |

Thorium Brotherhood rep comes from quests rewarding faction 59: "Gaining Acceptance" (13662, 4 Dark Iron Residue), "Gaining Even More Acceptance" (7737, 100 Dark Iron Residue), the BRD/Searing Gorge quest line (7701 to 7729), and the repeatable turn-ins 6642 (10 Dark Iron Ore), 6646 (Blood of the Mountain), 6643 Fiery Core, 6644 Lava Core, 6645 Core Leather. The last three are MC drops, so the high-rep pieces arrive after MC, not before.

Other pre-MC fire resistance sources:

| Source | Items | Where |
|---|---|---|
| Pattern: Volcanic Breastplate / Leggings / Shoulders (Leatherworking 285/270/300) | 20 / 20 / 18 fire res | Breastplate: Firebrand Grunt 4.9%; Shoulders: Firebrand Legionnaire 22.8% (both Blackrock Spire, map 229); Leggings: Firegut Brute 3.9% (map 0) |
| Pattern: Wizardweave Robe / Turban / Leggings (Tailoring 300/300/275) | 18 / 18 / 16 | Dark Caster about 2.2%, Dark Summoner 2.1% (map 0) |
| Schematic: Hyper-Radiant Flame Reflector (Engineering 290) | trinket, 18 | Solakar Flamewreath 6% (UBRS event) |
| Formula: Enchant Cloak - Greater Resistance (Enchanting 265) | +5 all res | Atal'ai Witch Doctor 1.5% (Sunken Temple, map 109) |
| Formula: Enchant Cloak - Greater Fire Resistance (Enchanting 300) | cloak | Kania (15419, Silithus), needs Cenarion Circle (609) rank 4, Friendly |
| Dungeon drops | Wildfire Cape 20 (Pyroguard Emberseer), Lavawalker Greaves 20 and Flamescarred Girdle 20 (Maleki the Pallid), Polychromatic Visionwrap 20 (Solakar), Incendius bracers 10, Cape of the Fire Salamander 12 (Ambassador Flamelash) | BRD, UBRS, Stratholme |
| Quest 7486 "A Hero's Reward" | Tidal Loop / Ocean's Breeze, 15 | Hydraxis chain, after MC kills |
| Class auras | Fire Resistance Aura (19900, paladin, level 60 rank +60), Fire Resistance Totem (10538, shaman, level 58) | Trainers |

The MC loot itself carries fire res (Fireguard Shoulders 22, Fireproof Cloak 18, Finkle's Lava Dredger 15, Core Forged Greaves 12, all in reference 12000, the Cache of the Firelord). Judgment, not data: nothing in the core scripts reads a resistance threshold, so fire resistance only reduces damage taken; it is a tank and healer comfort for Ragnaros, not a gate.

## 4. Consumable recipes

Craft spells, reagents and spell focus come from `Spell.dbc`; recipe sources from the live DB.

| Consumable | Craft spell, reagents | Recipe source on this server |
|---|---|---|
| Flask of the Titans 13510 | 17635: 7 Gromsblood, 3 Stonescale Oil, 1 Black Lotus, 1 Crystal Vial; focus 0 | Recipe 13519 drops from General Drakkisath (UBRS) 3%. Item 31354 is an Exalted Sha'tar vendor copy (Outland) |
| Flask of Distilled Wisdom 13511 | 17636: 7 Dreamfoil, 3 Icecap, 1 Black Lotus, 1 vial | Recipe 13520 drops from Balnazzar (Stratholme) 3%. 31356 Exalted Cenarion Expedition (Outland) |
| Flask of Supreme Power 13512 | 17637: 7 Dreamfoil, 3 Mountain Silversage, 1 Black Lotus, 1 vial | Recipe 13521 drops from Ras Frostwhisper (Scholomance) 4%. 31355 Exalted Keepers of Time (Outland) |
| Flask of Chromatic Resistance 13513 | 17638 | Recipe 13522 from Gyth (UBRS) 3% |
| Greater Fire Protection Potion 13457 | 17574: 1 Elemental Fire, 1 Dreamfoil, 1 vial. Absorbs 1950 fire (spell 17543) | Recipe 13494 drops from Firebrand Invoker 4.4% and Firebrand Pyromancer 4.2% (Blackrock Spire) |
| Fire Protection Potion 6049 | 7257 | Recipe 6055 sold by Jeeda and Nandar Branson |
| Elixir of the Mongoose 13452 | 17571: 2 Mountain Silversage, 2 Plaguebloom, 1 vial | Recipe 13491 drops from Jadefire Rogue 4% (Felwood) and Legashi Rogue 3.6% (Azshara) |
| Greater Arcane Elixir 13454 | 17573 | Trainer-taught at Alchemy 285 (alchemy trainer ids 65 to 67), plus rare world drops |
| Major Healing Potion 13446 | 17556 | Trainer-taught at Alchemy 275 |
| Major Mana Potion 13444 | 17580 | Recipe 13501: Darkmaster Gandling 10% (Scholomance) or vendor Magnus Frostwake |
| Elixir of Giants 9206 | 11472 | Recipe 9298, rare world drop and chests |
| Elixir of Superior Defense 13445 | 17554 | Recipe 13478 sold by Kor'geld and Soolie Berryfizz |
| Greater Stoneshield Potion 13455 | 17570 | Recipe 13490, rare world drop |
| Mageblood Elixir 20007 | 24365 | Recipe 20011, Rin'wosho the Trader, Zandalar Tribe Revered |
| Elixir of Greater Firepower | 26277 | Recipe 21547 from Dark Iron Slaver / Taskmaster / Watchman, about 1% |
| Dirge's Kickin' Chimaerok Chops | 25659 | Quest 8586 |
| Runn Tum Tuber Surprise | 22761 | Pusillin 100% (Dire Maul) |

All four flasks have spell focus 0 in this `Spell.dbc`, so no alchemy lab is needed. None of the four flasks, the two fire protection potions, Mongoose, Greater Arcane Elixir or Elixir of Giants is sold by a vendor or dropped as an item; they are crafted. Elemental Fire drops from MC bosses (30%) and fire elementals.

## 5. Field Repair Bot 74A

- Item 18232 (RequiredSkill 202 Engineering, rank 300) summons the bot with spell 22700.
- The craft spell is 22704 "Field Repair Bot 74A": 16 Thorium Bar, 2 Fused Wiring, focus 1 (anvil).
- Nothing on this server teaches 22704. Schematic 18235 has spellid_1 to spellid_3 all 0. `trainer_spell`, `npc_trainer`, `skill_discovery_template`, quest rewards, `npc_vendor` and every loot table have no row for 22704, 18235 or 18232. `SkillLineAbility.dbc` row 12296 has AcquireMethod 0 (not learned with the skill).
- So the bot cannot be had naturally. Repairs mean leaving the instance (hearth, a mage portal, or a summon back in).

## 6. World buffs

| Buff | How it is cast here | Open to a level 60 guild? |
|---|---|---|
| Songflower Serenade 15366 | Cleansed Songflower gameobjects (type 10, spell 15366) in Felwood, spawned after quests 2523 / 2878 "Corrupted Songflower". `spell_gen_disabled_above_63` scales it by level/60 and drops it above 63 | Yes |
| Dire Maul tribute: Fengus' Ferocity 22817, Mol'dar's Moxie 22818, Slip'kik's Savvy 22820 | Guard gossip (menus 5734, 5735, 5733) in Dire Maul (map 429). Conditions: level 63 or lower and not already buffed | Yes, after a tribute run |
| Warchief's Blessing 16609 | Herald of Thrall (10719) casts it after quest 4974 "For The Horde!" (Head of Rend Blackhand 12630, UBRS). `zone_orgrimmar.cpp` | Horde only |
| Rallying Cry of the Dragonslayer 22888 | Overlord Runthak (quests 7491, 7784) and Major Mattingly (7496) action lists. 7491/7496 follow the Head of Onyxia 18422/18423, but Onyxia (10184, level 83) now drops only 49643/49644, which start the level 80 quest 24428/24429. 7784 follows the Head of Nefarian 19002 (BWL) | Only after BWL |
| Spirit of Zandalar 24425 | Molthor action list (Heart of Hakkar, quest 8183) | Only after Zul'Gurub |

Bots: `playerbots.conf` has `AiPlayerbot.WorldBuffMatrix`, which grants the vanilla bracket (level 60 to 69) flasks such as 17626 Flask of the Titans when a player sends `nc +worldbuff` to a bot. That is an unearned grant and does not count as natural prep.

## 7. Summoning

- Ritual of Summoning 698: base level 20, trained at level 20 (`trainer_spell` 31), reagent one Soul Shard (6265). It spawns gameobject 194108 "Summoning Portal", type 18 with reqParticipants 3. `GameObject.cpp` counts unique users, and the warlock is one of them, so the warlock plus two group members must click. The summon effect (7720) checks in `Spell.cpp` that the target is in the same raid and, when the caster is in a dungeon, that the target satisfies the map's access requirement (level 50 for MC).
- Meeting stones: `GameObject.cpp` type 23 casts Meeting Stone Summon 23598 when one raid member uses the stone with another raid member targeted, and both are at or above the stone's minLevel. Blackrock Mountain stones: 179587 (min 55, max 60) and 179586 (min 48, max 60). One user is enough.
- `AiPlayerbot.SummonWhenGroup = 1` teleports bots to a leader on group join. That is a bot convenience, not the natural summon.

## 8. Onyxia

Not needed for MC. Onyxia's Lair on 3.3.5 (`dungeon_access_template` 15 and 16) is min_level 80 with no attunement row, and Onyxia is level 83. Her old head quests for Rallying Cry are unreachable at 60 (section 6).

## Bottom line

To enter and finish Molten Core on this core, a level 50+ raid group is enough. Attunement, Hydraxian rep, quintessence and runes do not gate any boss or Majordomo. Fire resistance, flasks, potions, world buffs and summons are optional quality, and the Field Repair Bot cannot be learned at all.
