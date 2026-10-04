# Idle leveling: why half of each guild earns no XP

Research for [wo#531](https://github.com/quadseven/wow-overseer/issues/531), workstream E of [wo#512](https://github.com/quadseven/wow-overseer/issues/512), following [wo#517](https://github.com/quadseven/wow-overseer/issues/517) ([research/leveling-throughput.md](https://github.com/quadseven/wow-overseer/blob/research/leveling-throughput/research/leveling-throughput.md)). Measured on wow-dev 2026-10-04 between 19:44 and 20:14 UTC (15:44 to 16:14 ET). Read-only: no row was written to the realm.

## Answer in brief

In a 30 minute window, 105 of the 132 non-family members of Cave and Bonkers earned no XP. Half of those idle members (50) are stuck by one mod-overseer bug. A hold that mod-overseer places on a guild member after a spirit-healer resurrection adds `stay` and removes `new rpg`. When a second hold overlaps it, nobody gives `new rpg` back. The member then stands where it revived until the next worldserver restart. 52 members carried this leaked hold at the start of the window. One of them earned XP (7 XP per hour on average), and 44 of them did not move 10 yards. The other 80 members averaged 617 XP per hour.

The leak started with mod-overseer [#783](https://github.com/quadseven/mod-overseer/pull/783) (2026-09-28), which made every guild member rest out its Resurrection Sickness under a hold. It fires on every spirit-healer revival of a guild member. 52 of 132 members were caught within 36 minutes of the 19:08 restart. Restarts (11 a day) are the only thing that clears it, which is why the [wo#517](https://github.com/quadseven/wow-overseer/issues/517) sample just after a restart found "only" half idle.

The one change: when the post-revival hold ends while another hold is in force, mod-overseer should hand that hold its debt (`stay` added, `new rpg` removed) instead of dropping it. On this sample, that change would return 50 of the 105 idle members to questing. The next causes are much smaller: 21 in zones far off their level, 13 on guild job errands, and 9 in death loops.

## Method

| Source | What was read |
|---|---|
| `acore_characters.overseer_snapshot` | Live map, zone, position, health, combat, group, online. All rows fresh within 5 s of each sample |
| `characters` | Saved `xp`, `level`, `money`, `online` at 19:44:15, 19:59:21 and 20:14:31 |
| `character_queststatus`, `character_queststatus_rewarded` | Quests in the log (status 1 complete, 3 incomplete), rewards |
| `character_inventory`, `item_instance`, `acore_world.item_template` | Backpack slots used, bag slots worn and used |
| `corpse` | Dead members |
| `overseer_command` | Every row targeting a guild member from 19:00 to 20:15, including all `guildjobs:*` rows |
| `acore_playerbots.playerbots_account_type`, `playerbots_random_bots` | Account type and random-bot rows for every member |
| `acore_world.quest_template` | Average quest level per zone (`QuestSortID`) |
| Worldserver log, `module.overseer`, 19:08 restart to 20:14 | Every hold, release, revival, death and ghost recovery naming a member |
| mod-overseer at main `ec7645a` | `src/mod_overseer.cpp`, `src/overseer_decisions.cpp` |
| wow-overseer at main `b1b7626` | `guildjobs.py`, `zones.json` |
| mod-playerbots at the pinned `7a593fa` | `RandomPlayerbotMgr.cpp`, `PlayerbotAI.cpp` (where strategies are reset) |
| Mounted `playerbots.overrides.conf` | Random-bot settings |

Leveling versus idle is split on saved XP between the first and third samples (30 minutes, two player-save intervals). A member is idle when it gained no XP. The families (Grug, Grog, Ugga, Bork, Og; Zug, Uzza, Oz, Zrog, Zork) are left out.

The playerbots strategy set of a member is not in any table, and reading it needs a `probe strategies` row, which is a write. Strategy state was therefore read from mod-overseer's own log lines. Each hold and release line reports what `HasStrategy` returned for `stay`, `follow` and `new rpg` at that moment.

All 132 members are on random-bot accounts (`account_type` 1) and have random-bot rows. Account type does not split them.

## 1. Leveling and idle

| | Members | Earned XP | Mean XP/h | Moved under 10 yd |
|---|---|---|---|---|
| Cave | 66 | 12 | 295 | 35 |
| Bonkers | 66 | 15 | 458 | 36 |
| Leaked hold at 19:44 | 52 | 1 | 7 | 44 |
| No leaked hold | 80 | 26 | 617 | 27 |
| All | 132 | 27 | 377 | 71 |

The 27 earning members averaged 1,841 XP per hour. No member in either set was grouped.

## 2. Idle members by cause

Each idle member is placed in the first cause that fits, in this order.

| # | Cause | Idle members | Notes |
|---|---|---|---|
| A | Leaked hold: `stay` on, `new rpg` off | 50 | 43 stood still all 30 minutes; 37 stand in a zone that fits their level |
| B | Death loop or dead | 9 | 9 to 19 deaths each since 19:08; 6 dead in a sample |
| C | On a guild job step in the window | 13 | 10 gear walks, 2 hearths, 1 post walk |
| D | Zone far off its level (over 5 levels), no other cause | 21 | 8 above (Searing Gorge, Eastern Plaguelands, Wetlands), 13 below (Eversong Woods, Elwynn, Tirisfal); 11 stood still |
| E | Still, zone fits, no hold logged | 9 | Includes Aalall (level 59 death knight) |
| F | Moving, zone fits, no XP | 1 | Fineklees |
| G | Offline | 2 | |
| | Total | 105 | |

Other readings across the 105 idle members:

- Bags: 34 had one free slot or none, against 9 of the 27 earning members. Full bags do not separate the two sets.
- Quest log: idle members carry 15 to 21 quests on average, under the 25 cap. 129 members hold at least one completed quest not yet turned in, 295 in all.
- Money: idle members average 4 to 47 silver by cause. No cause is explained by money.
- Guild jobs: 44 members had a `guildjobs:*` row between 19:00 and 20:15, and 13 of those 44 earned XP (30%, against 20% overall). Guild jobs do not hold members away from questing at scale.

## 3. Cause A: the leaked revival hold

### What the log shows

Every leaked member shows the same four lines. Beerix, level 18, in Bloodmyst Isle:

```
19:15:15 'Beerix' took the spirit healer's resurrection ... resurrection sickness and durability loss included
19:15:15 'Beerix' is held where it revives for 20s (`+stay`, `-new rpg`) before anything moves it again
19:15:23 'Beerix' is held still to revived sickness for at most 690s (stay already on, follow was off, new rpg was off, ...)
19:15:39 'Beerix' is out of its post-revival hold but a casting verb is holding it still - the mover stays off and the cast hold hands it back
19:23:15 'Beerix' is released from its revived sickness hold - Resurrection Sickness ended (stay left alone, follow not touched, new rpg not touched)
```

After 19:23 Beerix carries `stay` and no `new rpg`, and nothing in mod-overseer gives them back.

Counts from the log, 19:08 to 20:14:

| Line | Count |
|---|---|
| Spirit-healer resurrections of guild members | 90 |
| Revival hold deferred to another hold ("a casting verb is holding it still") | 68 |
| Revival hold released cleanly | 13 |
| Releases that restored nothing ("stay left alone ... new rpg not touched") | 97 |
| of which the `revived sickness` hold | 64 |
| of which `mailwalk`, `cast` and `hearth` holds | 33 |
| Later holds that read `stay` on and `new rpg` off on a member before holding it | 18 members |

Leaks accumulate after a restart: 18 members leaked between 19:10 and 19:20, 39 by 19:30, 48 by 19:40, and 52 by 19:44.

### Why it happens in the code

All references are mod-overseer main `ec7645a`, `src/mod_overseer.cpp` unless named.

1. `DriveGuildGhostRecovery` (line 27904) sends a guild member's ghost to the spirit healer ([#772](https://github.com/quadseven/mod-overseer/pull/772), 2026-09-27). The revival calls `HoldAfterRevival` (line 27488): `+stay`, and `-new rpg` when the member had it. It records the debt in `_revivalHoldUntil` for 20 seconds (`REVIVAL_HOLD_SECONDS`, line 734).
2. On every poll of a living guild member, `DriveGuildGhostRecovery` calls `ReleaseRevivalHold` and then `DriveRevivedSickness(..., restWhileSick = true)` (lines 27940 to 27942, from [#783](https://github.com/quadseven/mod-overseer/pull/783), 2026-09-28).
3. `DecideRevivedSickGround` (`src/overseer_decisions.cpp` line 7149) answers `HoldOutOfCombat` for any sick guild member on non-lethal ground. So `DriveRevivedSickness` places the `revived sickness` hold through `HoldCharacterStill` (line 8877) on the first living poll, inside the 20 second revival hold. `HoldCharacterStill` reads the strategies as they are now: `stay` already on and `new rpg` already off. So its record owes nothing back.
4. When the 20 seconds end, `ReleaseRevivalHold` (line 27518) finds `HeldStill(name)` true (line 27538). It erases its own record and returns, trusting that "the cast hold hands it back". The cast hold never took `new rpg`, so it has nothing to hand back.
5. When the sickness ends, `ReleaseHold` (line 9187) undoes only what its own record says: nothing. The member keeps `stay` and lacks `new rpg`.

Nothing else restores it. mod-playerbots resets a random bot's strategies only on a relog, a master or group change, or when the random-bot manager itself revives a dead bot (`RandomPlayerbotMgr.cpp` lines 2159 to 2170 and 2626, `PlayerbotAI.cpp` line 436, at pin `7a593fa`). mod-overseer revives guild members before the manager does. The guilds are always online (`AlwaysOnlineGuild = "Cave,Bonkers"`), so no periodic logout clears it either. A worldserver restart does.

The same deferral trap is written into `ReleaseRevivalHold`'s comment as a known case ("a revival hold is 20 seconds and a cast hold is 45"). For the family it is rare, because the family's revived-sickness rule only holds on lethal ground. #783 made it the normal path for every guild member.

## 4. The smaller causes

B. Death loops (9). These members died 9 to 19 times since 19:08, mostly in zones 14 to 34 levels above them (Badlands, Searing Gorge, Duskwood, Dun Morogh at level 2). Guild members died 448 times in the 66 minutes after the restart, 85 members in all, about 4.8 deaths per dying member per hour. Each spirit-healer revival is also a fresh chance for cause A.

C. Guild job steps (13). Ten were on gear walks (`guildjobs:gear`) and two had hearthed home after a failed gear walk (`hearth_step` in `guildjobs.py`). A hearth puts a member at its inn, usually in its starting zone. Five of the cause D members below their level had hearthed in the last 75 minutes. A trainer walk also repeats: Bacden walked to a trainer 17 times and Auren 13 times since the restart ("can afford N class spell(s) and walks ... to trainer"), without the learn ending the loop.

D. Wrong zone (21). Members are random bots with `AutoTeleportForLevel = 1`. No wow-overseer code routes a guild member to a quest hub (`levelroute.py` routes the families only). Eleven of the 21 stood still, so some may carry a hold this read could not see. Their logs since the restart name no hold.

E. Still with nothing logged (9). No hold, death or guild job names them since the restart. Their strategy state needs a `probe strategies` read to explain.

## Recommended change

Fix the hand-back in mod-overseer, in one place. When `ReleaseRevivalHold` defers because `HeldStill(name)` is true, it should move its debt onto the standing hold's register record: set `addedStay` and, when the member led (`led`), `removedNewRpg` on `HoldsInForce()[name]`. That hold's own `ReleaseHold` then removes `stay` and restores `new rpg` when it lifts. A test in the module's decisions suite can drive revival hold, then sickness hold, then both releases, and assert `new rpg` is back.

On this sample the change returns 50 of 105 idle members to questing (cause A). At the 617 XP per hour the unleaked members earn, it roughly doubles the guilds' total XP rate (377 to about 600 XP per member per hour). It needs no restart schedule and no change in wow-overseer.

Until that ships, a worldserver restart clears every leaked member, and the leak refills within about 40 minutes.

## Open questions

- Members in cause E and the 11 still members in cause D need a `probe strategies` read (a write to `overseer_command`, so out of scope here) to show whether they hold `stay` from a path this log did not name.
- Whether `revived sickness` should hold a guild member at all on safe ground. Upstream bots fight on through sickness. The hold costs up to 11.5 minutes of play per death, at about 4.8 deaths per dying member per hour.

## Appendix: idle members by cause

- A, leaked hold (50): Achevar, Actehuurn, Aehuurn, Alestheon, Almun, Alylienne, Ameth, Annestia, Ansalia, Aradak, Ariaad, Arianah, Astamara, Astitan, Atkermi, Aurehun, Auremir, Aurerim, Baall, Barem, Bazeite, Bazmoth, Beerix, Belaney, Belethos, Bezki, Biannise, Bramitho, Cigtek, Cokderl, Daidanden, Danderollo, Doriana, Duir, Dumdith, Dutlan, Eduin, Elis, Farrin, Fincizz, Flanu, Ganras, Gleenkick, Gonka, Grerarm, Helindy, Lengie, Loeron, Tynneda, Xohjaz
- B, death loop (9): Alindy, Arehr, Baleron, Blandorion, Bytkiz, Caelianon, Eveline, Nangri, Viwece
- C, guild job step (13): Ahgeathou, Amony, Anneve, Aristina, Avenah, Azarise, Bacden, Baldam, Balressian, Cario, Ginny, Nomarrin, Nyflyllen
- D, zone far off level (21): Adalok, Aellen, Allenn, Amilyn, Annian, Auren, Aylysae, Azaedine, Cesca, Dalene, Eazoth, Feyda, Fugotik, Fuxek, Hebus, Hellengi, Inhen, Quelmin, Selie, Velalenn, Zanron
- E, still, nothing logged (9): Aalall, Asvil, Behodiir, Deladoris, Derred, Dianore, Fitozz, Glolana, Zora
- F, moving, no XP (1): Fineklees
- G, offline (2): Asparano, Oswalt
