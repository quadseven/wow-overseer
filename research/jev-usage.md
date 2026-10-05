# Jev in live decisions: use, agreement, and outcome feedback

Research for [#583](https://github.com/quadseven/wow-overseer/issues/583), workstream E of [#512](https://github.com/quadseven/wow-overseer/issues/512). Measured 2026-10-04 (America/New_York) on the dev realm, read-only.

## Sources

- Code at `origin/main` ce4cad9: `jev.py` (client, `Policy.acted`, `threshold`), every `jev.policy` caller (`guildrun.py`, `jev_items.py`, `jev_keep.py`, `jev_activity.py`, `jev_family_intent.py`, `jev_movement.py`, `jev_choices.py`, `levelroute.py`, `lootcouncil.py`, `jev_recovery.py`, `raidsupply.py`, `dungeonpace.py`, `tradechoice.py`), `guildsocial.py`, and the bridge's guild-run loop (`bridge.py` `_guild_run_once`, `_guild_social_once`, `_start_social_run`).
- `overseer_jev_judgment`: every judgment since the table began, 54,904 rows, 2026-09-22 to 2026-10-04. This is the whole history, so Datadog adds nothing older.
- `overseer_guild_run`: 211 runs, 2026-09-27 to 2026-10-04. Columns include `dungeon_by`, `dungeon_jev`, `dungeon_confidence`, `composition_by`, `composition_jev`, `composition_confidence`, `prior_rate`, `prior_runs` and `outcome`.
- `overseer_loot_council`, `overseer_run_recovery`, `overseer_dungeon_pace`, `overseer_family_intent`: checked for outcome columns.
- The pod's last 24h log (it restarted at 21:44 ET on 10-04, so the log is thin; the tables carry the history).
- Deployment env: no `JEV_MODE_*` or `JEV_THRESHOLD_*` override is set. Every kind runs at its code default.

## How Jev is wired

- One client (`jev.Client`), one 3 s deadline, no retry, 4 slots, a 512-entry answer cache. A missing answer of any kind leaves the heuristic acting.
- Each kind has a mode (`act` by default everywhere except `quest_pick`, which has no act path) and a floor. `Policy.acted` returns `jev` when Jev differs and clears the floor, `both` when it agrees and clears the floor, and `heuristic` otherwise.
- `on_agreement=True` (guild_dungeon, guild_composition, activity_choice, movement, loot_council, item_disposition, run_recovery, dungeon_step) records an agreeing answer as `both` at ANY confidence. No action changes, but the record then credits Jev with heuristic picks it was not sure of.
- The question carries world state and, for a few kinds, a record of past outcomes in the option text. No kind sends Jev a labeled history of its own past answers, and nothing trains or tunes the model from outcomes. "Learning" exists only where a caller folds outcomes into the prompt.

## Per-kind measurements (2026-09-22 to 2026-10-04, all rows)

Answer rate = answered or cached / asked. Confidence buckets are counts. Agreement is over answered rows. Acted columns are what the record says was carried out.

| kind | floor | asked | answer rate | mean / max latency ms | conf <0.3 / 0.3-0.6 / 0.6-0.8 / >=0.8 | agree | acted jev / both / heuristic | outcome recorded |
|---|---|---|---|---|---|---|---|---|
| item_keep | 0.85 (bank, give 0.6) | 26,974 | 98.8% | 340 / 2982 | 4573 / 14902 / 2057 / 5106 | 29% | 499 / 4538 / 21937 | no |
| item_disposition | 0.80, agree | 12,978 | 98.8% | 283 / 2998 | 3538 / 6885 / 2023 / 371 | 53% | 18 / 6658 / 6175 | no |
| guild_recipient | 0.75 | 3,964 | 98.6% | 323 / 2835 | 1020 / 1150 / 726 / 1011 | 47% | 127 / 847 / 2990 | no |
| activity_choice | 0.6, agree | 2,562 | 99.2% | 314 / 2177 | 468 / 1066 / 333 / 674 | 63% | 545 / 1413 / 604 | no |
| family_intent | 0.7 | 2,546 | 99.3% | 281 / 2462 | 275 / 477 / 589 / 1187 | 58% | 450 / 947 / 1149 | no (table has no outcome column) |
| leveling_zone | 0.7 | 1,898 | 97.0% | 294 / 2807 | 287 / 660 / 451 / 444 | 65% | 99 / 593 / 1206 | no |
| weapon_choice | 0.85 | 1,817 | 99.6% | 272 / 2872 | 95 / 178 / 116 / 1420 | 83% | 57 / 1274 / 480 | no |
| movement | 0.75, agree | 907 | 99.3% | 302 / 2545 | 295 / 207 / 189 / 210 | 41% | 165 / 307 / 435 | no |
| raid_supply | 0.6 | 228 | 100% | 386 / 775 | 0 / 225 / 3 / 0 | 99% | 0 / 3 / 225 | no |
| staging_stall | 0.65, agree | 219 | 99.1% | 392 / 2698 | 70 / 128 / 18 / 1 | 16% | 3 / 15 / 201 | partly (next attempt) |
| guild_dungeon | 0.6, agree | 211 | 99.5% | 300 / 2259 | 27 / 17 / 16 / 150 | 89% | 5 / 187 / 19 | yes, and fed back |
| guild_composition | 0.6, agree | 211 | 99.5% | 300 / 2259 | 91 / 47 / 12 / 60 | 66% | 11 / 139 / 61 | yes, and fed back |
| loot_council | 0.75, agree | 190 | 100% | 317 / 594 | 33 / 58 / 30 / 69 | 54% | 14 / 103 / 73 | yes (`given_to`, `outcome`), not fed back |
| run_recovery | 0.6, agree | 179 | 100% | 350 / 625 | 49 / 99 / 20 / 11 | 36% | 6 / 53 / 120 | yes, and fed back (`history`) |
| dungeon_choice | 0.7 | 9 | 100% | 270 / 319 | 1 / 1 / 6 / 1 | 78% | 0 / 1 / 8 | wipes per door in the prompt |
| profession_choice | n/a | 5 | 100% | 337 / 419 | 1 / 2 / 2 / 0 | 60% | 0 / 0 / 0 | no |
| dungeon_step | 0.6, agree | 3 | 100% | 351 / 444 | 1 / 1 / 1 / 0 | 67% | 0 / 2 / 1 | yes (`overseer_dungeon_pace.outcome`), in prompt as door record |
| quest_pick | shadow | 3 | 67% | 288 / 295 | 1 / 0 / 1 / 0 | 0% | 0 / 0 / 3 | no |

Availability is not the problem: every kind answers 97% or more, the mean is about 0.3 s, and nothing exceeds the 3 s deadline. `busy` is the largest loss (188 item_keep, 112 item_disposition, 52 leveling_zone).

### Does confidence mean anything?

Agreement with the heuristic by confidence bucket is the only calibration signal most kinds have, because most kinds record no outcome.

- Confidence tracks agreement well for item_keep (6% agree below 0.6, 92% at 0.8 and up), weapon_choice (91% at 0.8 and up), leveling_zone (38% to 92%), loot_council (27% to 87%), run_recovery and guild_dungeon. In these kinds a high-confidence disagreement is a real signal and the floor is doing its job.
- Confidence carries no signal for movement (agreement 37% to 46% in every bucket) and runs backwards for activity_choice: at 0.8 and up Jev agrees only 32% of the time, and those disagreements act. The largest is `campaign -> sell` at a mean 0.92, carried out 230 times in the last 7 days, plus `quest -> sell` 121 times. No record says whether those sells helped or cost the campaign.
- For guild_dungeon, confidence is not calibrated to outcome. Runs Jev chose at 0.8 and up cleared 6 of 48 that went in; below 0.8, 0 of 21. At 1.0 it chose Ragefire for the 10-14 band 91 times on 09-27 and 09-28, and 72 of those never got in (refused, not entered, lost).

## Guild runs: who chose the door, and how it went

Of 211 runs, 77 went in (cleared, wiped, abandoned, timed out). 6 cleared, all Ragefire at band 15-19 with a tank-spec tank and a healer-spec healer.

| shape (tank / healer) | door | went in | cleared | deaths a run |
|---|---|---|---|---|
| spec / spec | Ragefire | 48 | 6 | 2.8 |
| class / class | Wailing Caverns | 10 | 0 | 4.7 |
| spec / class | Wailing Caverns | 8 | 0 | 4.0 |
| spec / spec | Wailing Caverns | 5 | 0 | 4.0 |
| spec / class | Ragefire | 3 | 0 | 2.3 |
| class / class | Deadmines | 2 | 0 | 4.5 |
| spec / spec | Deadmines | 1 | 0 | 5.0 |

By who picked the composition: `both` 6 cleared of 51 that went in; `heuristic` 0 of 24; `jev` 0 of 2.

Wailing Caverns: 48 runs over the table's life, 0 cleared (14 wiped, 9 abandoned or timed out, 25 never in). By who chose it:

| chosen | Jev's vote | recorded as | runs | Jev confidence | cleared |
|---|---|---|---|---|---|
| wailing | wailing | both | 30 | 0.02 to 0.64 | 0 |
| wailing | deadmines | heuristic | 13 | 0.00 to 0.35 | 0 |
| wailing | ragefire | heuristic | 5 | 0.65 to 0.82 | 0 |
| deadmines | deadmines | jev | 4 | 0.60 to 0.88 | 0 |

The 2026-10-04 case (runs 190 to 211, 16:56 to 21:09 ET): Jev voted Deadmines 7 times at 0.04 to 0.22, under its 0.6 floor, and the heuristic sent the group to Wailing Caverns each time. Those 7 went 3 wiped, 1 abandoned, 1 lost, 1 not entered, 1 refused. Twice Jev voted Deadmines at 0.60 and 0.88 and acted: 1 wiped, 1 abandoned. Every one of these groups was class-tank or class-healer. The door was not the deciding variable; the group was. Neither picker had the option that would have helped, which is not to send that group.

Five runs where Jev voted Ragefire at 0.65 to 0.82 still went to Wailing Caverns as `heuristic`: Ragefire was not in `fits` for the chosen composition, so `can_act` was False. That is correct behavior and worth saying in the line, which today reads as if Jev lost a vote.

### Why the heuristic kept picking a 0-of-48 door

`guildrun.heuristic_door` only weighs a door with at least `MIN_SAMPLES` (3) runs. It returns the best such door when the level-fit door itself has fewer than 3 runs. So a door with a long losing record (Wailing Caverns, smoothed 0.02 to 0.14) beats an untried door (Deadmines, smoothed prior 0.5) every time. The smoothing gives an untried door 0.5; the comparison never uses it. The heuristic exploits a known failure instead of exploring.

Three more defects in the loop:

1. `door_rate` uses the exact composition key when it has any runs, and `ROLLING` is 20 per (door, band, composition). The record shown to Jev is often "0 cleared of 5" for one member list instead of "0 cleared of 48" for the door at that band. The evidence is split into slivers.
2. `rates` drops refused, not entered and lost runs. Ragefire 10-14 ran 92 times with 0 clears and 72 never got in, yet its record stayed "no runs yet" and Jev chose it at 1.0. A door that the finder will not open for a band is the strongest signal there is, and it is thrown away.
3. With `on_agreement=True`, 30 Wailing Caverns runs at confidence 0.02 to 0.64 are recorded `dungeon_by=both`. A read of `overseer_guild_run` by chooser credits Jev with picks it rated a coin flip or worse.

### The guild door has left Jev entirely

`guildsocial` ([#574](https://github.com/quadseven/wow-overseer/pull/574), merged 2026-10-04 21:11 ET, live since 21:44 ET) is on by default. With it on, `_guild_run_once` and `guildrun.decide` do not run. A group forms from a member's ask for a door it needs (`_start_social_run` writes `dungeon_by='ask'`, `composition_by='answers'`). The social layer reads the doors and the shield gates from `guildrun` but not `rates`, and asks Jev nothing. guild_dungeon and guild_composition are now dormant kinds, and the door record no longer steers any door.

## Does Jev learn from outcomes?

Not in the model. TypeSafe's Jev is stateless per request; nothing here posts outcomes back to it. Learning exists only as outcome text placed in the question:

| kind | outcome in the prompt | where |
|---|---|---|
| guild_dungeon, guild_composition | each option's cleared-of-runs and deaths at the band | `guildrun.questions` via `door_rate`, `comp_rate` |
| run_recovery, staging_stall | recent recoveries and what the next attempt did | `jev_recovery.recovery_history` |
| dungeon_choice | wiped runs per door | `jev_choices` (`wiped_runs`) |
| dungeon_step | fought, cleared and wiped since the queue entry started | `dungeonpace` |
| loot_council | none in the prompt, though `given_to` and `outcome` are recorded | `overseer_loot_council` |
| every other kind | none, and no outcome is recorded | n/a |

The kinds that override the heuristic most (item_keep 499, activity_choice 545, family_intent 450, movement 165, guild_recipient 127) are exactly the kinds with no outcome record. Nobody can tell today whether those 1,786 overrides were better or worse.

## Recommendations

### Guild runs (now the social layer)

1. Give the social layer the record. Before an ask is posted or a group forms, look up `door_rate` for the door at the band and the group's shape. Hold an ask for a door whose shape record is 0 cleared of 10 or more that went in, and say why in chat ("we keep wiping in Wailing Caverns without a real healer"). This is the guild-run gate that matters most, and it needs no Jev at all.
2. Key the record by shape, not member list: `spec-tank/spec-healer`, `spec-tank/class-healer` and so on. Today a group's exact key fragments 48 runs into slivers of 5.
3. Count refused and not entered runs per (door, band) as a separate "the finder would not let us in" rate, and close a door for a band after 5 in a row.
4. If Jev is brought back for the door, ask one Noul per candidate group and door ("this group clears this dungeon") with the shape record in the criteria, and act only above 0.6. Add a "do not run; wait for a tank-spec tank and a healer-spec healer" option to any Choice so a no-good-door situation has a right answer.
5. Fix `heuristic_door` regardless of mode: compare a door's smoothed rate to the untried prior (0.5), so a door at 0 of 10 loses to a door with no runs. Keep the level fit as the tie-breaker.
6. Record an agreement below the floor as its own value (for example `agree_low`) instead of `both`, in `overseer_guild_run` and `overseer_jev_judgment`. The action stays the same; the attribution becomes honest.

### Per kind

| kind | floor now | change the floor | inputs and criteria to add | outcome loop |
|---|---|---|---|---|
| guild_dungeon | 0.6 | keep 0.6 if revived | shape record, not-entered rate, real tank and healer presence, a "do not run" option | already recorded; key by shape; stop crediting low-confidence agreement |
| guild_composition | 0.6 | keep | shape record stated as a sentence ("groups without a tank-spec tank: 0 cleared of 12"); make the spec tank and spec healer a hard gate, not a preference | already recorded; aggregate by shape |
| activity_choice | 0.6 | raise to 0.85 for `sell` over `campaign` or `quest`, or set that pair to shadow, until outcomes exist | free bag slots against the vendor-trip cost; how long the campaign has waited; the campaign's next door | record, per decision, bag slots freed and minutes until the campaign resumed |
| movement | 0.75 | set to shadow: confidence carries no signal (37% to 46% agreement in every bucket) | distance and time apart, whether the straggler is moving, whether the leader is in combat | record whether the family regrouped within 5 minutes |
| family_intent | 0.7 | keep; review after outcomes exist | the time the current intent has run, the last outcome of the same intent | add an outcome column to `overseer_family_intent` (completed, abandoned, superseded) and put the last few in the prompt |
| item_keep | 0.85 (bank, give 0.6) | keep; calibration is good (92% agreement at 0.8 and up) | whether the recipient can use the item (the `recap.verdict` gate) | record whether a given item was used or sold by the recipient within a day |
| item_disposition | 0.80 | keep; confidence above 0.8 is rare (371 of 12,817) and only 54% agree there | a slot rule for rings, necklaces and trinkets, which today reach Jev as "no slot rule covers it" | record whether an equip choice stayed equipped |
| guild_recipient | 0.75 | keep | the recipient's current item in that slot and its score | record equipped-within-a-day from `gearorigin`; feed the recipient's last few outcomes in |
| weapon_choice | 0.85 | keep; it is the best-calibrated kind | none needed | none needed |
| leveling_zone | 0.7 | keep | hours already spent in the zone and levels gained there | record levels per hour by zone and feed it into each option |
| loot_council | 0.75 | keep | the candidates' past awards | `given_to` and `outcome` already exist; put each candidate's recent awards into the prompt |
| run_recovery, staging_stall | 0.6, 0.65 | keep | already carries history | already fed back; this is the pattern the others should copy |
| raid_supply | 0.6 | none; it agrees 99% at 0.3 to 0.6 and never acts | n/a | n/a |
| dungeon_choice, dungeon_step, quest_pick, profession_choice | as is | too few rows (3 to 9) to judge | n/a | revisit at 50 rows |

### The general feedback loop

The pattern that works is `jev_recovery`: record what followed each decision, then show the next question the recent outcomes of the same kind of choice. Extend it in this order, by override volume times stakes: activity_choice, family_intent, movement, guild_recipient. Each needs one outcome field written by the pass that can observe it, and one line in the option criteria that summarizes the last N outcomes for that option. Until a kind has an outcome, its floor should be judged by agreement calibration alone, and a kind whose confidence does not track agreement (movement, and activity_choice at the top bucket) should not act on disagreement.

Jev is used widely and answers reliably, but it does not learn from outcomes except where a caller writes the record into the prompt, and on the 2026-10-04 guild runs the deciding variable was the group's tank and healer, which no door choice could fix.
