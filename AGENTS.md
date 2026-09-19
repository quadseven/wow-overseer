# This directory is public. Write it accordingly.

This is the Overseer website and its bridge. It was extracted from a private
monorepo into its own repository, and that repository is public: the site and
`quadseven/mod-overseer` are one product split across two repos, and the site
is the natural companion to the module whose tables it reads.

The move has happened. What was a forward-looking discipline is now simply
true, so the rule below is no longer about **stopping the gap from widening**
between this code and code that could be published tomorrow. It was published.

## Why this matters more than it sounds

The blocker on publishing was never architecture. It is that ordinary writing
in this directory assumed a private audience for a long time, and that
assumption is baked into thousands of lines. Measured on 2026-09-03:

    21,069 lines of Python
        55 files naming the operator personally
         3 files naming internal hostnames
         1 file carrying a private IP address

Re-measured on 2026-09-19, immediately before the repository went public. The
private IP is gone, and so is every internal hostname that sat in a comment or
a docstring. What remains:

        47 files naming the operator personally (first name only: no
           surname, no email address, no location appears anywhere here)
         3 call sites where an internal hostname is a FUNCTIONAL DEFAULT,
           not prose - `LLM_URL` in bridge.py and map_server.py, and
           `WOW_STREAM_BASE` in family.py

That second group is deliberately still here. Nothing in the deployment sets
those three variables, so the defaults are what production actually runs on;
blanking them to scrub a hostname would silently break the language model
calls and every stream URL on the site. Paying that down means setting the
variables in the deployment FIRST and neutralising the defaults second, in
that order, as its own change.

None of that is a secret in the scanner sense. No key, no token, nothing a
secret scan would stop. It is a real person's name in a comment explaining why
a timeout exists, an internal hostname in a docstring, a home network address
in a default. Every one is individually harmless and collectively they are the
reason "just move the directory" is a scrub of a twenty-thousand-line codebase
rather than a `git mv`.

The debt is already written. The rule below exists so it stops growing.

## The rule

**Write every new line in this directory for a stranger.** Same discipline as
`quadseven/mod-overseer/AGENTS.md`, which is the canonical version and worth
reading in full: it was written after real names, a real home network's
addresses, and a live credential reached a public tracker through ordinary
conversational writing rather than through careless code.

Concretely, in anything you add here:

- **No real personal names.** Say "the operator", "a reviewer", "a
  collaborator". The existing 55 files are debt to be paid down, not a
  precedent to follow.
- **No internal hostnames.** Not a tailnet name, not a registry host, not a
  box name. Take them from config or environment, and in prose say "the
  streaming host" or "the private registry".
- **No private IPs or device identifiers.**
- **No credentials of any kind**, including in a test fixture, and including
  one you believe is already rotated.

This applies to code, comments, docstrings, test fixtures, commit messages that
touch these paths, and PR bodies describing them.

## When you touch a file that already violates it

Fix the lines you are already editing. Do not embark on a directory-wide scrub
as a side quest in an unrelated change: a 55-file rename buried inside a bugfix
is unreviewable, and the reviewer cannot tell the rename from the fix.

If you want to pay the debt down deliberately, that is its own change with its
own PR, and it is welcome.

## What this file is not

It is not permission to relax. The repository being public does not make the
remaining debt harmless. It makes it visible. The rule above is now load
bearing rather than anticipatory: a personal detail or an internal hostname
added here is disclosed the moment it is pushed, with no private window in
which to catch it.

The one thing that did get easier: the decision to publish is made, so it is
no longer a project hanging over every change.
