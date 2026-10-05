# Guild run wipes: why Cave's Wailing Caverns and Deadmines groups die

Research for [#575](https://github.com/quadseven/wow-overseer/issues/575), workstream E of the [Ragnaros map](https://github.com/quadseven/wow-overseer/issues/512). Measured read-only on wow-dev on 2026-10-04, 16:56 to 21:20 America/New_York (runs 190 to 211).

## Answer

Cave's groups go in without a tank or a healer. The coordinator seats a member by class when nobody in band has the spec, and every Cave "healer" was an Enhancement shaman or a Retribution paladin, and five of seven Cave "tanks" were Retribution paladins or Balance druids. Playerbots plays a bot by its strategies, not its seat, so these members melee and cast damage. mod-dungeon-clear confirms it: 7 of 9 Cave entries logged "no tank in the party, so the group leader leads", and the healer mana it gates pulls on read a flat 100% in all 9, which is what it reports when no member has a heal strategy. Bonkers, which seats Protection warriors and Holy priests, made the only clear.

On top of that, four play patterns turn hard fights into wipes: the boss is engaged together with the elites that wander beside it, packs of three or more elites are pulled whole, the group pulls at half mana because nobody carries a drink, and tanks and healers run 3 to 5 levels under the trash in item level 3 to 9 gear.

## Sources

| Source | What it gave |
|---|---|
| `acore_characters.overseer_guild_run`, runs 190 to 211 | members, seats, door, band, outcome, deaths, bosses |
| Worldserver `module.overseer` "guild death" lines (Datadog, service wow-worldserver) | every guild death: victim level, class, max health, worn item level, killer, map |
| mod-dungeon-clear `[DC:<leader>]` lines (Datadog), 12 runs, 30,000 lines | pull verdicts with weight, ceiling, tank HP, healer and caster mana; first contacts; rest waits; rez holds |
| `character_inventory` joined to `item_template` | worn slots, average item level, quality, food and drink in bags |
| `overseer_raid_spec` | each seat holder's talent tree |
| `acore_world.creature`, `creature_template` | boss rooms and mob levels |
| mod-dungeon-clear `fix/rez-needs-mana-on-pin` (c094209) | `DcPullPlanner.cpp`, `DcRestFloorDecision.{h,cpp}`, `DcTargeting.cpp`, `DcSettingsRegistry.h` |
| mod-playerbots `PlayerbotAI::IsTank` and `IsHeal` | a bot is a tank or healer by strategy (`ContainsStrategy`), not by seat |
| wow-overseer `guildrun.py` | seat fit (`spec` or `class`), coverage gate, door floors |

`overseer_death` holds no instance deaths for these runs. The running worldserver started at 19:45 ET, 14 minutes before [mod-overseer#839](https://github.com/quadseven/mod-overseer/pull/839) (guild-member death rows) merged, so the guild death log lines stand in for it. The site meter is families-only and keeps no history, so healing done per run is not measured; healer activity is inferred from strategies and the readiness gate.

## The runs

22 runs formed. 1 cleared, 7 wiped, 4 were abandoned, 4 were lost (claim expired), 2 were not entered, 2 were refused, 2 were still inside at the end. Times are America/New_York. Item level is worn average at death.

| Run | Guild, door | Tank (seat fit) | Healer (seat fit) | Damage | Result | Deaths in order (killer) | Where |
|---|---|---|---|---|---|---|---|
| 190 | Cave, Wailing Caverns | Ahgeathou 19 Ret paladin (class), il 4 | Auren 22 Enh shaman (class) | Aurevil 21 pal, Annestia 19 rogue, Astamara 19 Balance druid | wiped, 0/7 bosses | Astamara (Anacondra), Ahgeathou (Guardian), Annestia (Guardian), Auren, Aurevil (Anacondra) | Lady Anacondra plus 2 Deviate Guardians |
| 191 | Bonkers, Ragefire | Eazoth 18 Prot warrior (spec) | Bazmoth 16 Holy priest (spec) | Ginny 20 lock, Blandorion 19 lock, Cario 19 rogue | cleared | Blandorion (Molten Elemental) | trash |
| 192 | Cave, Wailing Caverns | Goraraa 20 Ret paladin (class) | Ganras 19 Enh shaman (class) | Ceneelkarn 19 lock, Derred 19 mage, Fineklees 19 lock | lost after killing Anacondra | Goraraa (Anacondra) | Anacondra |
| 197 | Cave, Wailing Caverns | Krebraco 15 Prot warrior (spec) | Ahgeathou 19 Ret paladin (class) | Derred mage, Fineklees lock, Ganras shaman | wiped | Fineklees, Krebraco (Druid of the Fang, 3-mob pack); after rez: Fineklees (Guardian), Derred, Ganras, Ahgeathou, Krebraco (Anacondra) | trash, then Anacondra |
| 198 | Cave, Wailing Caverns | Alylienne 16 Balance druid (class) | Anneve 18 Ret paladin (class) | Nyflyllen 19 lock, Asvil 18 pal, Aurehun 18 shaman | wiped | Nyflyllen, Alylienne (Guardian), then Anacondra kills the rest | Anacondra plus Guardian |
| 199 | Cave, Deadmines | Goraraa 21 Ret paladin (class) | Auren 22 Enh shaman (class) | Aurevil 21 pal, Ceneelkarn 20 lock, Annestia 19 rogue | abandoned | Ceneelkarn, Aurevil (Defias Evoker, 4-mob face pull); Goraraa, Auren (Rhahk'Zor); nobody left to rez | Overseer pack, then Rhahk'Zor |
| 200 | Cave, Wailing Caverns | Astamara 19 Balance druid (class) | Beerix 18 Enh shaman (class) | Bakurn 18 mage, Fincizz 18 lock, Fugotik 18 lock | wiped | Fincizz (Guardian), Bakurn (Anacondra), Fugotik (Guardian), Astamara, Beerix | Anacondra plus Guardians |
| 203 | Cave, Deadmines | Goraraa 21 Ret paladin (class) | Auren 22 Enh shaman (class) | Aurevil, Ceneelkarn, Annestia | wiped | Annestia (Defias Miner), Ceneelkarn (Evoker), Goraraa (Miner), Aurevil (Overseer), Auren (Miner) | the mine, before Rhahk'Zor |
| 205 | Bonkers, Ragefire | Dakturm 17 Prot warrior (spec), il 13 | Ansalia 14 Holy priest (spec), 247 HP | Amony 18 lock, Whiona 18 rogue, Almun 17 rogue | wiped | Dakturm, Ansalia, Amony, Whiona, Almun (Ragefire Troggs) | trogg packs of 4 to 8 |
| 206 | Cave, Wailing Caverns | Krebraco 15 Prot warrior (spec) | Aeshontu 16 Ret paladin (class), il 3 | Derred mage, Fineklees lock, Nyflyllen lock | wiped | Fineklees, Derred, Nyflyllen (twice), Krebraco, Aeshontu (Deviate Ravagers), one at a time over 9 minutes | Ravager packs |
| 207 | Bonkers, Ragefire | Daidanden 16 Prot warrior (spec) | Azaedine 14 Holy priest (spec) | Carancan 18 lock, Eduin 18 lock, Elis 18 rogue | abandoned, 1/4 bosses | Carancan, Eduin, Eduin (Troggs), Azaedine (Oggleflint) | trogg packs, Oggleflint |
| 209 | Cave, Wailing Caverns | Astamara 19 Balance druid (class) | Ahgeathou 20 Ret paladin (class) | Anneve 19 pal, Ganras 19 shaman, Asvil 18 pal | inside, killed Anacondra | Astamara (Adder), Astamara (Druid of the Fang), Anneve (Adder), Asvil (Druid of the Fang) | trash past Anacondra |

Runs 193 and 196 (Bonkers, Ragefire) seated Velalenn, a Holy paladin, as tank; dungeon-clear logged "no tank in the party" and both runs were lost to expired claims.

## Causes, ranked

Counts are over the 12 runs that went in and logged dungeon-clear lines (190, 191, 192, 197, 198, 199, 200, 203, 205, 206, 207, 209) and their 236 pull decisions.

| Rank | Cause | Count | Component |
|---|---|---|---|
| 1 | No real healer: the seated healer plays damage (Enhancement or Retribution) | 9 of 9 Cave entries; healer mana read 100% at every pull in all 9 | wow-overseer `guildrun.py` seats `class` fit; mod-overseer finder-run sets no seat strategy |
| 2 | No real tank: the seated tank has no tank strategy | 7 of 9 Cave entries, plus Bonkers 193 and 196 | same |
| 3 | Boss engaged with the elites that wander beside it | 5 of 9 wipes or abandons end at a boss; Deviate Guardians killed in 4 of 5 Anacondra fights | mod-dungeon-clear at-boss path (`DcTargeting.cpp` vetoes the boss as a pull target and walks in) |
| 4 | Packs of 3 or more mobs pulled whole | 112 of 236 pull decisions; up to 8 troggs (run 205) | mod-dungeon-clear `DcPullPlanner.cpp`, `PullDynamicMaxLeeroyMobs = 5` |
| 5 | Pulling short of mana, with no drinks | 134 of 236 pulls with the rest gate NOT ready; casters pull at a 50% median; run 203 pulled at 0 to 12% | mod-dungeon-clear `DcRestFloorDecision.h` (`kNoDrinkDamageCap = 50`, `kBossDamageMana = 50`); bags hold no drinks |
| 6 | Tank or healer under the trash level, gear far below level | WC tanks at 15 and 16 against 18 to 20 elites (197, 198, 206); Ragefire healers at 14 (205, 207); worn item level 3 to 13 at death, median 6, mostly white | wow-overseer `guildrun.py` floors (`LEVEL_MARGIN = 0`, average only) |
| 7 | Wandering adds join a fight | Deadmines: 7 of 13 first contacts in each run joined a fight already on | mod-dungeon-clear pull planner (random movers in the mine) |

First deaths: 9 damage dealers (7 of them warlocks, at 309 to 363 max health), 3 tanks, 0 healers. A mob that kills a warlock first is a mob not on the tank.

### 1 and 2. Seats that nobody plays

`guildrun.compositions` sorts tanks and healers by fit, `spec` before `class`, and takes a `class` fit when nobody in the window has the spec. Cave has no spec healer above level 15 and no spec tank above 16 outside the families, so every Cave group at band 15 to 24 got class seats: Retribution paladins and Enhancement shamans as healers, Retribution paladins and Balance druids as tanks.

Playerbots decides tank and heal behaviour by strategy. `PlayerbotAI::IsTank(player)` returns `ContainsStrategy(STRATEGY_TYPE_TANK)` for a bot, and `IsHeal` returns `ContainsStrategy(STRATEGY_TYPE_HEAL)`. AiFactory gives a Retribution paladin and an Enhancement shaman damage strategies. Nothing in mod-overseer's finder-run changes them for the seat.

dungeon-clear shows the result twice:

- At the start: "dungeon clear enabled on map 43 ... (no tank in the party, so the group leader leads)" in runs 190, 192, 198, 199, 200, 203, 209.
- In every pull verdict: `DcPullPlanner` reads healer mana only from members where `IsHeal` is true and reports 100% when there is none. Cave runs read "healer 100% mana" at every one of their 145 pull decisions. Bonkers runs with Holy priests read real values (median 61 to 69%, as low as 0 to 2%).

So in Cave groups nobody casts heals on purpose, nobody taunts, and the readiness gate that should slow pulls when the healer is low cannot see a healer at all.

Bonkers seats spec tanks and healers (191, 205, 207) and made the only clear. Its two wipes came from causes 4 to 6, not from missing roles.

### 3. The boss comes with its neighbours

Lady Anacondra (level 20 elite, 5x health, 2.5x damage) stands with Deviate Guardians (18 to 19 elites, random movers) 8 and 20 yards from her spawn. dungeon-clear vetoes the boss as a pull target ("pull target vetoed: Lady Anacondra ... is a dungeon boss, at-boss path owns it") and the leader walks in. First contact came at 18 to 28 yards with no camp, and one or two Guardians joined within seconds ("blocking-trash: 2 candidate(s) in band -> Entry 3637 at 0.1yd"). Guardians made the first or second kill in runs 190, 197, 198 and 200.

Rhahk'Zor stands with two Defias Watchmen 9 and 10 yards away. Run 199 lost its tank and healer to him after two damage dealers died on the pack before.

Runs 192 and 209 did kill Anacondra, so she is beatable; she is the coin flip the group loses most.

### 4. Pull size

`PullDynamicMaxLeeroyMobs` is 5 elites. `FragilityScaledCeilingThirds` scales it by health per level against 40, so these groups (21 to 26 health per level) get a ceiling of 8 to 11 thirds: 2.7 to 3.7 elites face-pulled. A heavier pack is not refused; it becomes an ADVANCED pull, which drags the whole pack to a camp. Only a patrol makes the planner wait. The registry's own comment says "A human tank pulls two." 112 of 236 pull decisions estimated 3 or more mobs. Run 205 took Ragefire packs of 4, 5, 6 and 8 troggs (weights 12 to 24 thirds against a ceiling of 10 to 11) with the healer at 21 to 54% mana, and lost the tank first.

### 5. Mana and drinks

No seated healer and no tank carried a drink. Of 42 members, only 4 mages (conjured water) and 1 rogue held food or drink. `DcRestFloorDecision` caps the wait for a member with no drink at 50% mana (`kNoDrinkDamageCap`), and boss floors for tanks and damage dealers are 50% (`kBossDamageMana`). The pull logs show the plateau: the lowest caster sat at 50 to 56% at most pulls, and the rest gate read NOT ready at 134 of 236 pulls. Run 203 pulled the Deadmines mine with the lowest caster at 0 to 12% and wiped there. A human group drinks to full before every pull at this level, and to full before a boss.

### 6. Level and gear

`fitting_doors` checks the finder minimum for every member and the door floor for the average (Wailing Caverns 17, Deadmines 17, Ragefire 15), with `LEVEL_MARGIN = 0`. That let a level 15 tank (Krebraco) and a level 16 healer (Aeshontu, item level 3) into Wailing Caverns, where every trash mob is an 18 to 19 elite and the first boss is 20. Ragefire took 14-level Holy priests with 247 to 267 health. Worn gear at death averaged item level 3 to 13 (median 6), mostly white quality; a player at 18 to 20 usually wears quest greens.

### 7. Wandering adds

The Deadmines mine is full of random-moving Defias Miners. In runs 199 and 203, 7 of 13 first contacts were a mob joining a fight already on ("party already fighting: 2 to 3"), so pulls planned at 1 to 2 mobs became 4 to 5.

## Recommended changes

In order of expected effect. Each keeps to human-like play: no granted levels, gear or items.

1. **Seat only members who play the seat** (wow-overseer `guildrun.py`, mod-overseer finder-run). Either:
   - require a `spec` fit for the healer, and fill the seat with a helper from above the band ([#521](https://github.com/quadseven/wow-overseer/issues/521) allows two, up to 10 levels up) when the band has none, or hold the group; or
   - when a `class` fit takes the seat, switch that bot to the seat's strategy for the run (`+heal` for a Retribution paladin or Enhancement shaman, `+tank` with Righteous Fury or Bear Form), the way a player says "I'll heal this one", and restore it at the end. Verify with the "no tank in the party" line and a non-100% healer reading.
2. **Make dungeon-clear see the seats** (mod-dungeon-clear `DcPullPlanner.cpp`, `DungeonClearChatActions.cpp`). When no member passes `IsHeal`, read the seated healer's mana, or the lowest mana user, instead of 100%; refuse a boss engage with no heal-strategy member alive.
3. **Clear the boss's neighbours first, then pull the boss to a camp** (mod-dungeon-clear at-boss path). Before engaging, pull every elite within the boss's aggro reach plus assist radius (Anacondra's Guardians, Rhahk'Zor's Watchmen) as ordinary trash, then pull the boss back to the cleared camp.
4. **Smaller pulls at low level** (mod-dungeon-clear pull planner and conf). Lower `PullDynamicMaxLeeroyMobs` toward 2 below level 30, scale the ceiling by worn item level per level as well as health, and when a pack is over the ceiling, wait for it to split, line-of-sight pull, or skip it, instead of dragging the whole pack. A human pulls one or two elites at 18.
5. **Drink before pulls** (mod-overseer town errand before a guild run, mod-dungeon-clear rest floors). Members buy water and food at a vendor with their own money before they queue, mages hand out conjured water, and the rest floor waits to about 90% for the healer and to full before a boss (`kBossDamageMana`, `kNoDrinkDamageCap` apply only when nobody has a drink).
6. **Level floor per seat and per door** (wow-overseer `guildrun.py` `fitting_doors`). Keep `LEVEL_MARGIN = 0` for damage dealers, as the operator chose, but hold the tank and healer to the trash level minus 1 (Wailing Caverns 17, Deadmines 16, Ragefire 13) and the average to the first boss's level minus 1 (Anacondra 19, Rhahk'Zor 18). Door choice by band then follows the existing rate table.
7. **Measure the next round** (deploy and data). Roll the worldserver so [mod-overseer#839](https://github.com/quadseven/mod-overseer/pull/839) writes guild deaths to `overseer_death`; extend the meter probe to guild runs so healing done per run is stored; fix the claim expiry that lost 4 of 22 runs (including 192, which had just killed Anacondra), since lost runs teach the rate table nothing.

Changes 1 and 2 alone address the cause present in every Cave wipe. Changes 3 to 5 address what killed Bonkers' spec-seated groups too.
