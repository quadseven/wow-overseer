"""The runner commands exist, fail closed without a config, and say why."""

import io
import pathlib
import unittest
from contextlib import redirect_stdout

from ephemeral import __main__ as cli


class CliTest(unittest.TestCase):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(list(argv))
        return code, buf.getvalue()

    def test_commands_refuse_without_a_config(self):
        import os

        os.environ.pop("EPH_CONFIG", None)
        for argv in (
            ("submit", "x.yaml"),
            ("dispatch", "--once"),
            ("collect", "--dry-run"),
        ):
            code, out = self.run_cli(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("no runner config", out)

    def test_example_config_loads_once_filled_in(self):
        import json

        from ephemeral import runcfg

        example = (
            pathlib.Path(__file__).resolve().parent.parent
            / "ephemeral"
            / "eph.config.example.json"
        )
        raw = json.loads(example.read_text(encoding="utf-8"))
        raw["never_nodes"] = ["some-other-node"]
        raw["tools_image"] = "registry.example.com/t@sha256:" + "0" * 64
        cfg = runcfg.from_dict(raw)
        self.assertEqual(set(cfg.nodes), {"node-a", "node-b"})

    def test_config_refuses_a_never_node_and_a_tag_only_tools_image(self):
        from ephemeral import runcfg

        base = {
            "results_dir": "r", "tools_image": "x@sha256:" + "0" * 64,
            "template_images": {"lean": "a:1", "full": "b:1"},
            "nodes": {"n": {"claim": "c", "max_worlds": 1}},
        }  # fmt: skip
        runcfg.from_dict(base)
        with self.assertRaises(runcfg.ConfigError):
            runcfg.from_dict({**base, "never_nodes": ["n"]})
        with self.assertRaises(runcfg.ConfigError):
            runcfg.from_dict({**base, "tools_image": "x:latest"})
        with self.assertRaises(runcfg.ConfigError):
            runcfg.from_dict({**base, "surprise": 1})


if __name__ == "__main__":
    unittest.main()
