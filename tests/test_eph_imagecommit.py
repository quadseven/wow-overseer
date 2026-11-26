"""Reading the commit an image was built from, out of its own config (no pin to type)."""

import base64
import hashlib
import json
import unittest

from ephemeral import imagecommit

COMMIT = "a" * 40
PATH = "quadseven/wow-overseer"
CONFIG = json.dumps(
    {"config": {"Env": ["PATH=/bin", f"OVERSEER_COMMIT={COMMIT}"]}}
).encode()
CONFIG_DIGEST = "sha256:" + hashlib.sha256(CONFIG).hexdigest()
MANIFEST = json.dumps({"config": {"digest": CONFIG_DIGEST}}).encode()
MANIFEST_DIGEST = "sha256:" + hashlib.sha256(MANIFEST).hexdigest()
INDEX = json.dumps({"manifests": [
    {"digest": "sha256:" + "9" * 64, "platform": {"os": "linux", "architecture": "arm64"}},
    {"digest": MANIFEST_DIGEST, "platform": {"os": "linux", "architecture": "amd64"}},
]}).encode()  # fmt: skip
INDEX_DIGEST = "sha256:" + hashlib.sha256(INDEX).hexdigest()
CREDS = ("someone", "pw-value")


class Registry:
    """A fake registry: answers by URL, records every request."""

    def __init__(self, root_digest, root_body, blob_redirect=False):
        self.calls = []
        self.blob_redirect = blob_redirect
        self.bodies = {
            f"https://ghcr.io/v2/{PATH}/manifests/{root_digest}": root_body,
            f"https://ghcr.io/v2/{PATH}/manifests/{MANIFEST_DIGEST}": MANIFEST,
            f"https://ghcr.io/v2/{PATH}/blobs/{CONFIG_DIGEST}": CONFIG,
        }

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        if url.startswith("https://ghcr.io/token"):
            return 200, {}, json.dumps({"token": "tok"}).encode()
        if self.blob_redirect and "/blobs/" in url:
            return 307, {"location": "https://storage.example.com/blob"}, b""
        if url == "https://storage.example.com/blob":
            return 200, {}, CONFIG
        if url in self.bodies:
            return 200, {}, self.bodies[url]
        return 404, {}, b""


class ImageEnvTest(unittest.TestCase):
    def ref(self, digest=MANIFEST_DIGEST):
        return f"ghcr.io/{PATH}@{digest}"

    def test_reads_the_env_of_a_plain_manifest(self):
        reg = Registry(MANIFEST_DIGEST, MANIFEST)
        env = imagecommit.image_env(self.ref(), CREDS, reg)
        self.assertEqual(env["OVERSEER_COMMIT"], COMMIT)

    def test_picks_the_amd64_entry_of_an_index(self):
        reg = Registry(INDEX_DIGEST, INDEX)
        env = imagecommit.image_env(self.ref(INDEX_DIGEST), CREDS, reg)
        self.assertEqual(env["OVERSEER_COMMIT"], COMMIT)

    def test_the_token_request_carries_the_credential_and_the_rest_the_bearer(self):
        reg = Registry(MANIFEST_DIGEST, MANIFEST)
        imagecommit.image_env(self.ref(), CREDS, reg)
        first_url, first_headers = reg.calls[0]
        self.assertIn(f"scope=repository:{PATH}:pull", first_url)
        want = "Basic " + base64.b64encode(b"someone:pw-value").decode()
        self.assertEqual(first_headers["Authorization"], want)
        for _, h in reg.calls[1:]:
            self.assertEqual(h["Authorization"], "Bearer tok")

    def test_a_redirected_blob_is_fetched_without_the_registry_token(self):
        reg = Registry(MANIFEST_DIGEST, MANIFEST, blob_redirect=True)
        imagecommit.image_env(self.ref(), CREDS, reg)
        url, headers = reg.calls[-1]
        self.assertEqual(url, "https://storage.example.com/blob")
        self.assertNotIn("Authorization", headers)

    def test_content_that_does_not_match_its_digest_is_refused(self):
        other = "sha256:" + "5" * 64
        reg = Registry(other, b"{}")
        with self.assertRaises(imagecommit.RegistryError):
            imagecommit.image_env(self.ref(other), CREDS, reg)

    def test_only_a_digest_reference_is_read(self):
        for bad in (
            "ghcr.io/quadseven/wow-overseer:latest",
            "x@sha256:abc",
            "http://ghcr.io/a@sha256:" + "0" * 64,
        ):
            with self.assertRaises(imagecommit.RegistryError):
                imagecommit.image_env(bad, CREDS, Registry(MANIFEST_DIGEST, MANIFEST))

    def test_a_missing_manifest_is_an_error_not_a_guess(self):
        with self.assertRaises(imagecommit.RegistryError):
            imagecommit.image_env(
                self.ref("sha256:" + "7" * 64),
                CREDS,
                Registry(MANIFEST_DIGEST, MANIFEST),
            )


