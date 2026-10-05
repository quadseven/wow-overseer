# Realm roller prototype

PROTOTYPE for [#522](https://github.com/quadseven/wow-overseer/issues/522), decision 9 of [#511](https://github.com/quadseven/wow-overseer/issues/511), workstream A of [#512](https://github.com/quadseven/wow-overseer/issues/512). Nothing here is wired up or deployed. It exists for the operator to react to.

Stubs:

- [`realm-roller/release.example.yaml`](realm-roller/release.example.yaml): one release manifest.
- [`realm-roller/channel.dev.yaml`](realm-roller/channel.dev.yaml): the dev channel, its gates and rollback rules.
- [`realm-roller/roller.py`](realm-roller/roller.py): one roller tick as a pure function. `python3 -B prototype/realm-roller/roller.py` prints four sample decisions.
- [`realm-roller/status.html`](realm-roller/status.html): a static mock of the status tab.

## What a roll costs today

The manual process is a chain of shell scripts, each step gated with `|| exit 1`:

1. Merge the module PR (mod-overseer, mod-dungeon-clear) after its checks and bot threads settle.
2. Open a **bump** PR in the deploy repo: the source pin, the submodule gitlink and the drift entry `dev`. Its merge starts the image build.
3. Wait for the build, read the worldserver and db-import digests out of the build log (each under its own push header), and run a throwaway pod on the new worldserver image that greps the binary for the new code.
4. Open a **pin** PR: both digests, the banner, `deployed_dev` and the banner test literal, together. Fold any config-only change (the AH bot off, infra#4992) into the same diff.
5. Merge the pin no earlier than an hour after the last roll, and only while no Grug or Zug family member is in a dungeon.
6. Wait for the rollout, then read the live log for the change.

Two lessons are baked into the scripts. The banner and `deployed_dev` move with the image, never with the source, or the drift check fails for the whole build and the worldserver restarts twice. And the families-out check is a poll of the family API's `instance` field, from inside the cluster.

Each roll is two PRs, two bot-review cycles, a laptop-bound wait of one to three hours and a hand-written log check. The roller keeps every gate and removes the rest.

## 1. Release

A **release** is a named, complete set of source SHAs plus the images one build made from them. See [`release.example.yaml`](realm-roller/release.example.yaml).

- **Name:** `rYYYY.MM.DD-N`.
- **Sources:** core, playerbots, mod-overseer, mod-dungeon-clear, mod-ollama-chat and the site. Every release lists every SHA; nothing is inherited from a branch.
- **Changes:** one entry per merged PR, each with a `prove` grep (run against the built binary) and a `verify` check (a grep that must appear, or must stay absent, in the live log within a time limit).
- **Build:** the run id and the worldserver, db-import and site digests, written by the roller.
- **State:**

```
proposed -> building -> built -> proven -> rolling -> live -> verified
               |          |                  |         |
               v          v                  +----+----+
         build_failed  prove_failed               v
                                             rolled_back
```

The key change from today: the build is dispatched with the release's SHAs as inputs, not triggered by a bump merging to main. Source pins, digests, banner and `deployed_dev` then land in **one** deploy-repo commit. That commit is the roll. The bump PR disappears, and the drift check sees all four views move together.

## 2. Channel and how a release is adopted

The **dev channel** ([`channel.dev.yaml`](realm-roller/channel.dev.yaml)) names `current`, `previous` (the rollback target, always a verified release), a `queue`, a `paused` flag and the policy.

A **roll** adopts the head of the queue:

- **One restart per release.** The roll commit carries everything the worldserver needs. Config-only changes (like the AH bot switch) join a release as a change entry and ride its restart.
- **Coupled pair.** worldserver and db-import digests come from the same build run, are written in the same commit, and are never rolled apart. A release without both digests cannot leave `built`.
- **Banner and `deployed_dev`** are written in the roll commit, from the release, so they always match the running image.
- **Gates,** checked in this order every tick: paused; at most one roll start per 60 minutes; the family API answered; no Grug or Zug member has a non-empty `instance`; the families have stayed out for 5 minutes. An unreachable family API counts as "inside".
- **Coalescing.** If two releases are proven while a gate holds, only the newest rolls. The older one is marked superseded, not rolled.
- **Verification.** After the new pod is Ready, the roller tails the worldserver log and checks each change's `verify` grep. All seen within the grace period moves the release to `verified`.
- **Automatic rollback** to `previous` when any of these happen: not Ready in 15 minutes; more than 2 restarts in 30 minutes; a fatal signature in the log (`ASSERTION FAILED`, `Segmentation fault`, a failed db-import); any verify grep missing after the grace period; bots online fall below half for 10 minutes. A rollback skips the hourly and dungeon gates because the realm is already broken. The rolled-back release stays in history with the reason.

Build and prove keep running while the channel is paused or gated, so a release is usually `proven` before its window opens.

## 3. Where it runs

| Option | For | Against |
|---|---|---|
| **A. CronJob in the wow-dev namespace** (tick every 5 min) | Reads the family API, pod state and logs directly, as the scripts already do from inside the cluster. Survives a sleeping laptop. Narrow RBAC: read pods and logs, create one prove pod. Not part of any release, so it never restarts itself. | A new small image and a GitHub App token that can push to the deploy repo. |
| **B. Scheduled GitHub Actions workflow** | Native git and `gh` access; run logs visible in Actions. Already builds the images. | Scheduled triggers drift and skip under load. ARC runners are evicted by the descheduler on the half hour, which kills a waiting job mid-roll. Needs cluster credentials on the runner. A 5-minute tick burns runner time all day. |
| **C. Inside the overseer bridge** | Already holds family state, and already serves the site that shows the status. | The site image is part of a release, so the roller restarts itself mid-roll. A bridge crash stops rolls and rollbacks at the moment they matter. |

**Recommended:** A for deciding and applying, with the existing build workflow kept as the builder (dispatched per release, digests reported back as job outputs instead of scraped from logs). The roller holds no state of its own: each tick reads git and the world, takes at most one action, and commits the result.

### How a person sees it

A **Roller** tab on the overseer site (mock below) reads a small `roller-status` JSON that the CronJob writes each tick: current release, rollback target, queue with each release's state and what it waits on, next window and why, the last verification line by line, and recent rolls with their commits.

### How a person stops it

- **Pause** (`paused: true` in the channel file, with a reason): build and prove continue, no roll starts. A merged one-line commit, so it is auditable.
- **Stop everything:** suspend the CronJob. No build, no roll, no rollback.
- **Pin a release:** put exactly one release in the queue and pause after it verifies.

### How each roll is recorded in git

Every state change is one commit in the deploy repo, authored by the roller's app identity:

- `roller: r2026.10.04-2 building (run 1234)`
- `roller: r2026.10.04-2 rolling` (this is the commit that changes the digests, banner and `deployed_dev`)
- `roller: r2026.10.04-2 verified (4 of 4)` or `roller: r2026.10.04-2 rolled back: never seen AUCTION_HISTORY`

`git log -- releases/` answers what ran when, and a revert of the rolling commit is the manual rollback.

## 4. Status page mock

Static HTML: [`realm-roller/status.html`](realm-roller/status.html). The same page in ASCII:

```
Realm roller: dev channel                         [ Pause rolls ]
-----------------------------------------------------------------
Current      r2026.10.04-1   verified 18:12, 4 of 4 checks seen
Rollback to  r2026.10.03-3   verified
Next window  after 20:00     one roll per hour; Grug's family is
                             in Wailing Caverns (3 members)

Queue
  r2026.10.04-2  proven    mod-overseer#838 #839, dungeon-clear#16,
                           infra#4992                 waits: window
  r2026.10.04-3  building  wow-overseer#580           waits: build 12/40m

Last verification (r2026.10.04-1)
  OK  "guild death recorded"     seen 18:04
  OK  "levelup recorded"         seen 18:09
  OK  absent "casting worldbuff" for 30 min
  OK  Ready in 6 min, 0 restarts

Recent rolls
  18:00  r2026.10.04-1  verified 18:12                 abc1234
  14:31  r2026.10.03-4  ROLLED BACK 14:48: never seen
                        AUCTION_HISTORY                def5678
```

## 5. Open questions for the operator

1. **Who proposes a release?** Recommended: the roller proposes one automatically when a module or site PR merges, reading `prove` and `verify` lines from the PR body. A person can still write a manifest by hand.
2. **Where do release and channel files live?** Recommended: in the deploy repo, beside the overlay they change, so a roll and its state change are one atomic commit. The public site shows only release names, PR links and short SHAs.
3. **Does a site-only release need the worldserver gates?** Recommended: no. A site-only release restarts only the site pods, so it skips the hourly and dungeon gates but still verifies on the bridge log.
4. **Should a roll wait for families only, or for any guild run?** Recommended: families plus any formed guild dungeon or raid group, since guild runs are now live and a restart wipes them too.
5. **Is the hourly limit per roll start or per restart?** Recommended: per roll start, with rollbacks exempt.
6. **Auto-rollback, or page and wait?** Recommended: auto-rollback on the listed criteria, then pause the channel so the next release does not roll over an unexplained failure.
7. **Is a missing verify grep a rollback, or only a flag?** Recommended: a rollback by default; a change may mark its check `soft: true` when the event is rare (a level-up, a guild death).
8. **Should the site get a pause button?** Recommended: not at first. Pausing is a one-line commit; a button needs a write token on a public-facing pod.
9. **Coalesce queued releases?** Recommended: yes, roll only the newest proven release, since one restart per hour is the binding limit.
10. **How long do the old scripts live?** Recommended: until three rolls in a row verify through the roller, then delete them.

https://claude.ai/code/session_01TTixe8XCvTjiuqSLhi98KX
