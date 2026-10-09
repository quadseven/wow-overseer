"""A cold #map/N link opens the continent it names (#560).

applyHash reads the hash before zones.json has arrived, and its call to
adoptContinent used to clear the request on the spot because there was
nothing yet to check it against. loadZones then found nothing left to adopt,
and #map/0 opened on the default continent. The request is now kept until the
zones are in, and the address bar is put right once it is adopted.

adoptContinent is run under node, the way the page runs it: once before the
map data, once after.
"""

import json
import pathlib
import shutil
import subprocess
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "classic.html").read_text(encoding="utf-8")


def fn(name):
    js = PAGE[PAGE.index("function %s(" % name) :]
    return js[: js.index("\n}\n") + 3]


def adopt(scenario):
    script = (
        'let zones = null, current = "1";\nlet wantedContinent = "";\n'
        + fn("adoptContinent")
        + scenario
    )
    out = subprocess.run(
        [shutil.which("node"), "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


ZONES = 'zones = {"0": {}, "1": {}, "530": {}};\n'


@unittest.skipUnless(shutil.which("node"), "needs node to run adoptContinent")
class TheRequestOutlivesTheFetch(unittest.TestCase):
    def test_a_cold_link_opens_the_continent_it_names(self):
        got = adopt(
            'wantedContinent = "0";\nadoptContinent();\n'
            + ZONES
            + "adoptContinent();\n"
            "process.stdout.write(JSON.stringify(current));"
        )
        self.assertEqual(got, "0")

    def test_an_unknown_id_still_keeps_the_default(self):
        got = adopt(
            'wantedContinent = "999";\nadoptContinent();\n'
            + ZONES
            + "adoptContinent();\n"
            "process.stdout.write(JSON.stringify([current, wantedContinent]));"
        )
        self.assertEqual(got, ["1", ""])

    def test_a_link_after_the_map_is_in_is_adopted_at_once(self):
        got = adopt(
            ZONES + 'wantedContinent = "530";\nadoptContinent();\n'
            "process.stdout.write(JSON.stringify([current, wantedContinent]));"
        )
        self.assertEqual(got, ["530", ""])


class TheAddressBarFollows(unittest.TestCase):
    def test_loadzones_rewrites_the_hash_once_the_continent_is_adopted(self):
        """showView already wrote #map/<default> before the fetch finished."""
        load = fn("loadZones")
        after = load[load.index("adoptContinent();") :]
        self.assertIn(
            'if (view === MAP_VIEW) history.replaceState(null, "", hashFor(MAP_VIEW));',
            after[: after.index("const tabs")],
        )


if __name__ == "__main__":
    unittest.main()
