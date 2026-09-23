# This repository is public

Everything here — code, commit history, issues, pull requests, comments,
review threads, discussions, releases, wiki pages, GitHub Pages content —
is visible to anyone on the internet, forever, including after deletion
(forks, caches, and search-engine indexes outlive an edit or a delete).
Treat every write to this repo, in any surface, as something a stranger
reads the moment you make it.

This file exists because that got violated repeatedly before it was
written down. Real personal names, a real home network's addresses, real
device identifiers, and a live unrotated credential all ended up in public
issue trackers and public git history — not through carelessness in the
code, but through ordinary conversational writing in issues, PR bodies, and
code comments, where the discipline that already existed for the shipped
code was never applied. This file is the fix: the same discipline,
extended to every surface an agent writes to, not just the diff.

## The rule

**Nothing that identifies a specific person, a specific private network,
or a specific credential may appear anywhere in this repository, in any
form, ever.** Not in code. Not in a code comment. Not in an issue body. Not
in a PR description. Not in a commit message. Not in a comment reply. Not
in a test fixture. Not "just this once because it's only in a closed
issue" — closed does not mean hidden, and neither does deleted.

This is broader than "don't commit secrets." A secret scanner catches an
API key. It does not catch a sentence like *"[a real first name]'s home
server, reachable at their usual address, needed a restart"* — nothing
there matches a secret
pattern, and it is exactly the kind of sentence that put a real name, a
real domain, and a real IP into a public tracker tonight. Write for a
stranger from the first word, not just the code.

### Concretely, never write any of the following into this repo, on any surface

- A real personal name — yours, a collaborator's, anyone's. Refer to
  people by role ("the maintainer," "the operator," "a reviewer") the same
  way this file does.
- A real hostname, domain, or subdomain that resolves to a private network
  or a real person's infrastructure (a home VPN suffix, a personal tailnet
  domain, a work-in-progress product's real URL before it's meant to be
  public). Use a placeholder that is visibly fake: `example.com`,
  `your-server.internal`, `<your-domain>`.
- A real IP address on any network you actually operate — home, cloud, or
  otherwise. Use an RFC 5737 documentation range (`192.0.2.0/24`,
  `198.51.100.0/24`, `203.0.113.0/24`) or an obviously fictional one
  (`10.0.0.X` as a *labeled example* is fine; a live address copy-pasted
  from a real `curl`/`dig`/log output is not).
- A real device identifier: a serial number, a MAC address, an IMEI, a
  hardware ID, an account ID, a database GUID tied to a live system.
- A credential of any kind, live or "already rotated" — a key, a token, a
  password, a signing certificate, a webhook URL with a token embedded in
  the path. "It's already been rotated" is not a reason to leave the old
  value visible; redact it anyway, because the *pattern* (which SSM path,
  which naming convention, which provider) is itself information.
- A path that reveals a real local username (`/Users/<name>/...`,
  `C:\Users\<name>\...`) or a real machine's hostname.
- A quote attributed to a specific named person, even an accurate one.
  Paraphrase instead: "the operator decided..." not "Alice said...".
- An `@`-mention of anyone who is not already part of the conversation.
  A mention notifies that account and subscribes it to the thread, and
  neither can be undone by editing or deleting the text. `@grug` in
  particular is an unrelated real user, not the review bot: the bot is
  `grug-tribe[bot]` and takes slash commands (`/grug improve` re-runs the
  code review, `/grug recheck` re-runs the plan check). To name a handle
  in prose, put it in backticks, which GitHub does not treat as a mention.
- The name of another private repository, service, or internal system
  that isn't itself meant to be discoverable. Cross-repo references
  belong in the *private* tracker, not migrated wholesale into a public
  one.

### If you are migrating or importing content

Content that already exists elsewhere — an issue being moved from a
private repo, a comment thread being copied in, history being subtree-split
into a new repo — is not exempt from this rule because it was written
before this file existed. **Migration is not a scrub.** Before content
from anywhere else lands in this repo, on any surface, re-read it against
every bullet above and rewrite what fails. If a whole issue's substance is
inseparable from the personal/private detail it's built on, don't migrate
it — summarize the generic problem it represents instead, or leave it out.

Wholesale-copying a private issue tracker into a public one because it was
"faster" is exactly how this happened the first time.

### If you find a violation already in the repo

Fix the current tree, then say plainly in your response that older
issues/PRs/comments/history may still carry it and that this needs a
human decision, not a silent edit-and-move-on. Do not delete or rewrite
someone else's public comment without asking first — you may not always
know why it was worded that way. Editing your own agent-authored content
to remove a violation is always fine and encouraged.

## The other half: this repo must be genuinely reusable

A stranger must be able to clone this repository, supply their **own**
configuration and secrets, and have it work — without reading anything
beyond the README and an example config file to know what to change.

- Every value specific to one deployment (a hostname, an IP, a region, an
  account ID, a device identifier) is a variable, an environment variable,
  or a config file entry — never a literal baked into source, a workflow
  file, or a script.
- Ship a `.env.example` / `config.example.*` alongside any file that reads
  real config, with every key present and an obviously-placeholder value
  (`YOUR_DOMAIN_HERE`, not a real one with the last octet changed).
- If a CI/CD pipeline assumes infrastructure that doesn't ship with the
  repo (a specific runner pool, a specific cloud account, a specific
  private reusable workflow), say so explicitly in the README rather than
  let a stranger discover it as a mysterious failure. "This requires your
  own self-hosted runner and your own AWS account" is an honest
  dependency; a silent reference to `uses: <this-operator>/infra-private/...`
  is not.
- Prefer this repo's own already-public reusable workflows
  (`quadseven/infra-public/...`) over hand-rolled CI where one already
  exists — they're already written to take config as input rather than
  assume it.

## Why this file, not just a smarter secret scanner

A pattern-matching scanner catches shapes: an AWS key, a PEM block, a
32-character hex string. It cannot catch a paragraph of ordinary prose
that happens to name a real person or describe a real network in plain
words — which is where nearly everything this file exists to prevent
actually showed up. Scanners still belong in CI as a backstop for the
shapes they *can* catch; this file is the layer above that, for the judgment
a scanner doesn't have.

<!-- Everything above the next line is synced from quadseven/infra-public and replaced on every sync. Put this repo's own content below it. -->
<!-- repo-specific below -->

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
