# Rolls: shipping the bridge and the worldserver to the dev realm

This is the procedure for putting merged code on the live dev realm and proving it worked. It is written
so an orchestrator with no memory of earlier rolls can run it. The deploy repository is private; it is cited
bare as infra#N. Do not add hosts, addresses, node names or credentials to this file.

Two things ship, and they have different costs:

| Ship | What changes | What restarts | Where the digest is pinned |
|---|---|---|---|
| Bridge and site | `wow-overseer` main (bridge.py, map_server.py, apiv2/, app/) | the `wow-overseer` and `wow-map` deployments | the `ghcr.io/quadseven/wow-overseer` image in the wow-dev kustomization (infra) |
| Worldserver | mod-overseer, mod-dungeon-clear, core, playerbots, ollama-chat | the `worldserver` deployment (every online bot logs out) | the `ac-playerbots-worldserver` and `ac-playerbots-db-import` images in the same kustomization, plus the source pins |

A bridge ship is cheap and can be batched often. A worldserver roll is expensive: every family and guild run
inside an instance is lost, so it is rate limited and gated (section 2).

Merging a PR here deploys nothing. Label a merged-but-not-deployed ticket "merged"; "shipped" means it is on
the realm and its proof line was seen (section 3).

## 1. Steps

### 1a. Bridge ship (one restart for a batch of merged PRs)

1. Confirm the batch is merged to wow-overseer main and nothing else is queued. Read section 2 first.
2. Find the `build.yml` run for the exact merge commit of main (`gh run list -R quadseven/wow-overseer
   --workflow build.yml --branch main`, match `headSha`). If none exists after 5 minutes, dispatch it. Wait for
   it to pass; rerun failed jobs up to twice.
3. Read the digest from that run's log: the line `sha-<first 12 of the SHA>: digest: sha256:<64 hex>`. Do not
   take a digest from anywhere else.
4. In infra, branch from `origin/main` (a worktree, never the shared checkout) and edit the one stanza in
   `production/oke/manifests/wow-dev/kustomization.yaml`:

       # Published from wow-overseer <what shipped, e.g. #857 and #858>, merge <10 chars>, build run <run id>.
       - name: ghcr.io/quadseven/wow-overseer
         newName: ghcr.io/quadseven/wow-overseer
         digest: sha256:<new digest>

