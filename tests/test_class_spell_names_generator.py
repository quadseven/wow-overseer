"""Class skill taxonomy covers all ranks and indirect trainer learn rows."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.class_spell_names_from_dbc import (
    class_spell_ids,
    names_from_dbc,
    read_dbc,
    render,
)


def spell(spell_id, teaches=0):
    row = [0] * 234
    row[0] = spell_id
    if teaches:
        row[71], row[116] = 36, teaches
    return row


class ClassSpellSelection(unittest.TestCase):
    def test_class_skills_masks_and_recursive_learn_wrappers(self):
        skills = [(1, 7), (2, 11)]
        abilities = [
            (1, 1, 100, 0, 0),
            (2, 2, 200, 0, 8),
            (3, 2, 300, 0, 0),
            (4, 1, 999, 0, 0),
        ]
        spells = [spell(100), spell(200), spell(300), spell(401, 400), spell(400, 100)]
        self.assertEqual(
            class_spell_ids(skills, abilities, spells), {100, 200, 400, 401}
        )

    def test_names_and_ranks_come_from_client_strings(self):
        row = spell(100)
        row[136], row[153] = 1, 7
        inputs = [
            ([row], b"\0Light\0Rank 2\0"),
            ([(1, 7)], b""),
            ([(1, 1, 100, 0, 0)], b""),
        ]
        with patch("tools.class_spell_names_from_dbc.read_dbc", side_effect=inputs):
            names = names_from_dbc(Path("unused"))
        self.assertEqual(names, {100: "Light (Rank 2)"})
        self.assertIn('"100": "Light (Rank 2)"', render(names))

    def test_wrong_client_data_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Spell.dbc"
            path.write_bytes(b"a different client")
            with self.assertRaisesRegex(ValueError, "does not match"):
                read_dbc(path)
