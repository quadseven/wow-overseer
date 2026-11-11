# Fidelity suite

A change to the overseer is proven twice. [docs/LIVEPROOF.md](LIVEPROOF.md) proves it live, on a schedule, after it ships. The fidelity suite proves it offline, before it merges: realm reads captured once are replayed in CI through the real read path, and the output is held to what the realm credited. Ticket: #2281.

## What a scenario is

One JSON file under `fidelity/scenarios/`, named for what it proves:

- `provenance`: `kind` is `realm` (taken from the realm, with `source` saying where and when) or `synthetic` (rows written to exercise the machinery). A synthetic scenario is never realm truth: its file name starts with `synthetic-` and it cannot list tickets under `proves`.
- `surface` and `args`: which existing read path runs and what it is asked. The first surface is `chronicle`, the feed behind `GET /api/v2/chronicle`.
- `reads`: the realm reads that path made, in order, each with its statement, parameters and rows (`gap` when the realm lacked the table).
- `expect`: the claims the credited record supports. For a run: how many encounters were credited, how many it expects, and whether a clear is credited.
- `proves`: realm scenarios only. The awaiting-live-check tickets whose behavior the scenario proves.

## Capture a scenario

```
LIVEPROOF_DB_HOST=... LIVEPROOF_DB_USER=... LIVEPROOF_DB_PASSWORD=... \
  python3 -m fidelity.record --surface chronicle --guild <guild> \
  --name <scenario-name> --source "<where and when>" \
  --alias <real name>=<alias> --out fidelity/scenarios/<scenario-name>.json
```

It uses the same read-only account as the live probes. Every statement must be a single SELECT (the liveproof guard) and the connection is read-only. Replace names with aliases (`--alias`, repeatable): a fixture holds no real person, host or address (see AGENTS.md). Then:

1. Read the file. The recorder refuses a capture with no credited tally, but it cannot know what else a capture holds.
2. Add the file and open a pull request with the capture evidence in the description.
3. If the recorder prints that the overseer disagrees with the record, either the overseer has a defect (the scenario is the proof) or the capture is not what you meant. Settle which before merging.

## Where expected outputs come from

From the realm's credited record at capture time, never from the code under test. `fidelity/derive.py` reads the credited tally out of the captured rows and states the claim; it imports nothing from the overseer, and a test pins that. A fixture whose expectations the code under test wrote would agree with the code by construction and prove nothing.

The rule it applies came out of the Blackrock Depths incident: trust credited encounter records, never a run's own complete flag. A run is a clear only when it ended `cleared` and its tally holds every encounter it expects. A run that ended `cleared` at 18 of 19 credits no clear.

Before the recorder keeps a fixture, `fidelity/verify.py` re-derives the claims from the same capture and refuses the fixture if they differ. The suite runs the same check on every scenario, so a claim edited after capture is refused.

## What CI runs

To run the same check by hand: `python3 -m fidelity.replay` (all scenarios) or `python3 -m fidelity.replay <file>`. It exits 1 when a fixture is not accepted by the verifier or a replay differs from the record.

`tests/test_fidelity_scenarios.py` replays every scenario on every pull request, inside the existing check job. Replay needs no realm, database or network: `fidelity/replay.py` answers only the statements the capture holds. A statement the capture lacks fails the replay, and so does a recorded read the code no longer makes. The same file shows the not-a-full-clear scenario going red when a completion-flag shortcut is put back.

A change that alters credited-encounter behavior fails the replay unless the scenario's claims are updated, and a realm scenario's claims change only with a new capture attached to the pull request. Re-capture after a change to a read statement too: replay matches statements exactly.

## Not yet here

Loot attribution, goal transitions and stuck classification are later surfaces on the same format. The seed from one real completed Blackrock Depths run needs a capture from the realm and is not in this change; until it lands, the scenarios here are synthetic and say so.
