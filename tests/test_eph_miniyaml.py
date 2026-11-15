"""The decree reader is a strict YAML subset, stdlib only (the suite has no YAML parser)."""

import unittest

from ephemeral.miniyaml import YamlError, loads


class ScalarsTest(unittest.TestCase):
    def test_types(self):
        doc = loads("a: 1\nb: -2\nc: true\nd: false\ne: null\nf: hello world\ng: 20m\n")
        self.assertEqual(
            doc,
            {
                "a": 1,
                "b": -2,
                "c": True,
                "d": False,
                "e": None,
                "f": "hello world",
                "g": "20m",
            },
        )

    def test_quoted(self):
        doc = loads("a: \"x\\\\y.*\"\nb: 'it''s'\nc: \"a # not a comment\"\n")
        self.assertEqual(doc, {"a": "x\\y.*", "b": "it's", "c": "a # not a comment"})

    def test_comments(self):
        doc = loads("# top\na: 1   # trailing\n\nb: two # more\n")
        self.assertEqual(doc, {"a": 1, "b": "two"})


class CommentTest(unittest.TestCase):
    def test_text_without_a_comment_comes_back_unchanged(self):
        from ephemeral.miniyaml import _strip_comment

        for text in (
            "plain words",
            "a|b",
            "x: y",
            "with#hash",
            "'quoted # kept'",
            'k: "a #b"',
        ):
            self.assertEqual(_strip_comment(text), text)

    def test_a_trailing_comment_is_removed_and_trailing_space_trimmed(self):
        from ephemeral.miniyaml import _strip_comment

        self.assertEqual(_strip_comment("a: 1   # note"), "a: 1")


class StructureTest(unittest.TestCase):
    def test_nested_map_and_seq(self):
        text = "w:\n  class: lean\n  list:\n    - a\n    - 2\nz: 1\n"
        self.assertEqual(
            loads(text), {"w": {"class": "lean", "list": ["a", 2]}, "z": 1}
        )

    def test_seq_of_maps(self):
        text = "c:\n  - who: Zork\n    set: {alive: false, at: {graveyard: nearest}}\n  - who: Grug\n"
        self.assertEqual(
            loads(text),
            {
                "c": [
                    {
                        "who": "Zork",
                        "set": {"alive": False, "at": {"graveyard": "nearest"}},
                    },
                    {"who": "Grug"},
                ]
            },
        )

    def test_flow(self):
        doc = loads('a: [1, "b", {c: d}]\ne: {}\nf: []\n')
        self.assertEqual(doc, {"a": [1, "b", {"c": "d"}], "e": {}, "f": []})

    def test_block_scalar(self):
        doc = loads("sql: |\n  SELECT 1\n    FROM t\nnext: 1\n")
        self.assertEqual(doc, {"sql": "SELECT 1\n  FROM t\n", "next": 1})

    def test_block_scalar_keeps_hash(self):
        self.assertEqual(loads("s: |\n  a # b\n"), {"s": "a # b\n"})

    def test_empty_value_is_null(self):
        self.assertEqual(loads("a:\nb: 1\n"), {"a": None, "b": 1})

    def test_dotted_keys(self):
        self.assertEqual(
            loads("Overseer.RequireClient: 0\n"), {"Overseer.RequireClient": 0}
        )


class RefusalsTest(unittest.TestCase):
    def assertRefused(self, text, fragment):
        with self.assertRaises(YamlError) as ctx:
            loads(text)
        self.assertIn(fragment, str(ctx.exception))

    def test_duplicate_key(self):
        self.assertRefused("a: 1\na: 2\n", "duplicate key")

    def test_tab_indent(self):
        self.assertRefused("a:\n\tb: 1\n", "tab")

    def test_anchor_and_tag(self):
        self.assertRefused("a: &x 1\n", "anchors")
        self.assertRefused("a: !!str 1\n", "tags")

    def test_unterminated_flow(self):
        self.assertRefused("a: {b: 1\n", "flow")

    def test_bad_indent(self):
        self.assertRefused("a: 1\n  b: 2\n", "indent")

    def test_unterminated_quote(self):
        self.assertRefused('a: "x\n', "quote")

    def test_folded_scalar(self):
        self.assertRefused("a: >\n  x\n", "folded")


if __name__ == "__main__":
    unittest.main()
