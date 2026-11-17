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


def _jsonl_line(ts: str, sub_type: str, **extra) -> str:
    payload = {"type": sub_type, **extra}
    return json.dumps({"timestamp": ts, "type": "response_item", "payload": payload}, ensure_ascii=False)


def _human_line(ts: str) -> str:
    return _jsonl_line(ts, "message", role="user")


def write_codex_session(path, filename_dt: str, lines: list[str]) -> None:
    """Codex の会話の記録（平文の見本）を1件書く。filename_dt は 'YYYY-MM-DDTHH-MM-SS' の形。"""
    path.mkdir(parents=True, exist_ok=True)
    f = path / f"rollout-{filename_dt}-00000000-0000-0000-0000-000000000000.jsonl"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_codex_compressed_session(path, filename_dt: str) -> None:
    """圧縮済み（見本は本物のzstdでなくてよい。拡張子だけで読まない判定を確かめる）。"""
    path.mkdir(parents=True, exist_ok=True)
    f = path / f"rollout-{filename_dt}-11111111-1111-1111-1111-111111111111.jsonl.zst"
    f.write_bytes(b"\x28\xb5\x2f\xfd not a real zstd frame, just bytes")


class CodexNewConfigFormatTest(unittest.TestCase):
    """新しい設定の書き方（`default_permissions` 等）でも、安全の柱の項目が判定できることを確かめる。

    見本（codex_home_fail）には旧キー（approval_policy・sandbox_mode）が無いので、
    新キーだけを置いた config.toml に差し替えて確かめる（旧キーのみの見本は codex_home_pass/fail で
    既にカバーされている）。
    """

    def _run_with_config(self, tmp_path: Path, config_text: str) -> dict:
        workdir = copy_fixture("repo_fail", tmp_path / "workdir")
        make_git_repo(workdir, with_remote=False, track_all=True)
        claude_home = copy_fixture("claude_home_fail", tmp_path / "claude_home")
        codex_home = copy_fixture("codex_home_fail", tmp_path / "codex_home")
        (codex_home / "config.toml").write_text(config_text, encoding="utf-8")
        home = copy_fixture("home_fail", tmp_path / "home")
        return run_collect(tmp_path, workdir, claude_home, codex_home, home)

    def test_s3_s4_d1_pass_with_default_permissions_workspace(self):
        """旧キー無し・新キー `default_permissions = ":workspace"` だけで判定できる。"""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            facts = self._run_with_config(Path(td), 'model = "gpt-test"\ndefault_permissions = ":workspace"\n')
            codex = facts["items"]
            self.assertTrue(codex["S3"]["per_tool"]["codex"]["measured"])
            self.assertTrue(codex["S3"]["per_tool"]["codex"]["pass"])
            self.assertTrue(codex["S4"]["per_tool"]["codex"]["measured"])
            self.assertTrue(codex["S4"]["per_tool"]["codex"]["pass"])
            self.assertTrue(codex["D1"]["per_tool"]["codex"]["measured"])
            self.assertTrue(codex["D1"]["per_tool"]["codex"]["pass"])

    def test_s3_fails_with_default_permissions_danger_full_access(self):
        """オーナーの実環境と同じ形（`default_permissions = ":danger-full-access"` のみ）。

        以前は approval_policy・sandbox_mode が無いため「測定できず」だった。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            facts = self._run_with_config(
                Path(td), 'model = "gpt-test"\ndefault_permissions = ":danger-full-access"\n'
            )
            s3 = facts["items"]["S3"]["per_tool"]["codex"]
            self.assertTrue(s3["measured"])
            self.assertFalse(s3["pass"])
            self.assertTrue(s3["full_access"])

    def test_s2_pass_via_custom_permission_profile_filesystem_deny(self):
        """新しい許可の仕組み（`permissions.<name>.filesystem`）で秘密ファイルの読み取りを拒否している。"""
        import tempfile

        config = (
            'model = "gpt-test"\n'
            'default_permissions = "myprofile"\n'
            "\n"
            "[permissions.myprofile]\n"
            'description = "demo"\n'
            "\n"
            "[permissions.myprofile.filesystem]\n"
            '".env" = "deny"\n'
            '"id_rsa" = "deny"\n'
        )
        with tempfile.TemporaryDirectory() as td:
            facts = self._run_with_config(Path(td), config)
            s2 = facts["items"]["S2"]["per_tool"]["codex"]
            self.assertTrue(s2["measured"])
            self.assertTrue(s2["pass"])
            self.assertEqual(s2["rule_count"], 2)

    def test_s2_fail_via_custom_permission_profile_without_deny(self):
        import tempfile

        config = (
            'model = "gpt-test"\n'
            'default_permissions = "myprofile"\n'
            "\n"
            "[permissions.myprofile]\n"
            'description = "demo"\n'
            "\n"
            "[permissions.myprofile.filesystem]\n"
            '"**" = "read"\n'
        )
        with tempfile.TemporaryDirectory() as td:
            facts = self._run_with_config(Path(td), config)
            s2 = facts["items"]["S2"]["per_tool"]["codex"]
            self.assertTrue(s2["measured"])
            self.assertFalse(s2["pass"])
            self.assertEqual(s2["rule_count"], 0)

    def test_s2_unmeasured_with_builtin_profile(self):
        """組み込みプロファイル（`:read-only` 等）には自分で設定できる許可の仕組みが無いので測定できず。"""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            facts = self._run_with_config(Path(td), 'model = "gpt-test"\ndefault_permissions = ":read-only"\n')
            s2 = facts["items"]["S2"]["per_tool"]["codex"]
            self.assertFalse(s2["measured"])


class CodexSessionLogTest(unittest.TestCase):
    """会話の記録（平文の .jsonl）から D5・F11 が判定できることを確かめる。

    圧縮済み（.jsonl.zst）は標準機能では読めないため、件数には数えるが中身は読まない。
    """

    def _run_with_sessions(self, tmp_path: Path, build_sessions) -> dict:
        workdir = copy_fixture("repo_fail", tmp_path / "workdir")
        make_git_repo(workdir, with_remote=False, track_all=True)
        claude_home = copy_fixture("claude_home_fail", tmp_path / "claude_home")
        codex_home = copy_fixture("codex_home_fail", tmp_path / "codex_home")
        build_sessions(codex_home / "sessions")
        home = copy_fixture("home_fail", tmp_path / "home")
        return run_collect(tmp_path, workdir, claude_home, codex_home, home)

    def test_d5_and_f11_pass_from_plain_session(self):
        def build(sessions_dir):
            # 1本の会話: 人の発言 → 連続21回の道具呼び出し（うち1回はコネクタ）→ D5・F11 とも○
            ts = "2026-11-05T09:00:00Z"
            lines = [_human_line(ts)]
            for i in range(20):
                lines.append(_jsonl_line(ts, "custom_tool_call", name="exec"))
            lines.append(_jsonl_line(ts, "function_call", name="js", namespace="mcp__cua_repl"))
            write_codex_session(sessions_dir / "2026" / "11" / "05", "2026-11-05T09-00-00", lines)

        with __import__("tempfile").TemporaryDirectory() as td:
            facts = self._run_with_sessions(Path(td), build)
            codex_items = facts["items"]
            d5 = codex_items["D5"]["per_tool"]["codex"]
            f11 = codex_items["F11"]["per_tool"]["codex"]
            self.assertTrue(d5["measured"])
            self.assertTrue(d5["pass"])
            self.assertGreaterEqual(d5["max_consecutive"], 20)
            self.assertEqual(d5["read_session_count"], 1)
            self.assertTrue(f11["measured"])
            self.assertTrue(f11["pass"])

    def test_d5_and_f11_fail_from_plain_session_without_mcp_or_long_run(self):
        def build(sessions_dir):
            ts = "2026-11-06T09:00:00Z"
            lines = [_human_line(ts), _jsonl_line(ts, "custom_tool_call", name="exec"),
                     _jsonl_line(ts, "custom_tool_call", name="exec")]
            write_codex_session(sessions_dir / "2026" / "11" / "06", "2026-11-06T09-00-00", lines)

        with __import__("tempfile").TemporaryDirectory() as td:
            facts = self._run_with_sessions(Path(td), build)
            codex_items = facts["items"]
            d5 = codex_items["D5"]["per_tool"]["codex"]
            f11 = codex_items["F11"]["per_tool"]["codex"]
            self.assertTrue(d5["measured"])
            self.assertFalse(d5["pass"])
            self.assertTrue(f11["measured"])
            self.assertFalse(f11["pass"])

    def test_compressed_sessions_are_counted_but_not_guessed(self):
        """直近30日ぶんがすべて .jsonl.zst のときは「測定できず」。読めなかった件数は facts に残る。"""

        def build(sessions_dir):
            write_codex_compressed_session(sessions_dir / "2026" / "11" / "07", "2026-11-07T09-00-00")
            write_codex_compressed_session(sessions_dir / "2026" / "11" / "08", "2026-11-08T09-00-00")

        with __import__("tempfile").TemporaryDirectory() as td:
            facts = self._run_with_sessions(Path(td), build)
            codex_items = facts["items"]
            d5 = codex_items["D5"]["per_tool"]["codex"]
            f11 = codex_items["F11"]["per_tool"]["codex"]
            self.assertFalse(d5["measured"])
            self.assertIsNone(d5["pass"])
            self.assertEqual(d5["unreadable_session_count"], 2)
            self.assertEqual(d5["read_session_count"], 0)
            self.assertFalse(f11["measured"])

    def test_old_sessions_outside_window_are_ignored(self):
        def build(sessions_dir):
            ts = "2026-01-01T09:00:00Z"
            lines = [_human_line(ts)] + [_jsonl_line(ts, "custom_tool_call", name="exec") for _ in range(30)]
            write_codex_session(sessions_dir / "2026" / "01" / "01", "2026-01-01T09-00-00", lines)

        with __import__("tempfile").TemporaryDirectory() as td:
            facts = self._run_with_sessions(Path(td), build)
            d5 = facts["items"]["D5"]["per_tool"]["codex"]
            self.assertFalse(d5["measured"])
            self.assertEqual(d5["read_session_count"], 0)
            self.assertEqual(d5["unreadable_session_count"], 0)

    def test_no_sessions_at_all_is_unmeasured(self):
        def build(sessions_dir):
            pass

        with __import__("tempfile").TemporaryDirectory() as td:
            facts = self._run_with_sessions(Path(td), build)
            d5 = facts["items"]["D5"]["per_tool"]["codex"]
            f11 = facts["items"]["F11"]["per_tool"]["codex"]
            self.assertFalse(d5["measured"])
            self.assertFalse(f11["measured"])


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
