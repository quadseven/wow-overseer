"""The gear feed groups changes and keeps visit times per page key."""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"


class TestGearChangesView(unittest.TestCase):
    def test_invalid_stored_times_fall_back_to_the_first_visit_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "app"
            shutil.copytree(APP, root)
            (root / "package.json").write_text('{"type":"module"}', encoding="utf-8")
            module = (root / "models/gearchanges.js").as_uri()
            code = (
                "const M = await import(%s); const now = 200000000;\n"
                "const values = ['-1', '', '1.5', '9007199254740992', '8640000000000001'];\n"
                "const got = values.map(value => M.since('key-' + value, {getItem: () => value}, now));\n"
                "process.stdout.write(JSON.stringify(got));\n"
            ) % json.dumps(module)
            result = subprocess.run(
                [shutil.which("node"), "--input-type=module", "-e", code],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            ["1970-01-02T07:33:20.000Z"] * 5,
        )

    def test_storage_is_read_and_written_per_page_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "app"
            shutil.copytree(APP, root)
            (root / "package.json").write_text('{"type":"module"}', encoding="utf-8")
            module = (root / "models/gearchanges.js").as_uri()
            code = (
                "const data = new Map(); const storage = {getItem: k => data.get(k), "
                "setItem: (k, v) => data.set(k, v)};\n"
                "const M = await import(%s);\n"
                "const a = M.since('site', storage, 200000000);\n"
                "const b = M.since('member:tharn', storage, 300000000);\n"
                "M.markSeen('site', storage, 400000000);\n"
                "process.stdout.write(JSON.stringify([a, b, M.since('site', storage), "
                "M.since('member:tharn', storage)]));\n"
            ) % json.dumps(module)
            result = subprocess.run(
                [shutil.which("node"), "--input-type=module", "-e", code],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        got = json.loads(result.stdout)
        self.assertEqual(got[0], "1970-01-02T07:33:20.000Z")
        self.assertEqual(got[1], "1970-01-03T11:20:00.000Z")
        self.assertEqual(got[2], "1970-01-05T15:06:40.000Z")
        self.assertEqual(got[3], got[1])


if __name__ == "__main__":
    unittest.main()
