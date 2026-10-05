# Repeat deaths after the spirit-healer fallback: which path they take

Research for [wo#597](https://github.com/quadseven/wow-overseer/issues/597), workstream E of [wo#512](https://github.com/quadseven/wow-overseer/issues/512). Follows [wo#586](https://github.com/quadseven/wow-overseer/issues/586) ([research/guild-deaths.md](https://github.com/quadseven/wow-overseer/blob/research/guild-deaths/research/guild-deaths.md)) and [mod-overseer#842](https://github.com/quadseven/mod-overseer/pull/842). Measured on wow-dev from 23:07 ET to 23:56 ET on 2026-10-04 (03:07 to 03:56 UTC on 2026-10-05), the first 49 minutes after the roll that carried #842. Read-only: no row was written to the realm.

## Answer in brief

The remaining repeats do not take one path. They take all of them. Of 311 classified repeats, 101 (32%) are corpse runs that the no-stacking-sickness rule forced after an earlier spirit-healer revival, even though the member had already died at the spot or a hostile well above it stood there. 83 (27%) are corpse runs chosen as Clear because the killer was below the member's level, and the threat check counts only hostiles at or above it. 41 (13%) took the spirit healer at a graveyard within 60 yards of the killer. 40 (13%) were revived in place by the playerbots random-bot manager before mod-overseer made any decision. 29 (9%) took the spirit healer and walked back into the same spot. The rest, 17 (5%), are first-death fallbacks to the corpse run. The healer walk never timed out. What the paths share: 161 of the 311 (52%) are a third or later death at one spot, so the member had died there twice and was revived there again. The change that stops the most is the one a careful player makes: after a second death at one spot, leave once alive (hearth), whatever the revival path. [mod-overseer#846](https://github.com/quadseven/mod-overseer/pull/846) does that.

## Method

| Source | What was read |
|---|---|
| `acore_characters.overseer_death` | Every row for a Cave or Bonkers member created 02:30 to 03:57 UTC: 1,179 rows, with position, level, killer and `ghost_recovery` (guild rows since [mod-overseer#839](https://github.com/quadseven/mod-overseer/pull/839)) |
| `guild`, `guild_member`, `characters` | The roster of both guilds |
| `acore_world.game_graveyard` | Graveyard positions, matched by the name the log gives |
| Worldserver log, `module.overseer`, from 23:06 ET (the pod start) | "guild death" (member and killer level), "ghost recovery for" (choice, reason, corpse position, deaths here, strongest hostile, live hostiles, graveyard), "took the spirit healer's resurrection", "never stood at one", "revived with Resurrection Sickness", "Resurrection Sickness ended", "held where it revives" |
| Worldserver log, `playerbots` | "Natural guild: X keeps its own kit - random teleport skipped", which `RandomPlayerbotMgr::Revive` prints when it revives a dead random bot; given the timestamp of the line before it |
| mod-overseer main `0aaee37` | `DriveGuildGhostRecovery`, `DriveGhostRecovery`, `HoldAfterRevival`, `DriveRevivedSickness` and `GhostThreatCheck` in `src/mod_overseer.cpp`; `DecideGhostRecovery`, `GuildGhostFallback` and `DecideRevivedSickGround` in `src/overseer_decisions.cpp` |
| mod-playerbots (quadseven fork) | `RandomPlayerbotMgr::Revive` and `RandomPlayerbotMgr::Refresh` in `src/Bot/RandomPlayerbotMgr.cpp`; infra patch `0024-a-natural-guild-is-granted-nothing.patch` |

A repeat death is the ticket's: the same member dying within 60 yards and 15 minutes of its previous death on the same map. Classified: every repeat whose previous death fell at or after 23:07 ET, so that the recovery after it is in the log. The path is read from the log lines for that member between the previous death and the repeat. A "ghost recovery" line is matched to the previous death by corpse position (within 15 yards).

| | Value |
|---|---|
| Guild deaths 23:07 to 23:56 ET | 637 |
| Repeats (ticket definition) | 338 (53%) |
| Repeats classified (previous death also after 23:07) | 311 |
| Members with a classified repeat | 68 |
| 23:17 to 23:47 ET, ticket window | 392 deaths, 209 repeats (53%) |

The ticket counts 192 repeats in the 23:17 to 23:47 window; this count is 209 over the same 392 deaths. The likely difference is that this count lets the previous death fall before the window start. Either way about half of guild deaths are repeats, as before #842.

## How the code chooses (main `0aaee37`)

`DriveGuildGhostRecovery` runs each poll for every natural guild member that `GuildGhostDriven` admits. A dead member with no corpse yet (not released) is skipped. A released ghost goes to `DriveGhostRecovery(..., ladder = false, ...)`, which asks `DecideGhostRecovery`:

1. A healer choice already made is kept.
2. 1a. If the spirit healer was used in the last 600 seconds (`SPIRIT_HEALER_SICKNESS_SECONDS`) and a corpse run is possible (always true here), the answer is the corpse run, with reason Clear. Added in [mod-overseer#747](https://github.com/quadseven/mod-overseer/pull/747) "so sickness does not stack", and pinned by two cases in `tests/test_ghost_recovery.cpp` at 2 and 3 deaths here.
3. Two or more deaths within 60 yards in 10 minutes: the spirit healer, or Ladder if its graveyard fails the safety test.
4. A hostile 3 or more levels above the member near the corpse: the same.
5. A live hostile at or above the member's level near the corpse: Wait for 90 seconds, then the same.
6. Otherwise Clear: the corpse run.

For a guild caller, #842 maps Ladder through `GuildGhostFallback`: the spirit healer at 2 or more deaths here with a graveyard known, else the corpse run. The threat test (`GhostThreatCheck`) counts only creatures at or above the member's level within 39 yards of the corpse (`CORPSE_RECLAIM_RADIUS`); the spawn test counts spawns above it.

After a spirit-healer revival, `HoldAfterRevival` holds the member still 20 seconds when nothing hostile spawns within 30 yards, and `DriveRevivedSickness(restWhileSick = true)` holds it still, out of combat, until the sickness ends, unless spawns within 30 yards reach 3 levels above it, in which case it hearths when the stone is ready. After a corpse reclaim nothing holds or moves the member: it resumes where it died.

Separately, `RandomPlayerbotMgr` marks a dead random bot and, 60 to 300 seconds later (`MinRandomBotReviveTime`, `MaxRandomBotReviveTime`), calls `Revive`, whose `Refresh` runs `ResurrectPlayer(1.0f)` before the natural-guild check that patch 0024 adds. A member that has not released is revived at full health on its corpse, with no decision from mod-overseer and no sickness.

## Paths, ranked

| # | Path after the previous death | Repeats | Share | 3rd or later in chain | Killer below member | Killer 5+ above |
|---|---|---|---|---|---|---|
| 1 | Corpse run forced by rule 1a (healer used in the last 600 s) although deaths here, a hostile 3+ above, or a live hostile argued against it | 101 | 32% | 74 | 20 | 42 |
| 2 | Corpse run chosen as Clear: first death here, nothing at or above the member's level seen within 39 yards | 83 | 27% | 1 | 79 | 0 |
| 3 | Spirit healer taken, graveyard within 60 yards of the corpse (beside the killer) | 41 | 13% | 34 | 8 | 19 |
| 4 | No decision logged: revived in place by the playerbots random-bot manager | 40 | 13% | 32 | 11 | 11 |
| 5 | Spirit healer taken, graveyard 60+ yards away, walked back into the spot | 29 | 9% | 18 | 13 | 3 |
| 6 | Ladder at a first death (hostile 3+ above), `GuildGhostFallback` gave the corpse run | 9 | 3% | 0 | | |
| 7 | Wait that expired, then Ladder, then the corpse run (first death here) | 6 | 2% | 0 | | |
| 8 | No decision and no revive line seen | 2 | 1% | 2 | | |
| | Spirit-healer walk timed out ("never stood at one") | 0 | 0% | | | |
| | Total | 311 | | 161 | | |

The killer columns use the killer level from the repeat's "guild death" line against the member's level.

### How often each path leads to a repeat

Over every guild death from 23:07 to 23:41 ET (455 deaths, so each has a full 15 minutes after it), the share followed by a repeat:

| Path | Deaths | Followed by a repeat |
|---|---|---|
| Corpse run forced by rule 1a | 94 | 83% |
| Ladder at a first death, then the corpse run | 9 | 78% |
| Corpse run chosen as Clear | 118 | 51% |
| Wait that expired, then the corpse run | 10 | 50% |
| Revived in place by playerbots | 55 | 49% |
| Spirit healer taken | 153 | 36% |
| No decision, no revive seen | 16 | 6% |

The spirit healer is the safest path the code has and still repeats a third of the time. The corpse run after a recent healer use is the worst.

### Path 1: the no-stacking-sickness rule overrides the repeat test

Rule 1a sits above the repeat and outlevelled rules, so for 600 seconds after any spirit-healer revival every further death is a corpse run, logged as "nothing near the corpse argues against reclaiming it". Example from the log: Caelianon (level 13, Duskwood) took the spirit healer at Ravenhill at 23:07:25 ET, died at 23:08:04, and the next decision was `corpse_run` with "4 death(s) within 60 yards in 10min; strongest hostile ... level 24 'Skeletal Horror'". 77 of the 101 were made after the member's sickness had already ended (a "Resurrection Sickness ended" line came between the healer and the death), because the rule waits a fixed 600 seconds and the sickness of a member below level 20 is shorter (Caelianon, level 13: healer at 23:07:25, sickness ended at 23:10:53). 42 of the 101 died to a killer 5 or more levels above.

### Path 2: Clear, because a lower-level killer is invisible

79 of 83 died to a mob below their own level (Barrens plainstriders and zhevras, Bloodmyst and Silverpine wildlife). `GhostThreatCheck` counts hostiles at or above the member's level, so the pack that killed it reads as nothing near the corpse. These are second deaths in a chain (82 of 83): the first death at a spot, where the repeat test cannot yet fire. The member reclaims beside the pack at partial health and nothing moves it away.

### Paths 3 and 5: the spirit healer brings the member back to the same ground

41 revived at a graveyard within 60 yards of the corpse. Examples: Alindy (level 16, Badlands, Graveyard NE) four times, the graveyard 0 to 11 yards from the death point, to level 37 Starving Buzzards; Bitlubro (level 18, Searing Gorge SE graveyard) five times to Magma Elementals and Shleipnarr; Caelianon (Ravenhill) four times. `HoldAfterRevival` and the sickness hold keep the member standing still at the graveyard because no hostile spawn is within 30 yards. The ghost recovery lines for the same corpses show the killer type standing within 39 yards (Caelianon: "strongest hostile within 39 yards of the corpse level 24 'Skeletal Horror'"). 29 more revived 60 to 430 yards away and then walked back into the same spot under playerbots' own quest drive (median gap 394 seconds).

### Path 4: revived before any decision

40 repeats had no "ghost recovery" line between the deaths and a playerbots revive line between them (median gap 92 seconds). `RandomPlayerbotMgr::Revive` resurrects an unreleased member on its corpse at full health. mod-overseer's drive skips a dead member with no corpse, so it never sees these deaths, and its death marks do not count them.

### Revived-sickness holds

34 of the 311 repeats died while still sick (a healer revival with no "Resurrection Sickness ended" line before the death). 14 of them are path 3, members held still at a graveyard beside the killer. The sickness hold is a factor in path 3, not a path of its own.

## Where

| Zone | Repeats |
|---|---|
| The Barrens | 104 |
| Silverpine Forest | 29 |
| Westfall | 28 |
| Badlands | 27 |
| Ghostlands | 25 |
| Bloodmyst Isle | 22 |
| Loch Modan | 22 |
| Duskwood | 17 |

The members dying most: Alindy 19, Caelianon 17, Cokderl 15, Alestheon 12, Danderollo 11.

## Recommendations

Ordered by repeats addressed. Each names its component.

1. **mod-overseer, guild drive: leave after the second death (paths 1, 3, 4, 5; up to 161 repeats, 52%).** A living guild member with two or more deaths within the repeat radius of where it stands, inside the window, hearths when its stone is ready and it is out of combat. This is the careful player's rule: stop after the second death, whatever brought you back. It fires on revival at the corpse, at a graveyard beside the killer, and on walking back in. The hearthstone's one-hour cooldown limits it to one exit per member per hour, and 126 of the 161 fall in a member's first long chain, so 126 (41%) is the nearer estimate. Opened as [mod-overseer#846](https://github.com/quadseven/mod-overseer/pull/846).
2. **mod-overseer, `DecideGhostRecovery` rule 1a (path 1, 101 repeats).** Do not let "healer used recently" override repeat deaths or an outlevelled corpse, and tie its window to the sickness the member actually carries (aura 15007 on the member) instead of a fixed 600 seconds. This reverses part of [mod-overseer#747](https://github.com/quadseven/mod-overseer/pull/747) and its two pinned test cases, so it needs its own decision. On these numbers the cohort would move from an 83% repeat path to the healer's 36%.
3. **mod-overseer, threat near the corpse (path 2, 83 repeats).** Count the killer itself, and hostiles a few levels below the member, as threats near the corpse. 79 of 83 Clear repeats died to a lower-level mob. The gain is modest on its own (the Wait path repeats 50% and the spirit healer 36%, against 51% for the Clear corpse run), so pair it with a rest to full health after reclaiming, before the quest drive resumes.
4. **mod-overseer, the revive the drive never sees (path 4, 40 repeats).** Note a death mark for a dead member that has not released (its position is the death point), so the repeat test and recommendation 1 count deaths that `RandomPlayerbotMgr::Revive` revives in place.
5. **mod-overseer, revival hold at a graveyard beside the killer (path 3).** `HoldAfterRevival` and the sickness hold test hostile spawns within 30 yards; the corpses in path 3 had the killer type within 39 yards. Test the live grid and the corpse distance too, and when the graveyard is within 60 yards of the last death, move the member away (or hearth, recommendation 1) instead of holding it still.

## Open questions

- Where a natural guild member's hearthstone is bound, and whether the playerbots quest drive walks it straight back to the same zone after a hearth. The PR's acceptance measures it.
- Why level 13 to 18 members are in Duskwood, Badlands and Searing Gorge at all, which [wo#586](https://github.com/quadseven/wow-overseer/issues/586) left open and which drives most of the 5-or-more-levels deaths in paths 1 and 3.
