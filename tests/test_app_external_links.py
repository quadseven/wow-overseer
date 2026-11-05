"""Links to other sites open only when the read gives an https URL.

The economy, upstream and quest views open server-supplied URLs in a new tab.
Each goes through the one predicate in app/ui.js, so a value that is not an
https URL (a javascript: URL, a relative path, a missing field) renders as
text or nothing, never as a link (#1849).
"""

import json
import shutil
import unittest

from test_app_shell import node_module

BAD = ["javascript:alert(1)", "http://example.com/x", "/relative", "", None, 7]


def economy(url):
    wealth = {
        "auctions": {
            "any": False,
            "tracked": True,
            "listings": [],
            "empty": {
                "lead": "Nothing listed.",
                "body": "",
                "why": {
                    "before": "See ",
                    "ticket": {"url": url, "label": "the ticket"},
                    "after": ".",
                },
            },
        }
    }
    return node_module(
        "views/economy.js",
        """
const get = (path) => path === '/api/wealth'
  ? {data: %s, error: null, loading: false, at: 1}
  : {data: null, error: null, loading: true, at: 0};
const out = M.default.render({get, params: {tab: 'auction'}, query: {}});
console.log(JSON.stringify(out.s));
"""
        % json.dumps(wealth),
        realm={"families": [], "guilds": []},
    )


def upstream(url, repo="acore/example"):
    row = {
        "label": "Example",
        "status": "behind",
        "pinned": "abc1234",
        "head": "def5678",
        "behind": 1,
        "repo": repo,
        "url": url,
        "notable": [{"sha": "def5678", "title": "Fix a crash", "tags": []}],
    }
    read = {"data": {"rows": [row]}, "error": None, "loading": False, "at": 1}
    return node_module(
        "views/upstream.js",
        "console.log(JSON.stringify(M.upstreamSection(%s, 100).s));" % json.dumps(read),
    )


@unittest.skipUnless(shutil.which("node"), "node is needed for the actual views")
class OnlyHttpsUrlsBecomeLinks(unittest.TestCase):
    def test_the_predicate(self):
        out = node_module(
            "ui.js",
            "console.log(JSON.stringify(%s.map(M.isHttps)));"
            % json.dumps(["https://example.com/a"] + BAD),
        )
        self.assertEqual(out, [True] + [False] * len(BAD))

    def test_economy_ticket(self):
        self.assertIn(
            'href="https://example.com/t/1"', economy("https://example.com/t/1")
        )
        for url in BAD:
            text = economy(url)
            self.assertNotIn('target="_blank"', text, url)
            self.assertIn("the ticket", text)

    def test_upstream_compare_link(self):
        good = upstream("https://github.com/acore/example/compare/a...b")
        self.assertIn("Compare on GitHub", good)
        for url in BAD:
            self.assertNotIn("Compare on GitHub", upstream(url), url)

    def test_upstream_commit_link_needs_a_repo_name(self):
        good = upstream(None)
        self.assertIn('href="https://github.com/acore/example/commit/def5678"', good)
        for repo in ("", None, "../../other", "acore/example/../x", "a b/c"):
            text = upstream(None, repo=repo)
            self.assertNotIn("/commit/", text, repo)
            self.assertIn("Fix a crash", text)


if __name__ == "__main__":
    unittest.main()
