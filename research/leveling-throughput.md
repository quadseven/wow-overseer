# Leveling throughput: how fast the guilds level and gear, and what keeps 40 raiders from 60

Research for [wo#517](https://github.com/quadseven/wow-overseer/issues/517), workstream E of [wo#512](https://github.com/quadseven/wow-overseer/issues/512). Measured on wow-dev 2026-10-04 between 19:11 and 19:38 UTC. Read-only: no row was written anywhere.

## Answer in brief

The 132 non-family members of Cave and Bonkers were reset to level 1 on 2026-09-26 at about 05:40 UTC. 8.6 days later they average level 16 (Cave 16.3, Bonkers 15.7), wear item level 6 gear in 6 to 8 of 17 slots, and carry 14 silver each. Nobody but the families and one death knight is past 24.

Leveling has slowed to a crawl. Over a 25 minute window, half the members (66 of 132) gained no experience at all, 79 have not leveled in over 72 played hours, and the mean is 777 XP per member per hour. At that mean, a level 16 member reaches 60 in about 90 days of continuous play. At today's distribution, 40 raiders per guild never get there, because half the guild earns nothing.

The biggest blockers, in order:

1. Half the guild does not level. Members are unsupervised random bots, often in zones far off their level, and 29 of 132 stood still for 25 minutes.
2. Gear is starter whites. 117 of 132 members fail the dungeon gear gate, so no guild run has formed since 2026-10-01 03:35.
3. Members are too poor to buy gear. They average 14 silver, and a vendor kit for level 15 costs about 1 gold.
4. Quest throughput is near zero: 6 quest rewards across 132 members in 25 minutes.
5. Deaths are not measured for guild members. 10 to 13 of 132 lay dead at any instant.
6. The worldserver restarts often: 111 starts in 206 hours, 11 in the last 24.

At the current rate, the realm will not field 40 raiders per guild at 60. The leveling half averages about 1,550 XP per hour, which would take about 45 days. Getting there needs the stalled half moving and a gear path that does not depend on gold the members do not have.

## Sources

| Source | What was read |
|---|---|
| `acore_characters.overseer_snapshot` | Live level, map, zone, position, health, combat, group (fresh within 60 s) |
| `acore_characters.characters`, `guild`, `guild_member` | Saved level and xp, money, `totaltime`, `leveltime`, roster |
| `character_inventory`, `item_instance`, `acore_world.item_template` | Equipped item level and quality (bag 0, slots 0 to 18) |
| `character_queststatus_rewarded`, `corpse` | Quest rewards, dead members |
| `overseer_naturalized` | `reset` part: 132 rows, 2026-09-26 05:33 to 05:46 UTC |
| `overseer_guild_run` | All 189 guild runs, with members and their levels at formation |
| `overseer_raid_spec` | Raid seats: 35 non-family raiders per guild |
| `overseer_death`, `overseer_event`, `overseer_sample` | Family-only. They hold no row for a guild member (checked) |
| `acore_auth.uptime` | Worldserver starts since the reset |
| `acore_world.player_xp_for_level`, `quest_template`, `npc_vendor` | XP curve, zone quest levels (`QuestSortID`), vendor prices |
| Bridge log, `guild runs:` and `guild jobs:` lines | Last 90 minutes. The pod restarted at 17:39, so logs before that are gone |
| Code at main `b1b7626` | `guildrun.py` (`why_not`, `under_geared`, `GEAR_GAP`, `pools`), `bridge.py` (`_GUILD_RUN_MEMBERS_SQL`), `guildjobs.py`, `guildwork.py`, `gearup.py`, `natural.py`, `levelroute.py` |
| Worldserver deployment env | `AC_AI_PLAYERBOT_DISABLE_RANDOM_LEVELS=1`, `AC_AI_PLAYERBOT_RANDOMBOT_STARTING_LEVEL=1`. No XP rate override, so XP is 1x |

The families (Grug, Grog, Ugga, Bork, Og in Cave; Zug, Uzza, Oz, Zrog, Zork in Bonkers) are left out of every figure below unless named.

## 1. Where the guilds stand

| Guild | Members (non-family) | Avg level | Range | At 20+ | Gold carried, total | Bank |
|---|---|---|---|---|---|---|
| Cave | 66 | 16.3 | 2 to 59 | 4 | 10.2 g | 155 g |
| Bonkers | 66 | 15.7 | 10 to 24 | 5 | 8.7 g | 0 g |

Level bands (live snapshot, all 71 per guild including the family):

| Band | Cave | Bonkers |
|---|---|---|
| 0-9 | 1 | 0 |
| 10-14 | 24 | 28 |
| 15-19 | 37 | 32 |
| 20-24 | 3 | 6 |
| 25-29 | 0 | 5 (family) |
| 35-44 | 5 (family) | 0 |
| 55-59 | 1 | 0 |

The Cave member at 59 is Aalall, a death knight in Ebon Hold. Death knights start at 55, so that level was not earned by questing up from 1.

Raiders: `overseer_raid_spec` seats 35 non-family members per guild, plus the 5-member family, for 40. Raiders average level 17.5 in Cave and 15.7 in Bonkers, the same as non-raiders. Nothing levels raiders first.

## 2. Leveling rate

Guild members write no level history (`overseer_event` level_up rows are family-only), so the rate comes from four independent readings.

| Reading | Window | Result |
|---|---|---|
| Reset baseline (level 1 at 09-26 05:40) | 206 h | +15 levels average, but front-loaded |
| Levels recorded at guild-run formation vs now (94 members) | median 6.8 days | median +3 levels, 0.45 levels/day; 12 gained none |
| `characters.leveltime` (played time since last level-up) | at 19:11 | median 118 h; 79 of 132 over 72 h; 36 under 24 h |
| Saved XP, two samples | 19:13 to 19:38 | 42,391 XP total; mean 777 XP/h per member (Cave 586, Bonkers 967); 66 of 132 gained 0 XP; 2 level-ups |

The first run, on 09-27 at 21:27, already had members at level 12 to 16, so about 14 levels came in the first 40 hours. That is roughly 1,600 XP per hour, twice today's mean. Since then the pace has fallen to about a third of a level per member per day.

Caveat: `characters.xp` is the last save. The worldserver restarted at 19:08, which saved everyone just before the first sample. The second sample can lag by up to one save interval, so 777 XP/h is a floor.

### Time to 60

Level 16 to 60 is 3,288,800 XP (`player_xp_for_level`). Kill XP rises with mob level (about 45 + 5 x level per same-level kill), so the hourly rate is scaled up with level. Hours are wall hours at the measured 95% worldserver uptime.

| Assumed rate at level 16 | Days to 60 |
|---|---|
| 586 XP/h (Cave mean) | 119 |
| 777 XP/h (both guilds' mean) | 90 |
| 967 XP/h (Bonkers mean) | 72 |
| ~1,550 XP/h (mean of the 66 members who earned anything) | ~45 |
| 1,617 XP/h (the first 40 hours after reset) | 43 |
| 0 XP/h (the other 66) | never |

40 raiders per guild at 60 needs every raider moving. Today about half of each guild is not, so the honest estimate is "not at the current rate". About 45 days is the floor if every raider leveled like the active half, continuously. That floor counts level only. Section 4 shows those members would hit 60 in white gear.

## 3. Idle and quest throughput

Between the two samples (24.8 minutes):

- 29 of 132 members moved under 10 yards, and 26 of those 29 earned no XP.
- 132 members turned in 6 quests between them (3 members). Members average 24 quests rewarded since the reset (Cave 23.5, Bonkers 23.8). That is about 3 a day.
- Members earned 1,715 copper in total, about 0.4 silver per member per hour.

Nothing directs where a guild member levels. `levelroute.py` picks quest hubs for the two families only. `guildjobs.py` says a raider "levels on its own", which means mod-playerbots' own random-bot behavior. Zones against level (zone quest average from `quest_template.QuestSortID`):

- 33 members stand in zones whose average quest level is more than 5 below their own. Examples: 17 Bonkers members at 13 to 24 in Eversong Woods (quest average 8.4), and Cave members at 13 to 19 in Elwynn, Dun Morogh, Teldrassil and Azuremyst. Mobs there give little or no XP.
- 24 stand in zones more than 5 above them. Examples: 7 Cave members at 14 to 18 in Searing Gorge (quest average 50.1), and 2 in Badlands (41.7).
- The members who leveled in the last 24 hours and those stalled for 72+ hours look alike: the same average level (15.8 vs 16.0), the same share in starter zones (18 of 36 vs 30 of 79), and the same gear and purse. Zone alone does not explain the stall. The random-bot behavior of the stalled half is the open question.

## 4. Gear

Gear is measured the way the gate measures it (`bridge._GUILD_RUN_MEMBERS_SQL`): the average `ItemLevel` of equipped slots 0 to 18, without shirt and tabard (slots 3 and 18). Empty slots do not count against it.

| Guild | Avg level | Avg equipped ilvl | Slots filled (of 17) | Greens per member | Under the gate |
|---|---|---|---|---|---|
| Cave | 16.3 | 6.5 | 6.1 | 0.56 | 60 of 66 |
| Bonkers | 15.7 | 6.2 | 7.7 | 0.89 | 57 of 66 |

- Of 1,024 equipped items (with shirts), 837 are white with an average item level of 5.2, 91 are grey, 94 are green (average item level 20), and 2 are blue.
- The most-worn pieces are class starter gear and level 5 quest whites: Acolyte's Robe (item level 1, 23 members), Tapered Pants, Well Watcher Gloves, Snow Boots.
- The median member's gear is about 10 item levels under its own level. `guildrun.under_geared` holds a member home at more than 6 (`GEAR_GAP = 6`).
- Neck, rings and trinkets are empty on almost everyone. Members are leveling into the teens with half a set of starter clothing.

Members gain no gear because of where gear comes from after the reset. The playerbots factory grants nothing (`natural.py`), and quest rewards are scarce at 3 a day. Guild runs have stopped (section 5). Vendor buys need gold: the bridge already sends short members to vendors (`guild jobs: X walks to <vendor> to buy N piece(s) for empty slots`), and it also logs `Atherene is short of gear: no vendor within 1500 yards sells a short member a piece it can wear and afford`.

## 5. Guild runs

189 runs since 2026-09-27 21:27. The last one formed on 2026-10-01 at 01:35.

| Outcome | Cave | Bonkers |
|---|---|---|
| cleared | 0 | 5 (all Ragefire Chasm) |
| wiped | 9 | 18 |
| timed out | 7 | 25 |
| lost | 13 | 22 |
| not entered | 14 | 16 |
| refused | 35 | 25 |

- 5 clears in 189 runs (2.6%). All runs together gave 31 levels and 386 item levels.
- Every bridge pass in the last 90 minutes logged the same refusal: `117 gear too weak for a dungeon`, with 10 or 11 free members and no group of five that could be seated.
- The fallback that formed runs without the gate (#409) was removed in #435 on 2026-09-30, and runs stopped the next day. An offline replay of `guildrun.pools` on today's members, with the gate removed, finds 4 pools: Bonkers for Ragefire, and Cave for Wailing Caverns or the Deadmines. The gate is the only thing stopping runs.
- Removing the gate would bring back the old record: wipes, time-outs and lost runs at item level 2 to 6. Neither path gears the guild today.

## 6. Deaths

`overseer_death` only records characters on `overseer_roster`, and no guild member has ever had a row. Deaths per hour for guild members cannot be read. Two proxies:

- Corpses: 13 of 132 members were dead at 19:13 and 10 at 19:38. Six of the 66 members who earned no XP were dead in one of the two samples.
- The families died 72 times in the last 24 hours (Cave 30, Bonkers 42), about 7 deaths per character per day. The top killers were Drywallow Snapper, Flamescale Broodling, and falls (`self`). By job: town run 26, Shadowfang Keep 24, quest 16, Gnomeregan 3.

## 7. Jobs and money

- `guild jobs` places all 66 per guild as natural (`66 natural of 66 placed`). Ten per guild are maintenance gatherers, 21 are summoning warlocks, and 35 are raiders. No summoner has a door (`doors none`), because almost none have reached level 20, which Ritual of Summoning needs (`RITUAL_LEVEL = 20`).
- Gatherer skill is low: Cave has Mining 1 to 43 out of 75 and Herbalism 75 to 100. Some trainer walks fail and are retried ("waits to retry Mining, First Aid after a failed trainer walk").
- Money: members average 14 silver (maximum 3.8 gold, held by Aalall). Members post dues by mail to the guild master (`guildwork.py`, a tenth to a half of gold above a level-scaled float). That is small next to what the members earn: 0.4 silver per member-hour.
- The job pass starts 4 steps per guild per pass ("waits: 4 guild job steps per guild per pass"), so each pass reaches only a few of 66 members.

## 8. Restarts

`acore_auth.uptime` shows 111 worldserver starts between the reset and 19:11 on 10-04, with about 95% uptime. There were 11 starts in the last 24 hours, including 17:59 and 19:08 during this measurement. Each start logs everyone out and back in, and holds guild runs for `SETTLE_SECONDS = 600`. The lost play time is small next to blockers 1 to 3.

## Ranked blockers

| # | Blocker | Evidence | Effect |
|---|---|---|---|
| 1 | Half of each guild is not leveling | 66 of 132 earned 0 XP in 25 min; 79 have not leveled in 72+ played hours; 29 stood still | 40 raiders per guild cannot reach 60 at any timeline |
| 2 | Starter gear, gate shut | Avg item level 6.3 at level 16; 6 to 8 of 17 slots; 117 of 132 gated; no run since 10-01 | No dungeon XP, loot or gear; slower and deadlier questing |
| 3 | No gold | 14 silver average; vendor kit about 1 gold; 0.4 silver per member-hour | Vendor gear path closed; trainer ranks and repairs at risk |
| 4 | Undirected questing in the wrong zones | 3 quest rewards a day per member; 33 members in zones too low, 24 in zones too high; no hub routing for guild members | Low XP per hour even for the members who move |
| 5 | Dungeons fail when entered | 5 clears in 189 runs | Even an open gate yields little until gear and composition improve |
| 6 | No guild-member death or level history | `overseer_death` and `overseer_event` are family-only | Progress and deaths cannot be tracked or tuned |
| 7 | Frequent restarts | 11 starts in 24 h | Minor (about 5% downtime) |

## Open questions

- Why the stalled half stands still or earns nothing. It needs a per-member read of the playerbots strategy state and of what each member is doing, which this read-only pass did not take.
- How long a member at 60 in natural gear needs to gear for Molten Core. This depends on blocker 2 and on [wo#518](https://github.com/quadseven/wow-overseer/issues/518).
