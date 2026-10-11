"""Integration coverage for idempotent upstream-sync publication."""

import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FINALIZER = ROOT / "scripts" / "finalize-upstream-sync.sh"


class FinalizeUpstreamSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.origin = self.root / "origin.git"
        self.work = self.root / "work"
        self.state = self.root / "pr.json"
        self.create_count = self.root / "create-count"
        self.close_count = self.root / "close-count"
        self.bin = self.root / "bin"
        self.bin.mkdir()

        self.git("init", "--bare", str(self.origin), cwd=self.root)
        self.git("init", "-b", "main", str(self.work), cwd=self.root)
        self.git("config", "user.name", "Test Bot")
        self.git("config", "user.email", "test@example.invalid")
        self.work.joinpath("common.txt").write_text("common\n", encoding="utf-8")
        self.git("add", "common.txt")
        self.git("commit", "-m", "common")
        common = self.git("rev-parse", "HEAD").stdout.strip()

        self.git("switch", "-c", "upstream")
        self.work.joinpath("upstream.txt").write_text("upstream\n", encoding="utf-8")
        self.git("add", "upstream.txt")
        self.git("commit", "-m", "upstream")
        self.upstream = self.git("rev-parse", "HEAD").stdout.strip()

        self.git("switch", "-C", "main", common)
        self.work.joinpath("downstream.txt").write_text("downstream\n", encoding="utf-8")
        self.git("add", "downstream.txt")
        self.git("commit", "-m", "downstream")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("remote", "add", "origin", str(self.origin))
        self.git("push", "origin", "main", "upstream")
        self.git("merge", "--no-edit", self.upstream)
        self.tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()

        fake_gh = self.bin / "gh"
        fake_gh.write_text(
            """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys

state = Path(os.environ["GH_STATE"])
count = Path(os.environ["GH_CREATE_COUNT"])
close_count = Path(os.environ["GH_CLOSE_COUNT"])
args = sys.argv[1:]

def record():
    return json.loads(state.read_text(encoding="utf-8")) if state.exists() else None

def emit(item):
    if item:
        fields = [item["url"], item["base"], item["head"]]
        if args[:1] == ["api"] or any("headRepository" in arg for arg in args):
            fields.append(item["head_repository"])
        if args[:1] == ["api"] or any("isCrossRepository" in arg for arg in args):
            fields.append("true" if item["is_cross_repository"] else "false")
        if args[:1] == ["api"]:
            fields.append(item.get("head_ref", os.environ["EXPECTED_BRANCH"]))
        print("\\t".join(fields))

if args[:1] == ["api"]:
    items = record()
    for item in items if isinstance(items, list) else [items]:
        emit(item)
elif args[:2] == ["pr", "create"]:
    count.write_text(count.read_text() + "1\\n" if count.exists() else "1\\n")
    branch = args[args.index("--head") + 1]
    head = subprocess.run(
        ["git", "ls-remote", "origin", f"refs/heads/{branch}"],
        check=True, capture_output=True, text=True,
    ).stdout.split()[0]
    item = {
        "url": "https://example.invalid/pull/1",
        "base": "f" * 40 if os.environ.get("GH_STALE_BASE") == "1" else os.environ["BASE_SHA"],
        "head": head,
        "head_repository": os.environ.get(
            "GH_CREATED_HEAD_REPOSITORY", os.environ["GITHUB_REPOSITORY"],
        ),
        "is_cross_repository": os.environ.get("GH_CREATED_CROSS_REPOSITORY") == "1",
    }
    state.write_text(json.dumps(item), encoding="utf-8")
    if os.environ.get("GH_CREATE_RACE") == "1":
        raise SystemExit(1)
    print(item["url"])
elif args[:2] == ["pr", "view"]:
    items = record()
    emit(items[-1] if isinstance(items, list) else items)
elif args[:2] == ["pr", "close"]:
    close_count.write_text("1\\n")
else:
    raise SystemExit(f"unexpected gh invocation: {args}")
""",
            encoding="utf-8",
        )
        fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IXUSR)

    def git(self, *args, cwd=None, **kwargs):
        return subprocess.run(
            ["git", *args], cwd=cwd or self.work, check=True,
            capture_output=True, text=True, **kwargs,
        )

    def finalize(self, cwd=None, **extra_env):
        env = os.environ.copy()
        env.update({
            "PATH": f"{self.bin}{os.pathsep}{env['PATH']}",
            "GH_STATE": str(self.state),
            "GH_CREATE_COUNT": str(self.create_count),
            "GH_CLOSE_COUNT": str(self.close_count),
            "BASE_SHA": self.base,
            "UPSTREAM_SHA": self.upstream,
            "EXPECTED_TREE": self.tree,
            "DOWNSTREAM_BRANCH": "main",
            "UPSTREAM_REPOSITORY": "example/upstream",
            "GITHUB_REPOSITORY": "example/downstream",
            "EXPECTED_BRANCH": (
                f"automation/upstream-sync-{self.base[:12]}-{self.upstream[:12]}"
            ),
        })
        env.update(extra_env)
        return subprocess.run(
            [str(FINALIZER)], cwd=cwd or self.work, env=env, check=True,
            capture_output=True, text=True,
        )

    def test_repeated_equivalent_candidate_reuses_one_pull_request(self):
        first = self.finalize()
        self.assertIn("https://example.invalid/pull/1", first.stdout)

        # A rerun can produce a different merge commit ID from the same exact
        # base and upstream because merge metadata is time-dependent.
        self.git("commit", "--amend", "--no-edit", env={
            **os.environ, "GIT_COMMITTER_DATE": "2030-01-01T00:00:00Z",
        })
        self.assertNotEqual(
            self.git("rev-parse", "HEAD").stdout.strip(),
            json.loads(self.state.read_text())["head"],
        )
        second = self.finalize()

        self.assertIn("https://example.invalid/pull/1", second.stdout)
        self.assertEqual(self.create_count.read_text().splitlines(), ["1"])

    def test_concurrent_pr_creation_race_reuses_exact_winner(self):
        result = self.finalize(GH_CREATE_RACE="1")

        self.assertIn("https://example.invalid/pull/1", result.stdout)
        self.assertEqual(self.create_count.read_text().splitlines(), ["1"])

    def test_inbound_fork_pr_with_same_branch_name_is_not_reused(self):
        self.state.write_text(json.dumps({
            "url": "https://example.invalid/pull/fork",
            "base": self.base,
            "head": self.git("rev-parse", "HEAD").stdout.strip(),
            "head_repository": "attacker/APEX",
            "is_cross_repository": True,
        }), encoding="utf-8")

        result = self.finalize()

        self.assertNotIn("https://example.invalid/pull/fork", result.stdout)
        self.assertIn("https://example.invalid/pull/1", result.stdout)
        self.assertEqual(self.create_count.read_text().splitlines(), ["1"])

    def test_created_pr_is_closed_if_revalidation_reports_a_fork_head(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.finalize(
                GH_CREATED_HEAD_REPOSITORY="attacker/APEX",
                GH_CREATED_CROSS_REPOSITORY="1",
            )

        self.assertEqual(self.close_count.read_text(), "1\n")

    def test_create_race_does_not_reuse_inbound_fork_winner(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.finalize(
                GH_CREATE_RACE="1",
                GH_CREATED_HEAD_REPOSITORY="attacker/APEX",
                GH_CREATED_CROSS_REPOSITORY="1",
            )

        self.assertFalse(self.close_count.exists())

    def test_fork_candidate_before_same_repo_candidate_reuses_owned_pr(self):
        candidate = self.git("rev-parse", "HEAD").stdout.strip()
        self.state.write_text(json.dumps([
            {
                "url": "https://example.invalid/pull/fork",
                "base": self.base,
                "head": candidate,
                "head_repository": "attacker/APEX",
                "is_cross_repository": True,
            },
            {
                "url": "https://example.invalid/pull/owned",
                "base": self.base,
                "head": candidate,
                "head_repository": "example/downstream",
                "is_cross_repository": False,
            },
        ]), encoding="utf-8")

        result = self.finalize()

        self.assertNotIn("https://example.invalid/pull/fork", result.stdout)
        self.assertIn("https://example.invalid/pull/owned", result.stdout)
        self.assertFalse(self.create_count.exists())

    def test_owned_pr_is_found_after_more_than_thirty_fork_candidates(self):
        candidate = self.git("rev-parse", "HEAD").stdout.strip()
        forks = [
            {
                "url": f"https://example.invalid/pull/fork-{index}",
                "base": self.base,
                "head": candidate,
                "head_repository": f"attacker-{index}/APEX",
                "is_cross_repository": True,
            }
            for index in range(31)
        ]
        owned = {
            "url": "https://example.invalid/pull/owned",
            "base": self.base,
            "head": candidate,
            "head_repository": "example/downstream",
            "is_cross_repository": False,
        }
        self.state.write_text(json.dumps([*forks, owned]), encoding="utf-8")

        result = self.finalize()

        self.assertIn("https://example.invalid/pull/owned", result.stdout)
        self.assertFalse(self.create_count.exists())

    def test_fast_forward_candidate_is_published_and_reused(self):
        ff_origin = self.root / "ff-origin.git"
        ff_work = self.root / "ff-work"
        self.git("init", "--bare", str(ff_origin), cwd=self.root)
        self.git("init", "-b", "main", str(ff_work), cwd=self.root)
        self.git("config", "user.name", "Test Bot", cwd=ff_work)
        self.git("config", "user.email", "test@example.invalid", cwd=ff_work)
        ff_work.joinpath("base.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "base.txt", cwd=ff_work)
        self.git("commit", "-m", "base", cwd=ff_work)
        base = self.git("rev-parse", "HEAD", cwd=ff_work).stdout.strip()
        self.git("remote", "add", "origin", str(ff_origin), cwd=ff_work)
        self.git("push", "origin", "main", cwd=ff_work)
        ff_work.joinpath("upstream.txt").write_text("upstream\n", encoding="utf-8")
        self.git("add", "upstream.txt", cwd=ff_work)
        self.git("commit", "-m", "upstream", cwd=ff_work)
        upstream = self.git("rev-parse", "HEAD", cwd=ff_work).stdout.strip()
        tree = self.git("rev-parse", "HEAD^{tree}", cwd=ff_work).stdout.strip()

        result = self.finalize(
            cwd=ff_work, BASE_SHA=base, UPSTREAM_SHA=upstream, EXPECTED_TREE=tree,
        )

        self.assertIn("https://example.invalid/pull/1", result.stdout)
        self.assertEqual(self.create_count.read_text().splitlines(), ["1"])

    def test_new_pr_with_advanced_base_is_closed_and_fails(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.finalize(GH_STALE_BASE="1")

        self.assertEqual(self.close_count.read_text(), "1\n")

    def test_privileged_job_runs_trusted_finalizer_snapshot(self):
        workflow = ROOT.joinpath(".github/workflows/upstream-sync.yml").read_text()
        finalize = workflow.split("  finalize:", 1)[1]
        snapshot = 'cp scripts/finalize-upstream-sync.sh "$trusted_finalizer"'
        merge = 'git merge --no-edit "$UPSTREAM_SHA"'
        execute = 'bash "$trusted_finalizer"'

        self.assertLess(finalize.index(snapshot), finalize.index(merge))
        self.assertLess(finalize.index(merge), finalize.index(execute))


if __name__ == "__main__":
    unittest.main()
