"""collect.py の統合テスト。見本フォルダ（tests/fixtures/）で○側・×側を確かめる。

完成の条件1: 23項目すべての判定を、見本フォルダの○になる場合・×になる場合で確かめる。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import FIXTURES_DIR, TEST_NOW, copy_fixture, make_git_repo  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_collect(tmp_path: Path, workdir: Path, claude_home: Path, codex_home: Path, home: Path) -> dict:
    out_dir = tmp_path / "out"
    cmd = [
        sys.executable,
        str(REPO_ROOT / "collect.py"),
        "--workdir", str(workdir),
        "--out", str(out_dir),
        "--claude-home", str(claude_home),
        "--codex-home", str(codex_home),
        "--home", str(home),
        "--now", TEST_NOW,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"collect.py failed: {proc.stdout}\n{proc.stderr}"
    with (out_dir / "facts.json").open("r", encoding="utf-8") as fh:
        return json.load(fh)


class PassScenarioTest(unittest.TestCase):
    """見本フォルダ（合格側）で、機械判定項目が○になることを確かめる。"""

    @classmethod
    def setUpClass(cls):
        import tempfile

        cls._tmpdir = tempfile.TemporaryDirectory()
        tmp_path = Path(cls._tmpdir.name)
        cls._tmpdir_path = tmp_path

        cls.workdir = copy_fixture("repo_pass", tmp_path / "workdir")
        make_git_repo(cls.workdir, with_remote=True, track_all=True)

        cls.claude_home = copy_fixture("claude_home_pass", tmp_path / "claude_home")
        cls.codex_home = copy_fixture("codex_home_pass", tmp_path / "codex_home")
        cls.home = copy_fixture("home_pass", tmp_path / "home")

        # D2（定時実行が直近30日に動いた）: scheduled-tasks のファイルを「最近」にする
        recent_file = cls.claude_home / "scheduled-tasks" / "daily-job" / "log.txt"
        now_ts = __import__("datetime").datetime.fromisoformat(TEST_NOW).timestamp()
        os.utime(recent_file, (now_ts, now_ts))
        recent_file2 = cls.codex_home / "automations" / "daily" / "log.txt"
        os.utime(recent_file2, (now_ts, now_ts))

        cls.facts = run_collect(tmp_path, cls.workdir, cls.claude_home, cls.codex_home, cls.home)

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def item(self, iid):
        return self.facts["items"][iid]

    def cc(self, iid):
        return self.item(iid)["per_tool"]["claude_code"]

    def codexf(self, iid):
        return self.item(iid)["per_tool"]["codex"]

    def test_f1_pass(self):
        self.assertTrue(self.cc("F1")["pass"])
        self.assertTrue(self.codexf("F1")["pass"])

    def test_f2_pass(self):
        self.assertTrue(self.cc("F2")["pass"])
        self.assertTrue(self.codexf("F2")["pass"])

    def test_f3_f4_target_found(self):
        self.assertTrue(self.item("F3")["per_tool"]["claude_code"]["target_found"])
        self.assertTrue(self.item("F4")["per_tool"]["claude_code"]["target_found"])

    def test_f5_pass(self):
        self.assertTrue(self.cc("F5")["pass"])
        self.assertTrue(self.codexf("F5")["pass"])

    def test_f6_pass(self):
        self.assertTrue(self.cc("F6")["pass"])

    def test_f7_facts_json_has_no_candidate_names(self):
        """HIGH finding #2: facts.json に自作スキル名を入れない。"""
        self.assertNotIn("candidates", self.item("F7")["per_tool"]["claude_code"])

    def test_f7_ai_targets_json_points_to_real_skill_file(self):
        """AIが実際に読むファイルは ai_targets.json（手元用）の側に出す。"""
        ai_targets_path = self._tmpdir_path / "out" / "ai_targets.json"
        with ai_targets_path.open("r", encoding="utf-8") as fh:
            ai_targets = json.load(fh)
        cc_paths = ai_targets["F7"]["claude_code"]
        self.assertEqual(len(cc_paths), 1)
        self.assertTrue(cc_paths[0].endswith("demo-skill/SKILL.md"))
        self.assertTrue(Path(cc_paths[0]).exists())

    def test_f8_pass(self):
        self.assertTrue(self.cc("F8")["pass"])
        self.assertTrue(self.codexf("F8")["pass"])

    def test_f9_pass(self):
        self.assertTrue(self.cc("F9")["pass"])

    def test_f10_pass(self):
        self.assertTrue(self.cc("F10")["pass"])
        self.assertTrue(self.codexf("F10")["pass"])

    def test_f11_pass(self):
        self.assertTrue(self.cc("F11")["pass"])

    def test_s1_pass_no_secrets(self):
        self.assertTrue(self.facts["items"]["S1"]["combined"]["pass"])

    def test_s2_pass(self):
        self.assertTrue(self.cc("S2")["pass"])

    def test_s3_pass(self):
        self.assertTrue(self.cc("S3")["pass"])
        self.assertTrue(self.codexf("S3")["pass"])

    def test_s4_pass(self):
        self.assertTrue(self.cc("S4")["pass"])
        self.assertTrue(self.codexf("S4")["pass"])

    def test_g1_pass(self):
        self.assertTrue(self.facts["items"]["G1"]["combined"]["pass"])

    def test_g2_pass(self):
        self.assertTrue(self.facts["items"]["G2"]["combined"]["pass"])

    def test_g3_candidate_found(self):
        self.assertTrue(self.facts["items"]["G3"]["combined"]["measured"])

    def test_d1_pass(self):
        self.assertTrue(self.cc("D1")["pass"])
        self.assertTrue(self.codexf("D1")["pass"])

    def test_d2_pass(self):
        self.assertTrue(self.cc("D2")["pass"])
        self.assertTrue(self.codexf("D2")["pass"])

    def test_d3_pass_via_stop_hook(self):
        self.assertTrue(self.cc("D3")["pass"])

    def test_d4_pass(self):
        self.assertTrue(self.cc("D4")["pass"])

    def test_d5_pass(self):
        self.assertTrue(self.cc("D5")["pass"])
        self.assertGreaterEqual(self.cc("D5")["max_consecutive"], 20)


