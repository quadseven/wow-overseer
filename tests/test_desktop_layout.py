"""Desktop member upgrades retain their grid after visiting the Raid route."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UpgradeGridIsolation(unittest.TestCase):
    def test_raid_styles_cannot_redefine_the_members_upgrade_row(self):
        # Route styles remain loaded after navigation. An unqualified Raid
        # .up-row rule replaced the six-column Members grid with four columns.
        members = (ROOT / "app/views/members.css").read_text()
        raid = (ROOT / "app/views/raid.css").read_text()
        self.assertRegex(members, r"\.up-row\s*\{[^}]*grid-template-columns")
        rules = re.findall(r"([^{}]+)\{([^{}]*)\}", raid)
        selectors = [s.strip() for head, _ in rules for s in head.split(",")]
        self.assertFalse(
            [s for s in selectors if re.match(r"^\.up-row(?:\s|[{:>]|$)", s)],
            "Raid row styles must not match the Members upgrade row",
        )

    def test_raid_column_headings_can_wrap_inside_the_content_width(self):
        # The shared table header forbids wrapping; the expanded
        # roster otherwise grows beyond the content area at 1280 pixels.
        raid = (ROOT / "app/views/raid.css").read_text()
        self.assertRegex(raid, r"\.raid-table th\s*\{[^}]*white-space:\s*normal")
