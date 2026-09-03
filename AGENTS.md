# This directory is not public yet. Write it as though it already is.

This is the Overseer website and its bridge. It lives in a private repository
today, and the intent is that it will not always: the site and
`quadseven/mod-overseer` are one product split across two repos, and the site
is the natural companion to the module whose tables it reads.

That move has not happened, and this file does not commit anyone to it. What it
commits you to is cheaper: **stop widening the gap between this code and code
that could be published tomorrow.**

## Why this matters more than it sounds

The blocker on publishing is not architecture. It is that ordinary writing in
this directory has assumed a private audience for a long time, and that
assumption is now baked into thousands of lines. Measured on 2026-09-03:

    21,069 lines of Python
        55 files naming the operator personally
         3 files naming internal hostnames
         1 file carrying a private IP address

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
- **No internal hostnames.** Not `*.ts.ehumps.me`, not a registry host, not a
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

It is not a claim that this directory is public. It is not permission to treat
it as public — private repository rules still apply, and nothing here should be
copied outward on the strength of this file. It is a statement that the code
should be *ready* to be, so that the decision to publish is a decision rather
than a project.