class FailScenarioTest(unittest.TestCase):
    """見本フォルダ（不合格側）で、機械判定項目が×になることを確かめる。"""

    @classmethod
    def setUpClass(cls):
        import tempfile

        cls._tmpdir = tempfile.TemporaryDirectory()
        tmp_path = Path(cls._tmpdir.name)

        cls.workdir = copy_fixture("repo_fail", tmp_path / "workdir")
        make_git_repo(cls.workdir, with_remote=False, track_all=True)

        cls.claude_home = copy_fixture("claude_home_fail", tmp_path / "claude_home")
        cls.codex_home = copy_fixture("codex_home_fail", tmp_path / "codex_home")
        cls.home = copy_fixture("home_fail", tmp_path / "home")

        stale_file = cls.claude_home / "scheduled-tasks" / "stale-job" / "log.txt"
        old_ts = __import__("datetime").datetime(2026, 1, 1).timestamp()
        os.utime(stale_file, (old_ts, old_ts))

        cls.facts = run_collect(tmp_path, cls.workdir, cls.claude_home, cls.codex_home, cls.home)

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def item(self, iid):
        return self.facts["items"][iid]

    def cc(self, iid):
        return self.item(iid)["per_tool"]["claude_code"]

    def codexf(self, iid):
        return self.item(iid)["per_tool"]["codex"]

    def test_f1_fail(self):
        self.assertFalse(self.cc("F1")["pass"])
        self.assertFalse(self.codexf("F1")["pass"])

    def test_f5_pass_when_skill_dir_has_entries(self):
        # claude_home_fail はF6/F9の「古い使用」を確かめるためスキル自体は置いている。
        self.assertTrue(self.cc("F5")["pass"])

    def test_f5_fail_when_no_skills_at_all(self):
        """finding #6: F5 の×（自作スキルが1本も無い場合）を見本で確かめる。"""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            workdir = copy_fixture("repo_fail", tmp_path / "workdir")
            make_git_repo(workdir, with_remote=False, track_all=True)
            claude_home = copy_fixture("claude_home_fail", tmp_path / "claude_home")
            shutil.rmtree(claude_home / "skills")
            codex_home = copy_fixture("codex_home_fail", tmp_path / "codex_home")
            home = copy_fixture("home_fail", tmp_path / "home")
            facts = run_collect(tmp_path, workdir, claude_home, codex_home, home)
            f5 = facts["items"]["F5"]["per_tool"]["claude_code"]
            self.assertTrue(f5["measured"])
            self.assertFalse(f5["pass"])
            self.assertEqual(f5["count"], 0)

    def test_f8_fail_when_no_agents_at_all(self):
        """finding #6: F8 の×（エージェント定義が1つも無い場合）を見本で確かめる。"""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            workdir = copy_fixture("repo_fail", tmp_path / "workdir")
            make_git_repo(workdir, with_remote=False, track_all=True)
            claude_home = copy_fixture("claude_home_fail", tmp_path / "claude_home")
            shutil.rmtree(claude_home / "agents")
            codex_home = copy_fixture("codex_home_fail", tmp_path / "codex_home")
            home = copy_fixture("home_fail", tmp_path / "home")
            facts = run_collect(tmp_path, workdir, claude_home, codex_home, home)
            f8 = facts["items"]["F8"]["per_tool"]["claude_code"]
            self.assertTrue(f8["measured"])
            self.assertFalse(f8["pass"])
            self.assertEqual(f8["count"], 0)

    def test_f6_fail_old_usage(self):
        self.assertFalse(self.cc("F6")["pass"])

    def test_f9_fail_old_usage(self):
        self.assertFalse(self.cc("F9")["pass"])

    def test_f10_fail_no_connector(self):
        self.assertFalse(self.cc("F10")["pass"])

    def test_f11_fail(self):
        self.assertFalse(self.cc("F11")["pass"])

    def test_s1_fail_secret_detected(self):
        s1 = self.facts["items"]["S1"]["combined"]
        self.assertFalse(s1["pass"])
        total = sum(s1["repo"]["counts_by_kind"].values()) + sum(s1["config"]["counts_by_kind"].values())
        self.assertGreater(total, 0)

    def test_s2_fail(self):
        self.assertFalse(self.cc("S2")["pass"])

    def test_s3_fail(self):
        self.assertFalse(self.cc("S3")["pass"])
        self.assertFalse(self.codexf("S3")["pass"])

    def test_s4_fail(self):
        self.assertFalse(self.cc("S4")["pass"])
        self.assertFalse(self.codexf("S4")["pass"])

    def test_g1_fail_no_remote(self):
        self.assertFalse(self.facts["items"]["G1"]["combined"]["pass"])

    def test_g2_fail_no_content(self):
        self.assertFalse(self.facts["items"]["G2"]["combined"]["pass"])

    def test_d1_fail(self):
        # Codex 側は approval_policy="never" で「毎回確認」ではないため、
        # D1（確認なしで通る）としては○になる（S3/S4 とは別の軸）。
        # そのため D1 の×は Claude Code 側の allow 無し・bypassPermissions で確認する。
        self.assertFalse(self.cc("D1")["pass"])

    def test_d1_fail_codex_always_ask(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            codex_home = copy_fixture("codex_home_fail", tmp_path / "codex_home_always_ask")
            (codex_home / "config.toml").write_text(
                'model = "gpt-test"\napproval_policy = "untrusted"\nsandbox_mode = "workspace-write"\n',
                encoding="utf-8",
            )
            workdir = copy_fixture("repo_fail", tmp_path / "workdir")
            make_git_repo(workdir, with_remote=False, track_all=True)
            claude_home = copy_fixture("claude_home_fail", tmp_path / "claude_home")
            home = copy_fixture("home_fail", tmp_path / "home")
            facts = run_collect(tmp_path, workdir, claude_home, codex_home, home)
            self.assertFalse(facts["items"]["D1"]["per_tool"]["codex"]["pass"])

    def test_d2_fail_stale(self):
        self.assertFalse(self.cc("D2")["pass"])

    def test_d3_needs_ai_fallback(self):
        self.assertTrue(self.item("D3")["needs_ai"])

    def test_d4_fail(self):
        self.assertFalse(self.cc("D4")["pass"])

    def test_d5_fail(self):
        self.assertFalse(self.cc("D5")["pass"])


class F2LongInstructionTest(unittest.TestCase):
    """F2 単独: 長すぎる指示ファイルで× になることを確かめる（別フィクスチャ）。"""

    def test_f2_fail_too_long(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            workdir = copy_fixture("repo_long", tmp_path / "workdir")
            make_git_repo(workdir, with_remote=True, track_all=True)
            claude_home = copy_fixture("claude_home_pass", tmp_path / "claude_home")
            codex_home = copy_fixture("codex_home_pass", tmp_path / "codex_home")
            home = copy_fixture("home_pass", tmp_path / "home")
            facts = run_collect(tmp_path, workdir, claude_home, codex_home, home)
            self.assertFalse(facts["items"]["F2"]["per_tool"]["claude_code"]["pass"])
            self.assertFalse(facts["items"]["F2"]["per_tool"]["codex"]["pass"])

    def test_f2_fail_when_global_rules_file_too_long(self):
        """v2.1: F2・F4 の対象に全体用rules（~/.claude/rules/*.md）を追加した件の回帰テスト。"""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            workdir = copy_fixture("repo_pass", tmp_path / "workdir")
            make_git_repo(workdir, with_remote=True, track_all=True)
            claude_home = copy_fixture("claude_home_pass", tmp_path / "claude_home")
            long_text = "\n".join(f"- 行 {i}" for i in range(250))
            (claude_home / "rules" / "01-global-rule.md").write_text(long_text, encoding="utf-8")
            codex_home = copy_fixture("codex_home_pass", tmp_path / "codex_home")
            home = copy_fixture("home_pass", tmp_path / "home")
            facts = run_collect(tmp_path, workdir, claude_home, codex_home, home)
            f2 = facts["items"]["F2"]["per_tool"]["claude_code"]
            self.assertFalse(f2["pass"])
            self.assertGreaterEqual(f2["file_count"], 3)  # global CLAUDE.md + local CLAUDE.md + global rule


if __name__ == "__main__":
    unittest.main()
