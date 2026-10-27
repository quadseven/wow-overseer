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

`patches/mod-playerbots/` holds copies of three upstream mod-playerbots
patches (`0004`, `0005`, `0016`) that a few tests assert content against. The
authoritative copies live with the deploy repository's server image build.
The two can drift, and nothing here catches it yet.

`UPSTREAM-PINS.env` is a vendored test fixture, not a build input. Read its
header comment before changing it.
