# Where wow-overseer came from

This service was extracted on 2026-09-18 from the operator's private
deployment repository, with its full commit history preserved through
`git filter-repo`. That repository built and deployed the bridge in-tree for
its whole life before then. [mod-overseer](https://github.com/quadseven/mod-overseer)
went through the same extraction on 2026-08-27.

Before the split, the image was built inside the operator's own cluster by a
build Job whose context arrived in pieces, and the unit tests ran on a private
self-hosted runner pool. Here the image is a plain `docker build .` on a
GitHub-hosted runner (`build.yml`), and the tests run with the same command on
`ubuntu-latest` (`check.yml`).

## What did not come with the move

A handful of tests that lived beside this code were not moved, because they do
not test this service: they checked text in the deploy repository's own image
build workflow and build benchmark, and they stayed there.

One pin-agreement test was retired outright. It asserted that the deploy
repository compiled the same module commit it cloned; that premise does not
apply to a service that now ships as a prebuilt, digest-pinned image.

## Vendored copies

`patches/mod-playerbots/` holds two kinds of mod-playerbots patch, and no
build here reads any of them (`.dockerignore` drops the directory):

- `0004`, `0005`, `0016`: copies of patches from the infrastructure repo's
  realm patch tree, kept because a few tests assert content against them.
- `0017` to `0021`: the Majordomo series (#1650, #1651, #1652, #1659). They
  were written here, and the tests apply them to the pinned fork in order.

Realm patches are applied only from the infrastructure repo's tree,
`production/docker/azerothcore-playerbots/patches/`. The Majordomo series
ships from there as `0037` to `0041` (#1741). A patch merged here does not
reach the realm until it is ported into that tree.

The infrastructure repo's patch check runs its module patch coverage tool
over this repo's main with `--module-name wow-overseer`. A patch here with no
counterpart in that tree is an error. A same-named patch whose changed lines
differ is a drift warning. So when a copy here and the applied one disagree,
the applied one wins: make this copy match it. `0004` drifted on one comment
line and was brought back in line with the applied copy (#1781).

`UPSTREAM-PINS.env` is a vendored test fixture, not a build input. Read its
header comment before changing it.