5. Render it (`kubectl kustomize production/oke/manifests/wow-dev`), commit, open the infra PR in Chief format
   (section 5 of the repo's PR rules below), wait for checks, answer every bot thread, then squash merge.
6. Merging triggers `sync.k8s-manifests`, which applies the wow-dev directory. Wait for
   `kubectl -n wow-dev rollout status deploy/wow-overseer` and confirm the deployment image equals the new digest.
   `wow-map` runs the same image and rolls with it.

### 1b. Worldserver roll (one restart for a batch of module changes)

A roll is five steps that must land as ONE worldserver restart.

1. **Merge the module PRs** (mod-overseer, mod-dungeon-clear) after checks pass and every bot thread is
   answered. Record the new main SHA of each. mod-dungeon-clear is pinned to the head of its deployed fork
   branch, not main.
2. **Bump the source pins only** in an infra PR from a fresh worktree. Exactly three source locations move:
   - `production/docker/azerothcore-playerbots/UPSTREAM-PINS.env` (`AC_OVERSEER_SHA`, `AC_DUNGEON_CLEAR_SHA`,
     and `AC_CORE_SHA`, `AC_MODULE_SHA`, `AC_OLLAMA_CHAT_SHA` when those move);
   - the mod-overseer submodule gitlink under `production/docker/azerothcore-playerbots/` (set it with
     `git update-index --cacheinfo 160000,<sha>,<path>`);
   - the `"dev"` fields of the matching entries in `.github/scripts/wow_promotion_drift.py`.
   Check `git status --short` shows exactly those three paths. The banner (`overseer-pin.yaml`),
   `deployed_dev` and the banner test literal move with the IMAGE in step 4, not here, so this PR restarts
   nothing. Run the wow-dev tests, the promotion tests and `python3 .github/scripts/wow_promotion_drift.py`
   ("All four views agree"). Merge it. This merge starts the image build workflow
   (`build.azerothcore-playerbots.yml`).
3. **Read both digests from the build run's push lines**, each under its own `The push refers to repository
   [ghcr.io/quadseven/<image>]` line: `ac-playerbots-worldserver` and `ac-playerbots-db-import`. A digest read
   from the wrong repository line is the classic mistake.
4. **Prove the binary** before pinning: run a throwaway pod on the worldserver digest in wow-dev (same pull
   secret as the worldserver deployment, amd64 node selector) that greps
   `/azerothcore/env/dist/bin/worldserver` for a string or symbol unique to each change (a function name or log
   text from the diff). Every string must be found. A build that lacks the symbol is a stale layer: do not pin.
5. **Pin the pair** in a second infra PR: in `wow-dev/kustomization.yaml` set the worldserver AND db-import
   digests together (the worldserver comment block stays 3 lines), and move the banner
   (`production/oke/manifests/wow-dev/overseer-pin.yaml`), `deployed_dev` in the drift entries and the banner
   test literal in `wow-dev/tests/test_dev_world_isolation.py` to the new SHAs. Pinning one image without the
   other is a binary asking for a table its schema step never created; the drift check fails on it. Run the
   drift check again, open the PR in Chief format, then merge it ONLY inside the window in section 2.
6. Watch `kubectl -n wow-dev rollout status deploy/worldserver` and confirm the running image equals the new
   worldserver digest. The db-import job runs the module SQL first.

The same sequence is encoded for automation as the realm roller (`realmroller.py`, `realmroller_plan.py`,
`realmroller_act.py`, `realmroller_world.py`, `tools/realm_roller.py`; formats in `tools/realm_roller_example/`).
Its channel and release files live in infra under `production/realm-roller/wow-dev/`. As of 2026-10-12 the
channel is PAUSED and its seed releases are stale (it needs a GitHub App, infra#5027, an operator step), so run
the steps above by hand. `tools/realm_roller.py validate` and `dry-run` are read-only and safe to run: dry-run
prints the gates it sees and what it would do. Turning the roller on is an operator decision.

## 2. Before any ship

### Is a family or guild run inside a dungeon?

Read the site API from inside the cluster (read-only). From a pod that has `python3` (for example
`kubectl -n wow-dev exec deploy/wow-map -- python3 -c ...`):

- Families: `GET /api/family?family=Grug` and `...=Zug` on the map server (port 8080). Count members whose
  `instance` is set. The hard rule is zero for BOTH families.
- Guild runs: `GET /api/guildruns`, field `active`. Zero is preferred.
- Cross-check in the database with a SELECT on `acore_characters.overseer_guild_run` (state `inside`) and
  `overseer_dungeon_run` (open runs), as `mysql-0` read-only. Never write.

### Rules for a worldserver roll

- At most one worldserver roll per hour (measure from the previous roll's pin merge).
- Never roll while a family member is inside an instance. A family stalled inside a dungeon for hours does not
  block a roll (operator decision); confirm it is truly stalled (same instance, no kills; #743, #832) before
  using that exception, and say so in the PR.
- Prefer zero guild runs inside. Wait up to 60 minutes of open window for them to clear, then roll anyway so a
  busy guild cannot block every roll. A restart loses a run inside it.
- Batch changes. Do not roll for a single trivial fix if another is about to merge.
- A bridge ship needs families out of instances and is best with zero guild runs, but it never restarts the
  worldserver. Batch bridge ships too: after a restart the passes wait for the passes they depend on, so each
  restart idles the realm for a cycle or more (the gates open at the latest after 30 minutes of uptime).

### What blocks a roll

Any of: a family member inside an instance (unless stalled, above); a roll in the last 60 minutes; failing
checks or an unanswered bot thread on the infra PRs; the drift check disagreeing; the prove step missing a
symbol; a worldserver/db-import pair that does not come from one build; an open pre-roll review finding;
the operator having said hold.

### Pre-roll adversarial review (every worldserver roll and every bridge ship)

Spawn a reviewer, or do it yourself, with the full diff of every change in the batch. The question is not "is
the diff correct" but "what happens next in the live sequence". For each change, walk it end to end through the
real code of the module, the core, playerbots and the bridge, and write down:

1. The exact sequence the realm will execute after the restart (who is online, what state is loaded, what each
   pass does first).
2. What state survives a restart: database rows, in-memory maps, groups, claims, lfg data, leader assignments,
   timers. Earlier rolls lost runs because a claim expired, a group disbanded on bot login and the core deleted
   `lfg_data` for type-8 groups: three layers found one roll at a time. Look for the next layer now.
3. What the change does to a member who is mid-action (walking, in combat, dead, in a dungeon, trading).
4. Whether the new log line that will prove it is emitted on the success path and not before the work happens.
5. Whether it breaks any rule in section 4.
6. Whether the tests fail without the fix.

Fix blockers in the same batch. File every smaller finding as a ticket with `Part of #<epic>`. Do not roll
until the reviewer reports ship.

## 3. After a ship

### Proof

A ticket closes only when BOTH hold: the change's proof log line appeared on the live realm AND the targeted
metric moved. Name both in the ticket before the roll. Typical proof sources:

| Change type | Where to look | Proof |
|---|---|---|
| Bridge pass logic | `kubectl -n wow-dev logs deploy/wow-overseer` | the new log line text from the PR; no traceback after the restart; no heartbeat warning |
| Worldserver module behavior | `kubectl -n wow-dev logs deploy/worldserver -c worldserver` | the module's log text from the diff (for example the line a reroute prints); no `ASSERTION FAILED` |
| Database or schema | read-only SELECT on the table the change writes | rows appear or counts move |
| Site and API | the site API from inside the cluster | the field or view returns the new shape |
| Progression | `overseer_death`, `overseer_dungeon_run`, `overseer_guild_run`, level counts per guild | deaths down, runs and clears up over the window |

The read-only identity for agents is the `wow-agent-reader` ServiceAccount in wow-dev; mint an expiring token
(`kubectl -n wow-dev create token wow-agent-reader --duration=24h`) instead of keeping a standing one. A
metrics snapshot per guild (online, median level, count at 20/40/60, runs, clears, class-quest done and
blocked, ghosts, stuck, deaths in 24 hours, next dungeon) before and after a roll is the standard comparison.

### How long to watch

- Bridge ship: 30 minutes for tracebacks and the proof line; the gates open within 30 minutes of uptime.
- Worldserver roll: 30 minutes for the restart and bot login (online count back near its normal level), then
  two hours of death and run counters before calling a behavior change verified. A claim that needs a full
  guild run to prove (a boss kill, a reroute under real load) can take longer; keep the ticket open.
- Close after the evidence, never before. Tick the acceptance boxes first, then close with the evidence.

### Rollback

- Bridge: revert the infra pin PR (restores the previous `wow-overseer` digest) and let the sync apply it.
- Worldserver: revert the pin PR (restores BOTH previous digests; they are a pair). Module SQL is forward-only,
  so before a roll that adds schema, confirm the previous binary tolerates the new tables.
- Roll back on: more than 2 worldserver restarts in 30 minutes, an `ASSERTION FAILED` or segmentation fault in
  the log, or online bots below half of normal for 10 minutes (the roller's policy).
- After a rollback, hold further rolls until a finding explains the failure.

## 4. Rules that never break

- Natural progression only. No granted levels, gear, skills, buffs, gold or seeded items for guild members.
  Factory random-bot raiders are unearned and must not be used as seats.
- Never cancel or stop a campaign. A campaign that looks stuck is diagnosed and adapted; an automatic stop is a bug.
- The operator's approved 40-seat raid lineups stay as they are. A change to a seat needs the operator.
- Level order is per faction: Cave (Alliance) never runs Ragefire Chasm, and Bonkers (Horde) never runs the
  Stockade.
- No respecs; the raid spec plan stands. A missing tank or healer is filled by a PUG from the server.
- Class quests come first for every class (the mandatory quests), ahead of leveling throughput and raid prep.
- The coupled pins move together: the five source pins (`AC_CORE_SHA`, `AC_MODULE_SHA`, `AC_OVERSEER_SHA`,
  `AC_DUNGEON_CLEAR_SHA`, `AC_OLLAMA_CHAT_SHA`; core, playerbots and ollama-chat move as a set), the
  mod-overseer gitlink, the drift entries, the banner and its test literal; and the worldserver and db-import
  digests always come from one build and change in one PR.
- Public repos: no hosts, addresses, node names, personal names or credentials. Cite the private repo bare
  (infra#N). Never write the bot handle with an at-sign; the bot is the `grug-tribe` app and its commands are
  `/grug improve` and `/grug recheck`.
- PR bodies use `Refs #N` and never a closing keyword near an issue number, even negated. ASCII only, no em
  dashes. Commits end with the session trailer; PR bodies end with the session link.
- No secrets in output, files or logs. No realm writes except by shipped code.
- Close tickets only after live verification, and tick the boxes first.

## 5. What needs the operator anyway

- Anything that deletes data: the post-merge steps of infra#5016 (deleting the retired live and hardcore
  namespaces, the retained backup volume and the NAS dumps) stay on hold until the operator names them.
- Turning the realm roller on (infra#5027, the GitHub App) and unpausing its channel.
- A change to a raid seat, a respec, or any granted progression.
- Credentials: the Cloudflare token, the decision-model keys and quotas (HTTP 402 on Jev, #797), any rotation.
- The core, playerbots and ollama-chat upgrade (#826): a large roll with database migrations, run as a watched
  roll with a rollback plan.
- Pruning decisions on shared data (mod-overseer#908) and any destructive realm query.
- Anything that cannot be undone, or that is visible outside the repos (announcements, public posts).

## Appendix: PR format the Grug checks require

Agent-authored PR bodies need the headings `## Why`, `## Summary` (or `## What`), `## Acceptance` with exactly
three `- [ ]` boxes, a `Size:` line, `## Out of scope`, and the session link as the final line. Answer every
bot review thread before the squash merge, and resolve it. `/grug recheck` re-runs the Chief check only.
