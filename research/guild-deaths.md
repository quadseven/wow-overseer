# Guild deaths: why members die 900 times an hour, and what cuts it

Research for [wo#586](https://github.com/quadseven/wow-overseer/issues/586), workstream E of [wo#512](https://github.com/quadseven/wow-overseer/issues/512). Follows [wo#531](https://github.com/quadseven/wow-overseer/issues/531) ([research/idle-leveling.md](https://github.com/quadseven/wow-overseer/blob/research/idle-leveling/research/idle-leveling.md)). Measured on wow-dev from 21:42 ET to 22:11 ET on 2026-10-04 (01:42 to 02:11 UTC, 0.49 hours). Read-only: no row was written to the realm.

## Answer in brief

Cave and Bonkers (142 members, all online) died 444 times in 29 minutes: 912 per hour, 6.4 per member-hour. Two causes explain 71% of them. Half (224 deaths) are repeat deaths: a member dies, revives, walks back to its corpse and dies again within 10 minutes and 200 yards of the last death, to the same ordinary level-appropriate mobs. A fifth (93 deaths) happen on ground the member has no business on: the killer is 5 to 40 levels above the member, mostly in Searing Gorge, Badlands, Duskwood and Alterac Mountains. Elites are 2% of deaths. Nobody was grouped. The one change that cuts the most: after a second death near the same corpse, mod-overseer must stop sending a guild member back to the corpse (today the guild path labels the recovery `ladder` and still runs the corpse), and must send it out of the area instead.

## Method

| Source | What was read |
|---|---|
| `acore_characters.overseer_death` | Every row for a Cave or Bonkers member created 01:42 to 02:11 UTC: 444 rows, 80 distinct members |
| `guild`, `guild_member` | Roster: Cave 71, Bonkers 71 |
| `acore_world.creature_template` | Killer min and max level, `rank` (0 normal, 1 elite, 2 rare elite, 4 rare) |
| `overseer_snapshot` | Live zone, level and health of the members involved |
| `overseer_command` | `guildjobs:*` rows in the 15 minutes before each death |
| `character_queststatus`, `quest_template` | Whether an over-level member holds a quest in the zone it died in |
| Worldserver log, `module.overseer` | "guild death" lines (equipment, attackers, grouped) and "ghost recovery" lines (choice and reason) |
| Mounted `playerbots.conf` | Revive timers, teleport and quest settings |
| mod-overseer main `f095960` | `DecideGhostRecovery` in `src/overseer_decisions.cpp`; `DriveGuildGhostRecovery` and `LogGuildDeath` in `src/mod_overseer.cpp` |

Levels used: the member's level at death against the killer's `maxlevel` from `creature_template` (gap = killer minus member). A repeat death is the same member dying within 10 minutes and 200 yards of its previous death on the same map. Each death is placed in the first cause that fits, in the order of the cause table.

## Data gap

For guild members, `overseer_death` fills only: name, level, map, zone, position, killer type, name and entry, and `ghost_recovery`. Every guild row has `job` empty, `driver` `unknown`, `grouped` 0, `group_size` 0, `in_combat` -1, `health_at_death` 0, no `damage_*` and no `movement_generator`. The log line carries "0 attacker(s)" on all 457 lines sampled, because combat has already stopped when the hook runs. So solo versus grouped comes from the log (no "grouped" suffix on any line) and the roster (no member held a group in the earlier sample), and job at death is inferred (below), not recorded. Filling these for the guild path is recommendation 6.

## 1. Rate

| | Value |
|---|---|
| Deaths | 444 in 0.487 h |
| Per hour | 912 |
| Per member-hour (142 members) | 6.4 |
| Members who died | 80 of 142 |
| Per dying member-hour | 11.4 |
| Median deaths per dying member | 5 (21 members died 8 or more times, maximum 13) |
| Ten worst members | 117 deaths (26%) |
| Cave / Bonkers | 183 / 126 in the first 20 minutes |

Members are level 10 to 21 (184 deaths at 10 to 14, 224 at 15 to 19, 36 at 20 and up).

## 2. Causes, ranked

| # | Cause | Deaths | Share | Members |
|---|---|---|---|---|
| B | Repeat death at the same spot, killer within 2 levels of the member or easier | 224 | 50% | 52 members in chains of 3 or more |
| C | First death at a spot on level-appropriate ground (gap 4 or less) | 120 | 27% | |
| A | Killer 5 or more levels above the member (mean gap 20) | 93 | 21% | 12 |
| D | Elite or rare-elite killer, not already counted | 7 | 2% | |
| | Total | 444 | | |

Cause A overlaps B: 75 of the 93 are also repeats (a member parked in Searing Gorge dies every 2 to 3 minutes). Counting the repeat first is deliberate, because the repeat is what the fix has to stop. If every repeat were prevented, 444 deaths would fall to 145 (one death per member per spot), 2.3 per member-hour.

### Killer level against member level (all 444)

| Killer minus member | Deaths |
|---|---|
| 3 or more levels easier | 55 |
| Even (-2 to +2) | 271 |
| +3 to +4 | 24 |
| +5 to +9 | 11 |
| +10 or more | 82 |
| No template | 1 |

61% of deaths are to a mob of the member's own level. Dying to equal mobs is the cost of fighting in starter gear: the 507 "guild death" lines in the last 45 minutes show members wearing 7.6 items on average with an average item level of 5.1 at an average character level of 15.5, and 481 of the 507 (95%) average item level 8 or less.

## 3. Where

| Zone | Deaths | Members | Mean level | Killer 5+ above | Repeats | Top killers |
|---|---|---|---|---|---|---|
| The Barrens | 138 | 24 | 15.2 | 9 | 85 | Zhevra Runner, Sunscale Scytheclaw |
| Bloodmyst Isle | 42 | 8 | 13.5 | 0 | 29 | Thistle Lasher, Grizzled Brown Bear |
| Silverpine Forest | 41 | 11 | 15.7 | 0 | 19 | Dalaran Protector, Moonrage Glutton |
| Loch Modan | 33 | 5 | 14.8 | 0 | 26 | Mangy Mountain Boar, Grizzled Black Bear |
| Searing Gorge | 31 | 3 | 17.2 | 31 | 24 | Magma Elemental (level 48) |
| Ghostlands | 31 | 6 | 14.7 | 0 | 20 | Vampiric Mistbat |
| Westfall | 30 | 4 | 13.8 | 0 | 25 | Riverpaw Mongrel |
| Badlands | 23 | 2 | 15.5 | 23 | 21 | Starving Buzzard (level 37) |
| Stonetalon Mountains | 17 | 3 | 18.8 | 0 | 13 | Deepmoss Venomspitter |
| Duskwood | 12 | 1 | 13.0 | 12 | 11 | Skeletal Fiend (level 25) |
| Alterac Mountains | 11 | 1 | 20.0 | 11 | 10 | Crushridge Ogre (level 35) |

Top killers overall: Riverpaw Mongrel 20, Zhevra Runner 19, Magma Elemental 18, Grizzled Brown Bear 15, Sunscale Scytheclaw 15, Thistle Lasher 13, Skeletal Fiend 12.

### Zones above the member's level (cause A)

93 deaths, 12 members, killers 5 to 40 levels above (mean 20). By zone: Searing Gorge 31, Badlands 23, Duskwood 12, Alterac Mountains 11, Barrens 9, Ashenvale 7. By killer: Magma Elemental (level 48) 18, Skeletal Fiend (25) 12, Starving Buzzard (37) 11, Crushridge Ogre (35) 11, Feral Crag Coyote (38) 8, Dark Iron Lookout (48) 7, Wildthorn Lurker (29) 6, Glassweb Spider (45) 5. Member levels 11 to 21. Seven members account for 79 of the 93 (each died 8 to 13 times).

How they got there is not established. Only 4 of the 12 hold any quest in the zone they died in, so quests do not explain it for the other 8. Their `overseer_command` rows show guild job walks and hearths for some (Ginny four hearths, Bitlubro a vendor walk, a hearth and a mailbox walk, Caelianon two mailbox walks), and none for Alindy, Baleron and Eveline. Natural guild members skip the random teleport ("keeps its own kit - random teleport skipped"), so the playerbots random-teleport path is not the source for them.

## 4. Death loops

Of 444 deaths, 299 (67%) repeat the previous death of the same member inside 10 minutes and 200 yards. 52 members run chains of 3 or more such deaths, 314 deaths in all. The median gap between repeats is 174 seconds. Examples from the log, 02:00 to 02:07: Bitlubro (level 18, Searing Gorge) died to a level 46 Magma Elemental seven times in seven minutes, each corpse within 26 yards of the last; Caelianon (level 13, Duskwood) died to a level 24 to 25 Skeletal Fiend five times, corpse 0 to 5 yards from the last.

What the member does after each death, from `ghost_recovery`, and what followed the previous death for the 299 repeats:

| Recovery chosen | All deaths | Followed by a repeat death |
|---|---|---|
| `ladder` | 131 | 116 |
| `corpse_run` | 150 | 111 |
| `spirit_healer` | 103 | 41 |
| not decided | 57 | 30 |
| `wait` | 3 | 1 |

Why `ladder` loops. `DecideGhostRecovery` answers `ladder` when a hostile well above the ghost stands near the corpse, or the member already died here twice, and the spirit-healer graveyard fails the safety test (it stands on higher-level ground, or has hostile spawns above the member). The guild caller, `DriveGuildGhostRecovery`, passes `ladder = false` to `DriveGhostRecovery`. In the `Ladder` case that makes the member call `ReturnCorpseRun`, the plain run to the corpse. So the repeat-death and outlevelled verdicts for guild members end in the same corpse run they were meant to prevent. The member revives on the corpse, still next to the killer, and dies again. Log lines show 102 `ladder` choices with reason "it has already died here inside the repeat window" in 25 minutes.

Spirit-healer revivals also loop (41 of 103) but far less, and with a longer gap (median 408 seconds, only 20% inside 5 minutes), because the member returns from the graveyard and walks back into the same fight rather than standing on the corpse.

## 5. Solo versus grouped

All 444 deaths are solo. No "guild death" line carries the `, grouped` suffix in 70 minutes of log, and no guild member held a group in the [wo#531](https://github.com/quadseven/wow-overseer/issues/531) sample. A level 15 member fights packs alone in starter gear.

## 6. Job at death

The row does not record the job (see Data gap). The proxy is a `guildjobs:*` command to the member in the 15 minutes before the death:

| Proxy | Deaths | Share |
|---|---|---|
| No guild job command (quest, rpg or travel under playerbots) | 389 | 88% |
| `hearth` | 13 | 3% |
| `gear` | 13 | 3% |
| `craft` | 12 | 3% |
| `collect-walk` | 11 | 2% |
| `post-walk` | 6 | 1% |

77 guild job commands were issued in the window against 444 deaths. Guild jobs are about 12% of deaths. The other 88% happen to members under playerbots' own `new rpg` quest and travel drive, which mod-overseer neither chooses nor records for guild members.

## 7. Elites

9 deaths (2%): Leprithus (rare, level 19, Westfall), Shleipnarr (rare, 47, Searing Gorge), Barnabus (rare, 38, Badlands), Brokespear (rare, 17, Barrens), Haren Swifthoof (elite, 21, Loch Modan), Gradok (elite, 21, Loch Modan), Emogg the Crusher (rare elite, 19, Loch Modan), Large Loch Crocolisk (rare, 22, Loch Modan), Aean Swiftriver (rare elite, 22, Barrens). Elites are not a lever.

## Recommendations

Ordered by deaths removed. Each names its component.

1. **mod-overseer, guild ghost recovery (cause B, up to 224 deaths, 50%).** Make the `ladder` verdict real for guild members. When a member has died twice near its corpse inside 10 minutes, or the verdict is `ladder`, do not run the corpse. Take the spirit healer even when its graveyard fails the safety test (the family path already does this on the other faction's ground via `hostileGround`), accept the sickness, and then move the member out. Today `DriveGhostRecovery(..., ladder = false, ...)` for guilds turns the verdict into a corpse run. A test can drive three deaths at one corpse and assert that the fourth recovery is not a corpse run.
2. **mod-overseer, a death budget and a way out (causes A and B).** After the third death in 10 minutes within 200 yards, hearth the member to its bind point (or walk it to the nearest quest hub that fits its level) and keep it off that spot for a cool-down. This is what a careful player does: stop respawning into the same pack. The mover already exists for the family (`levelroute.py` routes families only, per its docstring); the guild has none.
3. **mod-overseer or wow-overseer, a level fit rule for guild members (cause A, 93 deaths, 21%).** A member whose zone is 5 or more levels above it (killer levels 25 to 48 against members of 11 to 21) is hearthed or teleported out. 7 members cause 79 of these deaths, so the rule touches few members. The first step is to find out how they get there: log the source of each guild member's cross-zone move (`guildjobs` walk, hearth, or playerbots travel), because 8 of 12 hold no quest in the zone.
4. **playerbots config (cause B, supporting).** The revive timers are `MinRandomBotReviveTime 60` and `MaxRandomBotReviveTime 300`, and the median repeat gap is 174 seconds, which fits a member that revives and re-engages at once. A longer minimum (or the mod-overseer hold from recommendation 1) lets mobs reset and leash before the member returns. The setting changes every bot, so measure on the guilds first.
5. **wow-overseer guild jobs, gear (cause C and B, supporting).** 95% of deaths wear gear averaging item level 8 or less at level 15. Natural progression means gear has to come from `guildjobs` gear and craft jobs and from quests. A member with a gear gap of this size should buy and craft before it fights packs. The share of deaths that gear would remove is not measured here: dying to equal-level mobs (61%) is the fingerprint, not the proof.
6. **mod-overseer, record the context (data gap).** For guild deaths, fill `job`, `driver`, `grouped`, `in_combat` and `health_at_death` the way the family path does, and record the drive that issued the last move. Without it, recommendations 3 and 5 cannot be checked against the table.

On this sample, recommendations 1 and 2 together address 317 of 444 deaths (71%, causes A and B), with an upper bound of 912 down to about 330 per hour.

## Open questions

- What moves a level 15 member into Searing Gorge, Badlands or Duskwood. Not quests (4 of 12), not the random teleport (skipped for natural members), partly guild job walks. Recommendation 3 starts with logging it.
- Whether the first death at a spot (cause C, 120 deaths) is reducible by gear or by resting to full health before a pull. The row has no health or combat state to test it.
- The sample is 29 minutes after a roll, with 80 of 142 members dying. The rate may shift as members level out of the Barrens.