class CredentialsTest(unittest.TestCase):
    def secret(self, auths):
        raw = json.dumps({"auths": auths}).encode()
        return {"data": {".dockerconfigjson": base64.b64encode(raw).decode()}}

    def test_user_and_password_from_the_auth_field(self):
        auth = base64.b64encode(b"u:p:with:colons").decode()
        got = imagecommit.credentials(
            self.secret({"ghcr.io": {"auth": auth}}), "ghcr.io"
        )
        self.assertEqual(got, ("u", "p:with:colons"))

    def test_user_and_password_fields(self):
        got = imagecommit.credentials(
            self.secret({"ghcr.io": {"username": "u", "password": "p"}}), "ghcr.io"
        )
        self.assertEqual(got, ("u", "p"))

    def test_no_entry_for_the_host_means_no_credential(self):
        self.assertIsNone(
            imagecommit.credentials(
                self.secret({"other.io": {"auth": "eDp5"}}), "ghcr.io"
            )
        )
        self.assertIsNone(imagecommit.credentials(None, "ghcr.io"))


class CommitTest(unittest.TestCase):
    def test_only_a_full_hex_commit_is_returned(self):
        self.assertEqual(imagecommit.valid_sha(COMMIT), COMMIT)
        for bad in ("", "abc", "g" * 40, None, COMMIT + "0"):
            self.assertIsNone(imagecommit.valid_sha(bad))


TPL = "registry.example.com/eph-template"
TPL_MANIFEST = b'{"schemaVersion": 2, "marker": "newest lean"}'


class TemplateRegistry:
    """A fake registry listing template tags and serving a manifest per tag."""

    def __init__(self, tags):
        self.tags = tags
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append(url)
        if "/token?" in url:
            return 200, {}, json.dumps({"token": "tok"}).encode()
        if url.endswith("/tags/list"):
            return 200, {}, json.dumps({"name": "x", "tags": self.tags}).encode()
        if url.endswith("/manifests/lean-20261120T020000Z"):
            return 200, {}, TPL_MANIFEST
        return 200, {}, b"other " + url.encode()


class NewestTemplateTest(unittest.TestCase):
    TAGS = [
        "lean-20261118T020000Z", "full-20261125T020000Z",
        "lean-20261120T020000Z", "lean-20261119T020000Z", "latest", "lean-bad",
    ]  # fmt: skip

    def test_newest_resolves_to_the_newest_stamp_of_the_class_as_a_digest(self):
        reg = TemplateRegistry(self.TAGS)
        got = imagecommit.newest_template(f"{TPL}:newest", "lean", CREDS, reg)
        want = "sha256:" + hashlib.sha256(TPL_MANIFEST).hexdigest()
        self.assertEqual(got, f"{TPL}@{want}")
        self.assertTrue(reg.calls[-1].endswith("/manifests/lean-20261120T020000Z"))

    def test_a_class_with_no_tag_is_an_error(self):
        reg = TemplateRegistry(["full-20261125T020000Z"])
        with self.assertRaises(imagecommit.RegistryError):
            imagecommit.newest_template(f"{TPL}:newest", "lean", None, reg)

    def test_only_a_newest_ref_is_resolved(self):
        self.assertTrue(imagecommit.is_newest(f"{TPL}:newest"))
        self.assertFalse(imagecommit.is_newest(f"{TPL}:lean-20261120T020000Z"))
        with self.assertRaises(imagecommit.RegistryError):
            imagecommit.newest_template(
                f"{TPL}:lean-1", "lean", None, TemplateRegistry([])
            )


if __name__ == "__main__":
    unittest.main()
