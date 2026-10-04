# Upstream rebase: what breaks when our forks and patches move to today's heads

Resolves [wow-overseer#513](https://github.com/quadseven/wow-overseer/issues/513), workstream B of [wow-overseer#512](https://github.com/quadseven/wow-overseer/issues/512).
Researched 2026-10-04 (America/New_York). Every result below comes from a local trial in a throwaway clone: `git rebase` / `git cherry-pick` for the forks, and a real `git apply --whitespace=error -p1` per patch in filename order (no fuzz, the same matching the image build uses). Nothing was pushed, no fork or pin changed, and the realm was not touched. No worldserver compile was run; compile verdicts below come from reading the headers and call sites at each ref.

## Answer in brief

Today's upstream heads are a coupled break, not a patch-apply problem. On 2026-10-01/02 the playerbots core (`Playerbot` branch) and mod-playerbots `master` landed a paired change that deletes the fork-only core API: `WorldSession::IsBot()` becomes `IsHeadless()`, the whole `PlayerbotScript` hook class goes, and `Player::IsInChannel` / `BotCanUseItem` go with it. So the core and the module can only move together, and once they do, five other things stop compiling: patches 0027 and 0028, mod-overseer at its pin, mod-dungeon-clear at its pin, and mod-ollama-chat at its pin. Against the rebased trees, 28 of 31 mod-playerbots patches still apply byte-exact. Three conflict: 0004 is dead weight because upstream #2638 fixed the same loop, and 0027 and 0028 still matter but need a rebase onto the new API. The mod-dungeon-clear image patch 0001 is dead weight because it is already upstream. The mod-dungeon-clear fork rebases onto jrad7 `master` with 8 of 13 commits hitting small conflicts of 1 or 2 hunks each. A nightly job must trial the core, the module and every other module together as one tuple, compile them, and gate on DB-update names and a boot-and-shutdown smoke test. Patch-apply alone would have reported 3 failures and missed all five compile breaks.

## 1. Heads trialled

| tree | pin | head trialled | pin vs head |
|---|---|---|---|
| core mod-playerbots/azerothcore-wotlk `Playerbot` | `7f12e89e` | `f19a1879` (2026-10-02) | 62 behind, 0 ahead |
| quadseven/mod-playerbots (fork) | `7a593fa2` | upstream `master` `037c0141` (2026-10-02) | 34 behind, 2 ahead (the two fall-damage commits) |
| quadseven/mod-dungeon-clear (fork) | `427e7007` (branch `fix/rez-needs-mana-on-pin`) | jrad7 `master` `60f3d98` (2026-10-01) | 45 behind, 13 ahead of merge-base `c32a384` |
| DustinHendrickson/mod-ollama-chat | `4befe61d` | `a9966f3e` (2026-10-02) | 4 new commits |
| mod-junk-to-gold, mod-ah-bot-plus | unchanged | unchanged | 0 |

The weekly trial in infra#4849 (2026-09-29) reported core and module "nothing new" and is now stale. All of the breaking movement landed after it ran.

## 2. The coupled core and module break

Core commits between the pin and head that matter ([azerothcore-wotlk compare](https://github.com/mod-playerbots/azerothcore-wotlk/compare/7f12e89ee5f467a50e62eba1d525eac7dc953d03...f19a18799a35f7c24bdcdc9ea399c601f166259b)):

- `92fed92e` headless sessions and session-less APIs (#27533). `WorldSession::IsBot()` is removed and `IsHeadless()` replaces it (`src/server/game/Server/WorldSession.h:1234` at head).
- `6792c7de` SessionScript hooks (#27531), `ff8d1177` merge of `pr/module-db-async`.
- In `ScriptDefines`, the `PlayerbotScript` class and all its `OnPlayerbot*` hooks are deleted, along with `CanPacketReceive`/`OnPacketReceived`. `OnPacketSent`, `OnSessionUpdate`, `CanCreateLfgProposal` and others are added.
- In `Player.h`, `BotCanUseItem`, `SetMovement`, `IsInChannel` and `ResetSpeakTimers` are removed.

mod-playerbots commits paired with that ([compare](https://github.com/mod-playerbots/mod-playerbots/compare/7bae1b5c58c7...037c01418b5d01506917a3db9b44fd56ac5f965c)): `56a0f383` "Remove unnecessary custom hooks" (#2765), `cc54f8f2` "Replace fork-only core calls" (#2820), `1e5add88` "Change bot to headless... new packet handler" (#2792), and `b0cd0ea7` "Align with async modular database" (#2830).

Consequences:

- Neither pairing across the boundary compiles. The module pin calls `IsBot()` (3 files), which the core head no longer has. The module head calls `IsHeadless()`, which the core pin does not have. The pair moves as one bump or not at all.
- **mod-overseer `ec7645a4` will not compile on the core head.** `OverseerFinderScript` derives from `PlayerbotScript` and overrides `OnPlayerbotPacketSent` (`src/mod_overseer.cpp`, around line 64600), and seven `session->IsBot()` uses sit in five statements. The fix is the upstream-hook equivalent (`ServerScript::OnPacketSent(WorldSession*, WorldPacket const&)`) plus `IsHeadless()`.
- **mod-dungeon-clear `427e7007` will not compile on the core head.** It uses `PlayerbotScript`/`OnPlayerbotUpdate` (`src/DungeonClearModule.cpp:471`) and `Player::BotCanUseItem` (`BetterLootRollAction.cpp:191`). jrad7 `master` already carries a compile-time shim for both cores (`Util/DcCoreCompat.h`, commit `cd925653`), so the rebase in section 4 fixes this.
- **mod-ollama-chat `4befe61d` will not compile on the core head.** It uses `session->IsBot()` and `Player::IsInChannel`. Upstream fixed both on 2026-10-02 (`4e3d4c8`, `cafa6f7`), so the pin must move to `a9966f3e` in the same bump.
- mod-junk-to-gold and mod-ah-bot-plus use none of the removed symbols.
- There is a semantic trap behind the compile break, recorded in jrad7's `DcCoreCompat.h`: after #2792, bot sessions no longer pass `is_bot`, so on any tree where `IsBot()` still exists it silently reads false for bots. Today the core deletes it, so the failure is loud. A shim that falls back to `IsBot()` must not be trusted on a mixed tree.

## 3. mod-playerbots fork and patches

### Fork rebase

The two fork-only commits (`5473d433`, `7a593fa2`) rebase onto upstream `037c0141` with no conflict. The earlier `CompleteDismount` conflict with upstream #2754 does not recur.

### Patches, in order, on the rebased fork (exact apply)

28 of 31 apply. As a control, all 31 apply on the current pin.

| patch | result on head | verdict |
|---|---|---|
| 0004 loot-needs-a-free-bag-slot | conflict at `LootObjectStack.cpp:315` | **Dead weight. Delete.** Upstream `ddf54880` "Fix/infinite gathering loop" (#2638) inserts a gathering-node guard at the same spot in `LootObject::IsLootPossible`. It refuses herb, mining, skinning and engineering nodes when bag usage is over 80% and no real player is the master. That covers the 0-free-slot case 0004 targets, and more. Behavior change: bots now stop gathering at 80% full, not at 100%. A selfbot leader still counts as "no real player master", because it has a PlayerbotAI. |
| 0027 a-headless-selfbot-finishes-its-own-teleport | conflict at `PlayerbotAI.cpp:791` | **Still needed. Rebase.** The textual conflict is only #2815 renaming the comment "selfbots" to "SelfBots". Upstream `HandleTeleportAck` (`PlayerbotAI.cpp:780` at head) still returns early for any selfbot. The patch's `GetSession()->IsBot()` must become `IsHeadless()`, or it will not compile. |
| 0028 a-headless-selfbot-is-logged-out-at-shutdown | conflict in `PlayerbotMgr.h:42` and `Playerbots.cpp:518` | **Still needed. Rebase.** The hook it extends, `OnPlayerbotLogoutBots`, no longer exists. Upstream now logs bots out from `WorldScript::OnShutdown` (`Playerbots.cpp:546` at head). `PlayerbotHolder::LogoutAllBots` (`PlayerbotMgr.cpp:323`) still skips every selfbot, so the instance-unload crash this patch prevents is still reachable. Move the call into `OnShutdown` and swap `IsBot()` for `IsHeadless()`. Re-prove it with a graceful shutdown while a headless tank stands in an instance. |
| 0001-0003, 0005-0026, 0029-0031 | apply byte-exact | Keep. No upstream commit in the range retires them. Checks on the likeliest overlaps: #2781 adds `HasQuestForItem` to `IsItemUsefulForQuest` but does not reorder `ItemUsageValue::Calculate`, so 0021 stays. Upstream `SayToGuild` still calls `BroadcastToGuild` with no script hook, so 0018 stays. `SayToParty`/`SayToRaid` still send only to real players, so 0020 stays. #2770 touches `LootRollAction.cpp` but not the region 0022 patches. |

Notes for the bump commit:

- 0005 and 0022 add API that mod-overseer calls. Both apply cleanly, so nothing changes there.
- 0017 restores a caller into `GuildTaskMgr`, and #2830 changed `GuildTaskMgr.cpp` to the async DB pool. The patch applies, but guild tasks should be re-checked on the dev realm.
- #2830 turns the playerbots DB pool asynchronous (`PlayerbotsDatabase.h`: queued `Execute`/`CommitTransaction`). mod-overseer reads that pool for travel routes and moorings. Writes made by playerbots are no longer visible to a read in the same tick.
- 0023 retires on DB state (no rogue row still stored under the old strategy names), not on upstream code. It is unaffected.

### Next wave already visible: mod-playerbots PR #2747

[mod-playerbots#2747](https://github.com/mod-playerbots/mod-playerbots/pull/2747), "Refactor bot movement and travel", is open against `test-staging` and touches 35 files. Trial: PR head merged with `master`, plus the fork commits (both clean), plus the patches. That breaks 0004, 0027 and 0028 (as above), plus **0006** (`NewRpgBaseAction.cpp:237`, `.h:36`) and **0029** (`NewRpgBaseAction.cpp:103`). In all, 18 of the 31 patches touch a file #2747 modifies. jrad7 `60f3d98` already builds mod-dungeon-clear against both movement APIs. It also drops the exact-waypoint retry ("a refusal now stands"), which changes dungeon movement for us on either API.

## 4. mod-dungeon-clear fork and patch

### Rebase of the deployed branch onto jrad7 `master`

The 13 commits from `c32a384` to `427e7007` were cherry-picked in order onto `60f3d98`. Each conflict was counted, then resolved toward our side so the rest of the stack could be measured in context:

| commit | result |
|---|---|
| `b9bdae0` testrun driver login | clean |
| `cf2dbba` tankless party led by group leader (#2) | 1 hunk, `DungeonClearChatActions.cpp` (upstream added the BRS/BRD wing note on the same lines) |
| `7afd5c5` leader in another copy, yield flood (#3) | 1 hunk, `DungeonClearChatActions.cpp` |
| `08868d0` live raid wipe disables (#4) | clean |
| `dec6224` Leeroy ceiling and rez mana gate (#5) | 1 hunk, test file only |
| `f3daa96` stalled fallback budget (#6) | 1 hunk, `DcApproachState.h` |
| `55f9bdf` hold and corpse-run (#7) | 2 hunks, `DungeonClearChatActions.cpp` and a test |
| `d371104` rests and pulls by role readiness | 1 hunk, test file only |
| `b50af98` boss mana floors (#11) | clean |
| `8646cc3` tank mana waits (#12) | clean |
| `d51b18f` wing-scoped encounter mask (#14) | 1 hunk, `DungeonBossInfo.h`: upstream's new `AnchorDoneByInstanceValues` sits beside our `DungeonBossesExpectedEncounterMask`. Keep both, but review it against upstream's own BRS/BRD wing split (`d3b06b8`, `b501c63`). |
| `0392224` corpse-run state (#13) | clean |
| `427e700` at-boss hold says why (#15) | clean |

None of the conflicts is a disagreement about behavior. All are adjacency conflicts that keep-both resolves. After the rebase, the only remaining reference to a removed core API sits behind `#ifdef DC_CORE_HAS_ON_PACKET_SENT`, which is jrad7's shim.

The drift report (infra#4848) found the same split: production follows `fix/*-on-pin` branches, dungeon features land on jrad7 `master`, and quadseven `master` is a third line (26 behind jrad7, 3 ahead). Rebasing onto jrad7 `master` reconciles the lines and also brings in the core-compat shim the coupled bump needs.

### Image patch

`mod-dungeon-clear/0001-boss-index-thread-safe-init.patch` reverse-applies on the rebased tree. **Dead weight. Delete it.** It is jrad7 `b5ccac1`. infra#4849 reached the same verdict.

## 5. DB and config changes a bump carries

- Core: 20 new `db_world` update files between the pins. None for auth or characters.
- mod-playerbots: 2 new `playerbots` updates (`2026_09_13_00_ai_playerbot_target_requester_text.sql`, `2026_09_21_00_playerbots_speech.sql`). Commit `5824bc82` (#2835) also renames 4 base files to a `0000_` prefix: `playerbots_names`, `playerbots_guild_names`, `playerbots_arena_team_names`, `playerbots_rpg_races`. Its own message says the core applies world and character module SQL "as a flat list", so on an existing DB the renamed files count as new and re-run. Each one does `DROP TABLE IF EXISTS` and then recreates and reseeds. mod-overseer and the patches do not reference those tables, but the reseed is a real write on upgrade, and a count of "new update files" would not show it. `charsections_dbc.sql` and `emotetextsound_dbc.sql` are deleted, because the core now loads those DBCs (`0126bc3c`).
- `conf/playerbots.conf.dist` adds `AiPlayerbot.AddClassRandomCharacter` and `AiPlayerbot.AnnounceConsumableUse` (default 1; set 0 to silence eat and drink whispers). No keys are removed.

## 6. What a nightly rebase-and-adopt job must check

The existing pair, `check.wow-upstream.yml` (drift) and `check.wow-upstream-trial.yml` (weekly trial, infra#4849), does most of this. The gaps found here are marked NEW.

1. **Trial the whole tuple, not each pin alone.** Core head + module head + every extra module at its own head + mod-overseer at its pin. NEW: today's break is invisible to any per-repo check.
2. **Use the true upstream for every fork, and carry the deployed commits.** NEW for mod-dungeon-clear: the weekly trial took quadseven `master` as "head" and left out the pin's own commits. It must rebase the deployed branch onto jrad7 `master`, and report per commit as clean, conflict (with hunk count), or dropped as already upstream.
3. **Apply every patch byte-exact in order and classify each one.** Applies; already merged (reverse-applies, so delete); or conflict. NEW: on a conflict, list the upstream commits that touched the conflicted lines (`git log -L` over the hunk range). 0004 is the case where upstream fixed the same defect with different code, which reverse-apply cannot detect.
4. **Compile the worldserver with all modules at the trial tuple.** This is the only gate that catches the five breaks in section 2. Also keep a symbol scan as a fast pre-check: removed core and module declarations (diff of `ScriptDefines/*.h`, `WorldSession.h`, `Player.h`, module headers) grepped across mod-overseer, the patches and every module, so the report names the file and line before a 90-minute compile.
5. **Run mod-overseer's decision tests at the trial tuple** (182 of 182 at infra#4849).
6. **Diff DB update file NAMES, not counts.** Flag renames and any base file that would re-run on an existing DB. Run `db-import` against a clone of the dev databases and fail on any error.
7. **Diff config keys.** Report keys added to or removed from `playerbots.conf.dist` and every module's dist file, and fail if a realm overlay sets a key that no longer exists.
8. **Smoke-test the image before adoption.** Boot against the DB clone, log bots in, far-teleport a headless selfbot (0027), and shut down gracefully with a headless selfbot inside an instance (0028). Fail on any assert or crash.
9. **Watch the next wave.** Also trial mod-playerbots `test-staging` and the open PRs that touch patched files (today, #2747). Report it as early warning only, never as adoptable.
10. **Adopt by pull request, never by a direct pin push.** Pins, patch deletions or rebases, and module call-site changes go in one commit, and that commit carries the trial image digest. The realm roll stays a separate, gated step. Any red gate means no adoption and a report.
11. **Keep one source of truth.** NEW: this repo carries its own `UPSTREAM-PINS.env` and `patches/`, last touched 2026-10-02, with older SHAs than the image build and 3 of the 31 patches. The job should either regenerate that copy or fail when it drifts from the build's pins.

## 7. The adoption, if made today

One bump that moves, in a single change:

- Core to `f19a1879` and the module fork to the rebased `037c0141` plus 2 fork commits.
- Delete `mod-playerbots/0004` and `mod-dungeon-clear/0001`. Rebase `0027` and `0028` onto `IsHeadless()` and `OnShutdown`.
- mod-ollama-chat to `a9966f3e`.
- mod-dungeon-clear to the deployed branch rebased onto jrad7 `master`, with the 8 conflicts resolved keep-both.
- mod-overseer moved off `PlayerbotScript` and `IsBot()`.

Then the gates in section 6.
