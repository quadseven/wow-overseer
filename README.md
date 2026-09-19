# wow-overseer

The overseer control plane's Discord/web bridge: a service that reads and
writes the `overseer_command` / `overseer_snapshot` / `overseer_roster`
tables [mod-overseer](https://github.com/quadseven/mod-overseer) exposes
inside the worldserver, and turns them into natural-language Discord
commands, persisted goals, in-character chatter, and a live web map of the
world (`map_server.py`).

This repository and `quadseven/mod-overseer` are one product split across two
repos: the module delivers commands to bots and snapshots their state every
five seconds; this bridge is the only thing that ever writes a command, and
the only thing that renders what the module recorded.

**Private on purpose.** See `AGENTS.md` before writing anything here - this
directory carried real names, internal hostnames and a private IP for a long
time as a private-only codebase, and that debt is not yet paid down. It is
not ready to be made public the way `mod-overseer` was.

## Where this came from

Extracted 2026-09-18 from
[quadseven/infra](https://github.com/quadseven/infra)
(`production/scripts/wow-overseer/` + `production/docker/wow-overseer/`),
with full commit history preserved via `git filter-repo`. infra built and
deployed this service in-tree for its whole life before this; the same
extraction `mod-overseer` went through on 2026-08-27, one repo later.

## Layout

- Python modules at the repo root - flat, unpackaged, exactly as they lived
  under `production/scripts/wow-overseer/` in infra. `bridge.py` is the
  entrypoint (`CMD` in the Dockerfile); `map_server.py` serves the live map.
- `tests/` - the unit suite. A meaningful slice of it reads
  `mod-overseer/src/mod_overseer.cpp` as text to assert that a Python-side
  assumption still matches what the pinned C++ module actually does; that is
  why `mod-overseer/` is a submodule here rather than a dependency this repo
  only reads about.
- `mod-overseer/` - git submodule, pinned by commit (see `.gitmodules` /
  `UPSTREAM-PINS.env`). Not part of the built image; only `tests/` reads it.
- `tools/` - one-off/maintenance scripts (DBC extraction, roster seeding,
  probes). Not part of the built image.
- `patches/mod-playerbots/` - a vendored copy of the three upstream
  mod-playerbots patches a handful of tests assert content against
  (`0004`, `0005`, `0016`). The authoritative copies live in
  `quadseven/infra` at `production/docker/azerothcore-playerbots/patches/`;
  these can drift from that copy and nothing currently catches it.
- `UPSTREAM-PINS.env` - a vendored **test fixture**, not a build input. See
  its own header comment before changing it.
- `Dockerfile` - builds the bridge image, `docker build .`, no submodule or
  test content required.

## CI

- `check.yml` - `python3 .github/scripts/compile_check.py --min-python 3.12`
  then `python3 -m unittest discover -s tests -p 'test_*.py'`, on
  GitHub-hosted `ubuntu-latest`, with the `mod-overseer` submodule checked
  out. Same test-cmd infra ran on `arc-infrastructure` before the split.
- `build.yml` - builds `ghcr.io/quadseven/wow-overseer`, builds only (no
  push) on a pull request, and builds + pushes `sha-<12-char-sha>` on a push
  to `main`. **The package is private** (this repo is private), so consuming
  it in k8s-oke needs an `imagePullSecret` - see `quadseven/infra`'s
  `production/oke/manifests/muster/deployment.yaml` for the working pattern
  this follows (`imagePullSecrets: [{name: ghcr}]`).

## What did not come with the move

A handful of tests that lived in `production/scripts/wow-overseer/tests/` in
infra were **not** moved here, because they do not test this service at all -
they assert text-level properties of infra's own
`.github/workflows/build.azerothcore-playerbots.yml` and
`production/docker/azerothcore-playerbots/tools/build_benchmark.py`. They
stayed in `quadseven/infra` (relocated to
`production/docker/azerothcore-playerbots/tests/`). `test_pin_agreement.py`
was retired outright rather than moved: its whole premise (infra's
`UPSTREAM-PINS.env` clones a SHA that infra itself compiles) does not apply
to a service that now ships as a prebuilt, digest-pinned image instead of
source infra clones and builds.
