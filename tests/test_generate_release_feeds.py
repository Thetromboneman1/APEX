"""Release inventory failures must not masquerade as an empty release list."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError


SPEC = importlib.util.spec_from_file_location(
    "generate_release_feeds", Path(__file__).resolve().parents[1] / "scripts/generate_release_feeds.py"
)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class ReleaseInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        previous_cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous_cwd)
        self.env_patch = mock.patch.dict(os.environ, {
            "GITHUB_REPOSITORY": "Thetromboneman1/APEX",
            "GITHUB_REF_NAME": "main",
            "GITHUB_TOKEN": "",
        })
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        # Keep the generator's scratch cleanup inside this disposable fixture.
        self.path_patch = mock.patch.object(
            generator, "Path", side_effect=lambda value: (
                self.root / "scratch" if value == "/tmp/apex_ipas" else Path(value)
            )
        )
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.root.joinpath("JSON").mkdir()
        self.original = b'{"apps": [{"name": "Previously published app"}]}\n'
        for filename in ("esign.json", "feather.json", "scarlet.json", "store.json"):
            self.root.joinpath("JSON", filename).write_bytes(self.original)

    def assert_failed_without_replacing_feeds(self, **response):
        with mock.patch.object(generator.urllib.request, "urlopen", **response):
            with self.assertRaises(SystemExit) as raised:
                generator.main()
        self.assertNotEqual(raised.exception.code, 0)
        for path in self.root.joinpath("JSON").glob("*.json"):
            self.assertEqual(path.read_bytes(), self.original)
        self.assertFalse(self.root.joinpath("scratch").exists())

    def test_http_failure_fails_and_preserves_feeds(self):
        self.assert_failed_without_replacing_feeds(side_effect=HTTPError(
            "https://api.github.com/repos/Thetromboneman1/APEX/releases",
            503, "Service Unavailable", {}, None,
        ))

    def test_transient_network_failure_fails_and_preserves_feeds(self):
        self.assert_failed_without_replacing_feeds(side_effect=URLError("timed out"))

    def test_malformed_response_fails_and_preserves_feeds(self):
        self.assert_failed_without_replacing_feeds(return_value=io.BytesIO(b"not json"))

    def test_successfully_fetched_empty_list_generates_valid_empty_feeds(self):
        with mock.patch.object(generator.urllib.request, "urlopen", return_value=io.BytesIO(b"[]")):
            generator.main()
        for path in self.root.joinpath("JSON").glob("*.json"):
            data = json.loads(path.read_text())
            self.assertEqual(data["identifier"], "com.thetromboneman1.apex")
            self.assertEqual(data["apps"], [])
        self.assertEqual(self.root.joinpath("JSON/feather.json").read_bytes(),
                         self.root.joinpath("JSON/store.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
