# Molten Core encounters: what the core scripts and bot strategies do for a bot raid today

Research for [wo#519](https://github.com/quadseven/wow-overseer/issues/519), workstream G of [wo#512](https://github.com/quadseven/wow-overseer/issues/512). Read 2026-10-04. Source code only; nothing here was observed on the live realm.

## Sources and pinned commits

| Component | Repo and commit | What was read |
|---|---|---|
| Core scripts | [mod-playerbots/azerothcore-wotlk `Playerbot` @ f19a1879][ac] | `MoltenCore/boss_*.cpp`, `instance_molten_core.cpp`, `molten_core.cpp`, `molten_core.h`; `data/sql/base/db_world/smart_scripts.sql` for trash and adds without C++ AI |
| Bot fight strategy | [quadseven/mod-playerbots @ 7bae1b5c][pbf] and [mod-playerbots/mod-playerbots @ 037c0141][pbu] | `src/Ai/Raid/MC/*`, `BossAuraTriggers.cpp`, `BossAuraActions.cpp`, class strategies, `PlayerbotAI::ApplyInstanceStrategies` |
| Between-fight brain | [quadseven/mod-dungeon-clear @ 427e7007][dc] (branch `fix/rez-needs-mana-on-pin`) | `Data/Events/MoltenCoreEvents.cpp`, `DcRunState.h`, `Util/DcBossStandDown.h`, `Util/DcRaidMusterDecision.h`, `DcStrategyGate.cpp` |
| Raid runner | [quadseven/mod-overseer @ ec7645a4][mo] | `src/overseer_decisions.h` (RaidRunPhase, StepRaidRun, RaidClearStallDecision, loot council), `src/mod_overseer.cpp` (MarkRaidMainTank, ApplyRaidFightStrategy) |
| Plan | [wo#269](https://github.com/quadseven/wow-overseer/issues/269), `raidsupply.py` in this repo | MC night plan, fire resistance targets |

The fork and upstream MC strategy are identical except one TODO comment (`diff -r src/Ai/Raid/MC`): the fork's Magmadar TODO still lists fear ward, upstream's lists only tremor totem. Everything below about `src/Ai/Raid/MC` holds for both.

[ac]: https://github.com/mod-playerbots/azerothcore-wotlk/tree/f19a18799a35f7c24bdcdc9ea399c601f166259b/src/server/scripts/EasternKingdoms/BlackrockMountain/MoltenCore
[pbf]: https://github.com/quadseven/mod-playerbots/tree/7bae1b5c58c76a0aa20381155edc08096d1485b2/src/Ai/Raid/MC
[pbu]: https://github.com/mod-playerbots/mod-playerbots/tree/037c01418b5d01506917a3db9b44fd56ac5f965c/src/Ai/Raid/MC
[dc]: https://github.com/quadseven/mod-dungeon-clear/blob/427e70073e979a0771d61c67d388a7dca42f2415/src/Ai/Dungeon/DungeonClear/Data/Events/MoltenCoreEvents.cpp
[mo]: https://github.com/quadseven/mod-overseer/blob/ec7645a41bf263e4c674b7d91147a8466c62c50d/src/overseer_decisions.h

## Who owns what during a raid

- **mod-overseer** forms the 40, walks it in through areatrigger 3529, and runs the phases Form, Assemble, Enter, Hold, Clear, Recover (`RaidRunPhase`). In Hold it sets the head as main tank (`MarkRaidMainTank`, `MEMBER_FLAG_MAINTANK`) and checks every member carries the `moltencore` strategy (`ApplyRaidFightStrategy`). In Clear it arms dungeon-clear. A stall gets two regroups, then one `dc skip`; a wipe (90 percent dead) is Recover: release, run back, walk in. Raid loot is master loot with the leader as looter and the loot council naming the recipient (`LootRulesFor`, `LootCouncilHeuristic`).
- **mod-dungeon-clear** owns everything between pulls on a raid map (`raidRun`). Before each boss a strict muster (`DcRaidMusterDecision`) stages the raid, tops it to full and runs a rebuff round, each phase timeout-bounded. During an encounter it stands down completely (`DcBossStandDown`: entered when `IsEncounterInProgress()` or a roster boss holds a member in combat, exited after 3 s of quiet). On raid maps it also installs playerbots' `worldbuff` strategy as the consumable stand-in (`DcStrategyGate.cpp`).
- **mod-playerbots** owns the fight. `PlayerbotAI::ApplyInstanceStrategies` installs `moltencore` on map 409 (`PlayerbotAI.cpp`, `case 409`). Generic class behavior (dispels, interrupts, `avoid aoe`, fear ward) runs underneath it.
- **The core** runs the encounters. Runes are doused by the instance script itself when each rune boss dies (`SetBossState` calls `UseDoorOrButton` on the rune), so no Aqual Quintessence is needed. Majordomo is summoned once bosses 1 to 8 except Lucifron are DONE (`CheckMajordomoExecutus` skips `DATA_LUCIFRON`).

## What the MC strategy contains

`RaidMcStrategy::InitTriggers` ([MCStrategy.cpp][pbu]):

- A paladin aura swap per boss: shadow resistance aura on Lucifron, Gehennas and Majordomo; fire resistance aura on the other seven. Only paladins act (`BossFireResistanceTrigger::IsActive` returns false for any other class). No shaman totem, no other class.
- Baron Geddon: Living Bomb holder runs 20 yd from the group; everyone runs 20 yd from Geddon while Inferno is up; a multiplier blocks every other movement and reach action meanwhile.
- Shazzrah: ranged bots inside 26 yd move out to 26 yd (Arcane Explosion radius).
- Golemagg: skull on the boss; main tank drags Golemagg to a fixed spot; the first two assist tanks each hold one Core Rager at a second spot 56 yd away so Golemagg's Trust drops; healers stand at the midpoint; non-tanks back off at 20 Magma Splash stacks until the stack expires; ranged never melee; DPS AoE off; below 10 percent all of that releases for the burn.
- Garr: a multiplier zeroes every DPS AoE action while Garr lives.
- Core Hound packs: the main tank keeps skull on the highest-health hound (10 percent hysteresis), which spreads damage so the pack dies together.
- Anywhere: a bot standing or swimming in magma runs to the nearest dry raid member (`mc in lava`, priority ACTION_RAID + 1).
- Target exclusions: Majordomo himself, and the Core Ragers while Golemagg lives, are removed from DPS target lists.

Nothing in the strategy names Lucifron's adds, Magmadar's fear, Gehennas, Sulfuron's priests, Majordomo's adds, Ragnaros, or the Sons of Flame. Upstream's own TODO on Magmadar says so: "tremor totem, or general anti-fear strat development".

## Per boss

"Generic" means class-level playerbots behavior that runs everywhere, not MC-specific. "Live-unverified" applies to every row: none of this has run as a 40-player bot raid on our realm.

### Lucifron

- **Mechanics (core):** Impending Doom (magic debuff, 20 s), Lucifron's Curse (curse, 20 s), Shadow Shock on the victim every 5 s. Two Flamewaker Protectors (12119, SmartAI) cast Dominate Mind and Cleave.
- **Handled:** paladin shadow resistance aura (MC strategy). Curses: mage and druid `remove curse on party` (generic). Magic: priest `dispel magic on party`, paladin `cleanse` (generic). The dispel target search walks the whole raid, own subgroup first (`PartyMemberValue::FindPartyMember`).
- **Gap:** Dominate Mind. Nothing makes the raid stop hitting, or crowd-control, a mind-controlled raider, and nothing dispels it on purpose. Not required for Majordomo, so the run can also order it after the others; DC clears it in roster order today.

### Magmadar

- **Mechanics:** Panic (fear, 31 to 38 s), Frenzy (enrage, 15 to 20 s), Lava Bomb under a random melee and a random ranged target (spawns a burning GameObject trap for 30 or 60 s).
- **Handled:** paladin fire resistance aura (MC). Frenzy: hunter `tranquilizing shot enrage` (generic, priority 61). Fear ward on the main tank by priests (generic `fear ward on main tank`; Alliance dwarf priests only). Lava Bomb traps: generic `avoid aoe` (`AvoidGameObjectWithDamage`), on by default (`AiPlayerbot.AutoAvoidAoe = 1`).
- **Gap:** the fear itself. No tremor totem placement, no fear immunity for anyone but the main tank, no repositioning after fear. DC's own header lists "Magmadar fear chaos" as an accepted v1 loss. Feared bots running into trash or lava is the main wipe risk here.

### Gehennas

- **Mechanics:** Gehennas' Curse (curse, -75 percent healing, 25 to 30 s), Rain of Fire on a random target every 6 s, Shadow Bolts. Two Flamewakers (11661, SmartAI): Strike, Fist of Ragnaros, Sunder Armor.
- **Handled:** paladin shadow resistance aura (MC). Curse: generic decurse. Rain of Fire: generic `avoid aoe` (dynamic object).
- **Gap:** none specific. Add-first kill order is not set; bots pick targets with stock logic.

### Garr

- **Mechanics:** Garr plus 8 Firesworn (12099). Each Firesworn erupts when it dies (fire AoE plus knockback) and gives Garr a Frenzy stack. Antimagic Pulse strips a buff every 20 s, Magma Shackles slows. Firesworn more than 40 yd from Garr gain +300 percent damage and banish immunity (Separation Anxiety). After 10 minutes Garr detonates one Firesworn every 20 s.
- **Handled:** paladin fire resistance aura and DPS AoE disabled while Garr lives (MC).
- **Gap:** add control. No tank or banish assignment for eight adds, no kill order, nothing keeping adds within 40 yd of Garr, no spread so eruptions do not chain into melee. With the stock target logic, bots will spread damage over whatever attacks them. A raid without eight-plus holders relies on raw healing until the 10-minute timer.

### Baron Geddon

- **Mechanics:** Inferno (10 s pulsing AoE, damage rising to 5000 a tick), Ignite Mana (magic debuff burning mana), Living Bomb (a random target becomes a bomb that explodes on the raid when it expires), Armageddon at 2 percent (boss invulnerable, then dies).
- **Handled:** paladin fire resistance aura, Living Bomb run-out, Inferno run-out, movement lock-out while either is active (MC). Ignite Mana: generic magic dispel.
- **Gap:** small. The bomb holder runs 20 yd from "the group" but nothing makes healers follow, and nothing stops a Living Bomb runner landing in another pack. This is the best-covered fight after Golemagg.

### Shazzrah

- **Mechanics:** Arcane Explosion every 4 to 5 s around him, Shazzrah's Curse (curse, random target), Magic Grounding (self buff), AoE Counterspell, Gate of Shazzrah every 45 s (teleports to a random non-melee player, wipes threat, Arcane Explosion there).
- **Handled:** ranged stay outside 26 yd (MC). Curse: generic decurse. Magic Grounding: shaman `purge` (generic, Horde/draenei only).
- **Gap:** the blink. After Gate he stands among the ranged with no threat; nothing tells the tanks to taunt him back or the ranged to step out quickly beyond the per-tick move. No paladin aura row for him (he is arcane, so none applies).

### Sulfuron Harbinger

- **Mechanics:** Sulfuron casts Demoralizing Shout, Inspire (on himself and a priest), Knockdown on the victim, Flamespear on a random target. Four Flamewaker Priests (11662) cast Dark Mending (heals the lowest friendly), Shadow Word: Pain, Immolate, Dark Strike.
- **Handled:** paladin fire resistance aura (MC). SW:P and Immolate: generic magic dispel.
- **Gap:** kill order and interrupts. Classic kills the priests first and interrupts Dark Mending; nothing marks the priests or assigns interrupters. Generic interrupt triggers may catch some casts.

### Golemagg the Incinerator

- **Mechanics:** Magma Splash stacking on melee, Pyroblast on a random target every 7 s, two Core Ragers that full-heal at 50 percent while he lives and gain Golemagg's Trust near him, Earthquake every 5 s and Rager convergence below 10 percent. A Core Rager more than 100 yd from Golemagg resets the encounter.
- **Handled:** fully scripted (MC): tank spots, Rager split, healer midpoint, splash back-off, burn phase, target exclusion on Ragers.
- **Gap:** role supply. The plan needs at least three tank-spec raiders (main plus two assist tanks; `IsAssistTankOfIndex`). Assist tanks are "any tank-spec bot that is not the main tank", ordered by group position, so the lineup must seat them. With one tank the multiplier makes it tank all three.

### Majordomo Executus

- **Mechanics:** Majordomo cannot die; the encounter ends when his 8 adds die (4 Flamewaker Healers 11663: Shadow Shock, Shadow Bolt; 4 Flamewaker Elites 11664: Fireball, Blast Wave, Fire Blast). Magic Reflection or Damage Reflection every 30 s. Teleport of his victim and of a random target, each with a full threat reset. Encouragement on each add death, polymorph immunity at 4 left, Champion on the last. Adds more than 40 yd from him gain Separation Anxiety. On victory he turns friendly and teleports to Ragnaros's chamber.
- **Handled:** Majordomo is excluded from DPS targets (MC). Paladin shadow resistance aura (MC). Completion is read from boss-state slot 8, not a corpse, by DC (`MoltenCoreEvents.cpp`, `MakeBoss(... kSlotMajordomo)`). A teleported tank who lands in magma escapes via `mc in lava`.
- **Gap:** the reflection shields (casters and melee keep hitting through Magic or Damage Reflection), the threat resets after each teleport, add kill order and crowd control, and keeping adds within 40 yd.

### Ragnaros

- **Summon (dialogue):** Ragnaros only appears when someone gossips the friendly Majordomo (menu 4108) in his chamber. A scripted RP of about 48 s follows, then Ragnaros zone-pulls the raid himself (`DoZoneInCombat`). **Handled by DC:** the "Summon Ragnaros" objective dwells 5 s, gossips Majordomo (option 0), and waits up to 120 s for a live Ragnaros; the Ragnaros boss anchor follows (`MoltenCoreEvents.cpp`). The author marks it "not yet validated live". Ragnaros despawns 2 hours after summon if out of combat (`TEMPSUMMON_TIMED_DESPAWN_OUT_OF_COMBAT`).
- **Mechanics:** he is rooted. Wrath of Ragnaros (knockback around his victim, 25 s), Hand of Ragnaros (spell 19780, self-cast every 20 s), Might of Ragnaros on a random mana user, Lava Burst GameObjects (three random eruptions every 10 s), Magma Blast on his victim every 4 s when nobody is in melee range. At 180 s he submerges: untargetable, threat reset, 8 Sons of Flame (12143) zone in. He emerges after 90 s or when all Sons die, attacks a random target, and the 180 s timer restarts.
- **Handled:** paladin fire resistance aura (MC). Magma escape after a knockback (`mc in lava`). Lava Burst GameObjects: generic `avoid aoe`, if the burst trap counts as a damaging GameObject. Sons of Flame are ordinary attackers once zoned in. DC's stand-down holds through the submerge because the boss state stays IN_PROGRESS.
- **Gap:** melee placement (no rule keeps melee in front at a wall or spread to cut knockback distance), main tank pick-up and taunt after emerge (he attacks a random target with a fresh threat table), kill order and positioning for 8 Sons, and healer spread. DC's header lists "Ragnaros knockback/submerge inefficiency" as an accepted v1 loss.

## Trash

| Pack | Mechanic (core) | Handled | Gap |
|---|---|---|---|
| Core Hound packs (11671) | A hound at 0 hp plays dead 10 s, then revives at full if any other hound within 80 yd and in LOS is alive and fighting (`spell_mc_play_dead_aura`). Serrated Bite. | MC strategy: skull on the highest-health hound, so damage evens out and the pack dies together. | None specific; cleave and AoE classes are stock. |
| Ancient Core Hounds (11673) | Lava Breath, Vicious Bite, a random debuff script. | Stock combat. | No facing rule for the breath. |
| Lava Surgers (12101) | Surge: charge with knockback. | Stock combat. | Nothing. Wandering surgers can chain-pull. |
| Firelords (11668) | Soul Burn; Summon Lava Spawn. Each Lava Spawn splits in two every 15 s while fewer than 16 exist (`npc_lava_spawn`). | Stock combat. | Kill-priority on Lava Spawns. Left alone they multiply to 16. |
| Molten Giants and Destroyers (11658, 11659) | Smash, Knock Away; Knockdown, Massive Tremor. | Stock combat; `mc in lava` after knockback. | None specific. |
| Flamewaker trash (11666 Firewalker, 11667 Flameguard) | Incite Flames, Fire Blossom; Cone of Fire, Melt Armor. | Stock combat; `avoid aoe`. | None specific. |

## Cross-cutting

### Decurse and dispel assignment

There is none. Every mage and druid runs `remove curse on party` (priority 40 to 57), every priest `dispel magic on party`, every paladin `cleanse`, every shaman `purge` on enemies. Each picks the first raid member needing it, own subgroup first, then the rest of the raid. So coverage is raid-wide, but casters race each other for the same target, burn mana on duplicates, and nothing ranks Lucifron's Impending Doom over a Shadow Word: Pain. For 40 bots this probably works by volume; it is the first place a mana-starved healer pool will show.

### Fire resistance

- In-fight: only the paladin aura, swapped per boss by the MC strategy. Shaman fire resistance totem exists (`set fire resistance totem`) but only in the opt-in totem strategy; the MC strategy never asks for it.
- Gear: `raidsupply.py` targets 200 for the main tank, 120 for other tanks, 60 for healers. Live on 2026-09-23 the 40 placed raiders held 10 fire resistance in total, on one raider ([wo#269](https://github.com/quadseven/wow-overseer/issues/269)).
- Consumables: DC installs playerbots' `worldbuff` on raid maps. Its level 60 rows in the shipped `playerbots.conf.dist` apply simulated flask and food auras (17626, 17627, 17628, 17538 and food buffs); none is a fire protection potion. These are granted auras, which sits badly with the "natural progression only" rule in [wo#512](https://github.com/quadseven/wow-overseer/issues/512); the deployed conf was not read here.

### Knockback positioning

The only knockback rule is the lava escape. No raid strategy places tanks or melee against a wall for Wrath of Ragnaros, Garr's eruptions, Molten Giants or Lava Surgers.

### Majordomo dialogue to summon Ragnaros

Handled in DC code (see Ragnaros), unvalidated live. A re-entered instance with Ragnaros already summoned skips the gossip (`skipIfMissing`).

## What a one-shot still needs, in order of risk

1. **Magmadar fear.** Tremor totem or a fear plan beyond the main tank's fear ward; recovery from feared bots.
2. **Ragnaros.** Melee placement, re-taunt after emerge, Sons of Flame handling, healer spread.
3. **Garr's eight Firesworn.** Holders or banish, kill order, keep within 40 yd of Garr.
4. **Majordomo.** Stop casting into Magic Reflection and swinging into Damage Reflection, re-taunt after teleports, add kill order.
5. **Fire resistance supply.** Gear and potions; the paladin aura alone is far short of the classic targets.
6. **Lineup roles.** At least three tank-spec raiders for Golemagg, paladins in every group for aura coverage, hunters for Tranquilizing Shot, dwarf priests for fear ward.
7. **Lucifron's Dominate Mind, Sulfuron's priests, Shazzrah's blink, Firelord Lava Spawn priority.** Smaller, each a kill-order or target rule.
8. **Live validation.** No part of the MC chain (overseer Clear, DC roster and muster, the Ragnaros gossip, the MC strategy) has run on our realm.

## Summary

The core scripts work without player-side props (runes douse themselves, Majordomo spawns on his own, Ragnaros is summoned by one gossip). The bot side covers Golemagg fully, Baron Geddon well, Core Hounds and Shazzrah's ranged spacing, and gives paladins the right resistance aura on every boss. Dungeon-clear handles between-pull staging, the Majordomo completion and the Ragnaros summon in code. Nothing handles Magmadar's fear, Garr's adds, Majordomo's reflection and teleports, or Ragnaros's knockback, submerge and Sons, and fire resistance is ten points across the raid; a one-shot today is not possible.
