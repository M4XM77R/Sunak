"""Update channels: `sunak update dev` puts the clone on the dev branch (sunak/updates.py, `sunak channel`)."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sunak import updates
from tests.test_updates import commit, git


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class ChannelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        t = Path(self.tmp.name)
        self.remote, self.clone = t / "remote.git", t / "clone"
        git(t, "init", "-q", "--bare", str(self.remote))
        git(t, "clone", "-q", str(self.remote), str(self.clone))
        git(self.clone, "checkout", "-q", "-b", "main")
        commit(self.clone, "a.txt")
        git(self.clone, "push", "-q", "-u", "origin", "main")
        git(self.clone, "checkout", "-q", "-b", "dev")
        commit(self.clone, "dev.txt")
        git(self.clone, "push", "-q", "-u", "origin", "dev")
        git(self.clone, "checkout", "-q", "main")
        git(self.clone, "branch", "-q", "-D", "dev")  # a fresh machine has no local dev branch
        git(self.clone, "remote", "set-head", "origin", "main")

    def tearDown(self):
        self.tmp.cleanup()

    def test_switch_to_dev_and_back(self):
        self.assertEqual(updates.channel(self.clone), "stable")
        ok, _ = updates.switch_channel("dev", self.clone)
        self.assertTrue(ok)
        self.assertEqual(updates.channel(self.clone), "dev")
        self.assertTrue((self.clone / "dev.txt").exists())
        self.assertTrue(updates.switch_channel("dev", self.clone)[0])  # already there
        self.assertTrue(updates.switch_channel("main", self.clone)[0])  # "main" is an alias of stable
        self.assertEqual(updates.channel(self.clone), "stable")
        self.assertFalse((self.clone / "dev.txt").exists())

    def test_dirty_clone_is_left_alone(self):
        (self.clone / "a.txt").write_text("changed", encoding="utf-8")
        ok, message = updates.switch_channel("dev", self.clone)
        self.assertFalse(ok)
        self.assertIn("uncommitted", message)
        self.assertEqual(updates.channel(self.clone), "stable")

    def test_diverged_local_branch_is_left_alone(self):
        updates.switch_channel("dev", self.clone)
        commit(self.clone, "mine.txt")  # a local commit the remote does not have
        updates.switch_channel("stable", self.clone)
        ok, message = updates.switch_channel("dev", self.clone)
        self.assertFalse(ok)
        self.assertIn("commits that the update source does not have", message)

    def test_single_branch_clone_without_dev(self):
        single = Path(self.tmp.name) / "single"
        git(self.tmp.name, "clone", "-q", "--single-branch", "-b", "main", self.remote.as_uri(), str(single))
        git(single, "remote", "set-head", "origin", "main")
        self.assertEqual(git(single, "branch", "-r", "--list", "origin/dev"), "")  # a plain fetch will not bring it
        ok, message = updates.switch_channel("dev", single)
        self.assertTrue(ok, message)
        self.assertEqual(updates.channel(single), "dev")
        self.assertTrue((single / "dev.txt").exists())
        git(single, "fetch", "-q")  # origin/dev is kept up to date from now on
        self.assertIn("origin/dev", git(single, "branch", "-r"))

    def test_detached_head_with_own_commits_is_left_alone(self):
        git(self.clone, "checkout", "-q", "--detach")
        commit(self.clone, "lost.txt")
        ok, message = updates.switch_channel("dev", self.clone)
        self.assertFalse(ok)
        self.assertIn("detached HEAD", message)

    def test_inspect_with_channel_does_not_switch(self):
        r = updates.inspect(self.clone, channel="dev")
        self.assertEqual((r["behind"], r["error"]), (1, ""))
        self.assertEqual(updates.channel(self.clone), "stable")

    def test_missing_branch_and_unknown_channel(self):
        git(self.clone, "push", "-q", "origin", ":dev")
        self.assertIn("does not exist", updates.switch_channel("dev", self.clone)[1])
        self.assertFalse(updates.switch_channel("nightly", self.clone)[0])

    def test_no_clone(self):
        with tempfile.TemporaryDirectory() as d:
            ok, message = updates.switch_channel("dev", Path(d) / "app")
        self.assertFalse(ok)
        self.assertIn("not installed from a git clone", message)


if __name__ == "__main__":
    unittest.main()
