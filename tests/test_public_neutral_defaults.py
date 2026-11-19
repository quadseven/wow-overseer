"""Keep deployment-specific service URLs out of public defaults."""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DEFAULTS = {
    "bridge.py": ("LLM_URL", "https://llm-service.example.com"),
    "map_server.py": ("LLM_URL", "https://llm-service.example.com"),
    "family.py": ("WOW_STREAM_BASE", "https://wow-stream.example.com"),
}


def _environment_default(source: str, variable: str) -> str:
    """Return the fallback passed to os.environ.get for one variable."""
    module = ast.parse(source)
    for node in ast.walk(module):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        environment = node.func.value
        if (
            node.func.attr != "get"
            or not isinstance(environment, ast.Attribute)
            or environment.attr != "environ"
            or not isinstance(environment.value, ast.Name)
            or environment.value.id != "os"
            or len(node.args) < 2
            or not isinstance(node.args[0], ast.Constant)
            or node.args[0].value != variable
        ):
            continue
        return ast.literal_eval(node.args[1])
    raise AssertionError(f"os.environ.get for {variable} is missing")


class PublicNeutralDefaults(unittest.TestCase):
    def test_service_url_fallbacks_are_neutral(self):
        for path, (variable, expected) in EXPECTED_DEFAULTS.items():
            with self.subTest(path=path, variable=variable):
                source = (ROOT / path).read_text(encoding="utf-8")
                actual = _environment_default(source, variable)
                self.assertTrue(
                    actual == expected,
                    f"{path} {variable} fallback must use the documented placeholder",
                )


if __name__ == "__main__":
    unittest.main()
