"""Read a module's guild job ladder as it was before seats level first.

An approved raid seat below the cap now skips errands that do not block play
(guildjobs.levelling_first, SEATS_LEVEL_FIRST). A test module that pins an
older rung for a member named after a seat (a dedicated trainer errand, the
rank walk, the mail walk, the ordinary job) calls `switch_off` from its
`setUpModule`; the new order is pinned in test_seats_level_first.py.
"""

import os
import unittest


def switch_off():
    old = os.environ.get("SEATS_LEVEL_FIRST")
    os.environ["SEATS_LEVEL_FIRST"] = "off"

    def restore():
        if old is None:
            os.environ.pop("SEATS_LEVEL_FIRST", None)
        else:
            os.environ["SEATS_LEVEL_FIRST"] = old

    unittest.addModuleCleanup(restore)
