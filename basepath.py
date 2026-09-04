"""Where this page is mounted, and how every URL it emits finds its way home.

WHY THIS EXISTS, AND WHY IT IS A SAFETY MODULE RATHER THAN A CONVENIENCE. Three
realms run this site. Until now each had its own hostname, and the hostname WAS
the answer to "which world am I looking at" - the routing layer's own comments
say the stake out loud, about getting one word wrong in a proxy target: it does
not fail, it serves the live family's positions under a name whose entire
promise is that it is not production.

Those hostnames are being collapsed into one, with each realm served under its
own path instead. That move has a trap in it that has nothing to do with the
routing and everything to do with this page. A browser resolves a URL like
`/api/map` against the ORIGIN, not against the path the document was fetched
from. So a page served under a prefix that asks for `/api/map` is not asking
its own realm at all: it is asking whatever is mounted at the root, which is
production. The page would render production's characters, under a path that
says otherwise, with no error anywhere and no symptom to notice. That is the
same failure the routing comments describe, arriving through the front end.

WHAT THIS MODULE IS. The mount point, normalized once, plus the substitution
that gets it into the markup. `normalize` turns whatever the environment says
into either the empty string (the root) or a rooted path with no trailing
slash, so that a URL is a plain concatenation at every call site: `u("/api/map")
-> "/api/map"` at the root and `"/dev/api/map"` under a prefix. `apply` puts
that answer into the page, because it CANNOT be baked into the image: all three
realms run the same image and differ only in configuration.

WHY THE SERVER DOES NOT ALSO ROUTE ON THE PREFIX. The ingress strips it before
proxying, so this process sees `/api/map` whether it was asked for at the root
or under a path, and its routing table stays a lookup on exact paths. Two
independent mechanisms that could each strip a prefix is one more than there
should be: if the ingress ever stopped stripping, a server that also stripped
would keep serving happily and the page would look right, whereas one that does
not strip returns a plain 404 on every request. A loud, immediate, obviously
wrong result is the better failure, so the stripping lives in exactly one place
and this module never touches `self.path`.

WHY AN INVALID VALUE RAISES, WHERE cast.py's OVERSEER_FAMILY FALLS BACK. That
asymmetry is deliberate and the reasoning is not the same on both sides.
cast.py falls back to the live family because every process that exists sets
nothing at all, so a raise would turn a typo in one overlay into a crash-looping
LIVE deployment. Here the unset case is already the safe one and is spelled as
such: no value means the root, which is exactly what the realm at the root has
always served, so nothing that sets nothing can be surprised. But a value that
was SET and cannot be read has no safe reading - falling back to the root would
hand a prefixed realm the root's URLs, which is precisely the cross-realm read
above. A pod that refuses to start says so in one line of log; a pod that
quietly addresses the wrong world says nothing at all.
"""
from __future__ import annotations

import json
import re

import realmnav

# The Deployment-level knob. Named for the page rather than for the realm on
# purpose: it says WHERE this copy is mounted, and nothing about which world it
# is reading. Which world it is reading is settled by the database it dials,
# and reported by realm.py out of that same database.
ENV_VAR = "OVERSEER_BASE_PATH"

# The placeholder the page ships with, replaced on the way out. A substituted
# marker rather than a `<base href>` element, because `<base>` also rewrites
# in-page fragment links and the functional IRI references this page uses to
# point SVG markers at their own definitions - it would silently move
# `url(#arrow)` to another document. The cost is that every URL goes through
# one helper; the benefit is that nothing resolves differently than it reads.
#
# NAMED `PLACEHOLDER` AND NOT `TOKEN`, which is what it was first called and is
# the more natural word. ruff's S105 reads any assignment to a name like that
# as a hardcoded credential, and it is right to in general. Renaming beats a
# suppression directive here: the suppression would be arguing with a correct
# rule over a name that was arbitrary, and ruff parses such a directive out of
# ANY comment, so even writing one in prose to explain it silences the whole
# line. ../../oke/manifests/wow-dev/tests/_render.py hit both halves of this
# and made the same choice.
PLACEHOLDER = "__OVERSEER_BASE__"
# THE SWITCHER RIDES WITH THE MOUNT POINT, because it is a function of it: the
# page is served from one image on all three realms and the ONLY thing that
# differs is where it is mounted, so the mount is both what tells the page
# where it is and what tells it which pill to light. Substituting them in the
# same pass means the two can never disagree.
#
# Not an endpoint. A switcher that arrives on a later poll is a switcher that
# is missing for the first second on every load, which is exactly when someone
# who opened the wrong realm is looking for it.
NAV_PLACEHOLDER = "__OVERSEER_NAV__"

# What a mount point may be made of. Deliberately narrow: this value is
# substituted into a JavaScript string literal in the page, so a quote or a
# backslash in it would not be a wrong path, it would be a broken page. The
# characters permitted here are the ones a path segment is actually made of.
_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]+$")

# "." and ".." pass the charset above and are not mount points by any
# reading. Named rather than folded into the pattern because the reason is
# different: they are the two segments that mean "somewhere else".
_NOT_SEGMENTS = (".", "..")


def normalize(value: str | None) -> str:
    """The mount point, as a prefix that concatenates: "" or "/dev".

    Empty, missing or "/" all mean the root and come back as the empty string,
    so that `prefix + "/api/map"` is correct without a branch. Anything else is
    returned rooted and without a trailing slash, for the same reason.

    Raises ValueError on a value that was set and cannot be read as a path. See
    this module's docstring for why that is a raise and not a fallback.
    """
    text = (value or "").strip()
    if not text or text == "/":
        return ""
    segments = [s for s in text.split("/") if s]
    for segment in segments:
        if segment in _NOT_SEGMENTS or not _SEGMENT.fullmatch(segment):
            raise ValueError(
                f"{ENV_VAR}={value!r} is not a usable mount point: the segment "
                f"{segment!r} is not a plain path segment. Set it to a rooted "
                "path such as '/dev', or leave it unset to serve at the root."
            )
    return "/" + "/".join(segments)


def apply(html: bytes, prefix: str) -> bytes:
    """The page with its mount point substituted in.

    Raises if the page carries no placeholder. A page that cannot be told where
    it is mounted would fall back to addressing the root, which for every realm
    but the one AT the root means reading production - so an index.html that
    lost the token has to stop the response rather than serve a page that looks
    entirely normal and is asking the wrong world.
    """
    marker = PLACEHOLDER.encode()
    if marker not in html:
        raise ValueError(
            f"the page carries no {PLACEHOLDER} placeholder, so it cannot be told it "
            "is served under a prefix. Serving it anyway would address the "
            "realm at the root from every realm."
        )
    html = html.replace(marker, prefix.encode())
    # Substituted only where the page asks for it. A page with no switcher is
    # a page with no switcher, which is a visible absence somebody notices;
    # refusing to serve it, the way a missing mount point is refused, would
    # turn a cosmetic loss into an outage. test_realm_nav asserts index.html
    # carries the token, so the loud failure happens in the suite instead.
    nav = NAV_PLACEHOLDER.encode()
    if nav in html:
        html = html.replace(
            nav, json.dumps(realmnav.build_nav(prefix)).encode())
    return html
