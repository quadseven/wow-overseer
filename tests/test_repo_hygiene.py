"""Repository hygiene checks."""

import re
import subprocess
from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
# A `uses:` line, step or job level. Local actions (./...) and docker://
# references are not GitHub refs and need no commit pin.
USES = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?([^\s'\"#]+)")
PINNED = re.compile(r"@[0-9a-f]{40}$")


class RepositoryHygiene(unittest.TestCase):
    def test_no_tracked_tmp_files(self):
        result = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.tmp"],
            check=True,
            capture_output=True,
        )
        tracked_files = result.stdout.decode().split("\0")
        existing_files = [
            path for path in tracked_files if path and Path(path).exists()
        ]
        self.assertEqual(existing_files, [], "tracked *.tmp files found")

    def test_every_workflow_action_is_pinned_to_a_commit_sha(self):
        # The review bot's hygiene watch reports any `uses:` not pinned to a
        # 40-hex commit SHA (#1468). This keeps the main branch clean between
        # its weekly reports, honouring the same inline opt-out it does.
        files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
        self.assertTrue(files, "no workflow files found")
        unpinned = []
        for path in files:
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                match = USES.match(line)
                if not match or "# hygiene: allow-" in line:
                    continue
                ref = match.group(1)
                if ref.startswith(("./", "docker://")):
                    continue
                if not PINNED.search(ref):
                    unpinned.append(f"{path.name}:{lineno}: {ref}")
        self.assertEqual(unpinned, [], "actions not pinned to a commit SHA")


if __name__ == "__main__":
    unittest.main()
