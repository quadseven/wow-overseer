"""The three worlds, and how to get from one to another.

WHY THIS EXISTS AT ALL. Three realms are served from one hostname, told apart
by the path, and until now nothing on the page said so. Moving between them
meant editing the URL, which is not a thing anybody does, so in practice the
site had one realm: whichever you happened to open.

WHY IT IS A MODULE AND NOT THREE ANCHORS IN THE HTML. Three judgements live
here, and every one of them is the kind that goes wrong silently:

  which realms exist        a fourth world would otherwise be added by editing
                            markup in one place and routing in another
  which one you are on      derived from the mount point, because the page
                            cannot ask the world what realm it is: it is
                            served from the same image on all three, and the
                            only thing that differs is where it is mounted
  which one has no page     hardcore has no site AT ALL, deliberately, and a
                            switcher that links to it sends a reader to a 404
                            that looks like an outage

That last one is the reason this is worth a file. `wow-hardcore/excluded.yaml`
deletes the wow-map Deployment and its Service, and the Caddyfile has no route
for /hardcore/ and explains why at length (infra#2912). It is not missing, it
is a decision. So the switcher shows it, disabled, and SAYS WHY - which is the
difference between "that world has no page yet" and a link that appears broken.
"""

# THE MOUNT POINT IS THE IDENTITY. basepath.normalize has already turned
# whatever the environment said into "" or "/dev" or "/hardcore", so these are
# compared against a value that is already clean rather than against raw
# configuration.
PRODUCTION = ""
DEV = "/dev"
HARDCORE = "/hardcore"

# Short, because they sit in a row on a phone and the row must not wrap.
# "PROD" rather than "PRODUCTION" for the same reason the realm band spells the
# long form: the band has the whole width and is making a safety claim, the
# switcher is a control.
REALMS = (
    (PRODUCTION, "PROD", "the live realm"),
    (DEV, "DEV", "the family"),
    (HARDCORE, "HC", "hardcore"),
)

# Said in full wherever the disabled control is explained, so nobody has to go
# and find out whether it is broken.
NO_PAGE = ("This world runs, but it has no page: its map deployment and "
           "service are deliberately excluded, and nothing routes to it.")


def has_page(mount: str) -> bool:
    """Does this realm serve a site?

    Named as a question about the REALM rather than as a list of exceptions,
    so the answer stays true if hardcore ever gains one: the day it does, this
    function is the single place that changes.
    """
    return mount != HARDCORE


def href_for(mount: str) -> str:
    """Where a link to this realm points.

    Always ends in "/". A link to "/dev" gets a redirect to "/dev/" before it
    is served, and the redirect is one that some proxies answer with the ROOT
    realm, which would silently hand a reader production while the switcher
    showed dev as active.
    """
    return (mount or "") + "/"


def build_nav(current: str) -> list:
    """The switcher, in a fixed order, with exactly one entry marked current.

    `current` is the mount point this page is served under. An unrecognised
    value marks NOTHING as current rather than guessing, because the honest
    rendering of "I do not know which realm this is" is a switcher with no
    active pill, and guessing production would be the most dangerous of the
    three to be wrong about.
    """
    nav = []
    for mount, label, description in REALMS:
        live = has_page(mount)
        nav.append({
            "mount": mount,
            "label": label,
            "description": description,
            "href": href_for(mount) if live else "",
            "current": mount == current,
            "reachable": live,
            # A disabled control that does not say why is indistinguishable
            # from a broken one.
            "note": "" if live else NO_PAGE,
        })
    return nav
