"""v2.5（SPEC 16章）の基準の締め直しを確かめる。

- 何もしなくても○にしない（S1・S4 は調べる対象が0個なら測定できず）
- 判定できた数が少ないときは、点数と型の名前を出さない
- S2 は2系統・S3 は3系統をすべて止めていれば○。フックで止めているものも数える
- 表紙のダッシュボードの数（日別・使われている本数・任せた量）
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import score  # noqa: E402
from helpers import TEST_NOW, copy_fixture, make_git_repo  # noqa: E402
from readers import claude_code, common  # noqa: E402


def _run(tmp: Path, workdir: Path, claude_home: Path, codex_home: Path, home: Path) -> dict:
    out = tmp / "out"
    base = ["--out", str(out)]
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "collect.py"), "--workdir", str(workdir), *base,
         "--claude-home", str(claude_home), "--codex-home", str(codex_home), "--home", str(home), "--now", TEST_NOW],
        check=True, capture_output=True, text=True, timeout=60,
    )
    subprocess.run([sys.executable, str(REPO_ROOT / "score.py"), *base], check=True, capture_output=True, text=True,
                   timeout=60)
    return json.loads((out / "result.json").read_text(encoding="utf-8"))


class EmptyEnvironmentTest(unittest.TestCase):
    """設定がほぼ空の環境で、点が出たり「安全は強く」になったりしない。"""

    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        tmp = Path(cls._td.name)
        empty = tmp / "empty"
        empty.mkdir()
        cls.result = _run(tmp, empty, empty / ".claude", empty / ".codex", empty)

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def test_s1_is_unmeasured_when_nothing_was_scanned(self):
        self.assertEqual(self.result["items"]["S1"]["status"], "unmeasured")

    def test_score_and_type_are_withheld(self):
        self.assertIsNone(self.result["score"])
        self.assertIsNone(self.result["type_name"])
        self.assertTrue(self.result["score_withheld"])

    def test_dashboard_is_null_without_records(self):
        self.assertIsNone(self.result["daily_30d"])
        self.assertIsNone(self.result["usage_breadth"])
        self.assertIsNone(self.result["autonomy"])


class S4NoSettingsTest(unittest.TestCase):
    def test_s4_unmeasured_without_any_settings_file(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            workdir = copy_fixture("repo_pass", tmp / "workdir")
            make_git_repo(workdir)
            claude_home = copy_fixture("claude_home_pass", tmp / "claude_home")
            (claude_home / "settings.json").unlink()
            facts = claude_code.collect_facts(workdir, claude_home, now=datetime.fromisoformat(TEST_NOW))
            self.assertFalse(facts["S4"]["measured"])
            self.assertIsNone(facts["S4"]["pass"])


class SecretCoverageTest(unittest.TestCase):
    def cov(self, deny=(), ask=(), hooks=()):
        return claude_code.secret_coverage({"deny": list(deny), "ask": list(ask)}, list(hooks))

    def test_env_only_is_not_enough(self):
        c = self.cov(deny=["Read(./.env)"])
        self.assertEqual(c, {"env": True, "keys": False})
        self.assertFalse(all(c.values()))

    def test_env_and_keys_pass(self):
        self.assertTrue(all(self.cov(deny=["Read(./.env*)", "Read(~/.ssh/**)"]).values()))

    def test_non_read_rule_does_not_count(self):
        self.assertFalse(any(self.cov(deny=["Bash(cat .env:*)", "Edit(id_rsa)"]).values()))

    def test_hook_text_counts(self):
        hook = "#!/bin/sh\ncase \"$1\" in *.env|*id_rsa*) exit 2;; esac\n"
        self.assertTrue(all(self.cov(hooks=[hook]).values()))


class DestructiveCoverageTest(unittest.TestCase):
    def cov(self, rules=(), hooks=()):
        return claude_code.destructive_coverage({"deny": list(rules), "ask": []}, list(hooks))

    def test_single_curl_rule_is_not_enough(self):
        c = self.cov(["Bash(curl:*)"])
        self.assertEqual(c, {"delete": False, "force": False, "outward": True})

    def test_rm_and_git_push_cover_all_three(self):
        # git push を止めれば強制の push も止まるので「強制上書き」にも数える（16-2）
        self.assertTrue(all(self.cov(["Bash(rm:*)", "Bash(git push:*)"]).values()))

    def test_rm_word_boundary(self):
        self.assertFalse(self.cov(["Bash(npm run format:*)", "Bash(confirm:*)"])["delete"])
        self.assertTrue(self.cov(["Bash(rm -rf:*)"])["delete"])

    def test_hook_text_counts(self):
        hook = "if echo \"$CMD\" | grep -E 'rm -rf|reset --hard|git push'; then exit 2; fi"
        self.assertTrue(all(self.cov(hooks=[hook]).values()))


class HookFileIsReadTest(unittest.TestCase):
    """PreToolUse のフックが指すファイルの中身まで読んで、系統を数える（実行はしない）。"""

    def test_hook_script_contents_count_for_s2_and_s3(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            workdir = copy_fixture("repo_pass", tmp / "workdir")
            make_git_repo(workdir)
            claude_home = copy_fixture("claude_home_pass", tmp / "claude_home")
            guard = claude_home / "hooks" / "guard.sh"
            guard.parent.mkdir()
            guard.write_text("#!/bin/sh\n# .env id_rsa rm -rf reset --hard git push\nexit 0\n", encoding="utf-8")
            settings = {
                "permissions": {"deny": [], "ask": []},
                "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": f"sh {guard}"}]}]},
            }
            (claude_home / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
            facts = claude_code.collect_facts(workdir, claude_home, now=datetime.fromisoformat(TEST_NOW))
            self.assertTrue(facts["S2"]["pass"])
            self.assertTrue(facts["S3"]["pass"])
            self.assertEqual(facts["S2"]["hook_count"], 1)
            # 命令の文字列・場所は facts に入れない
            self.assertNotIn(str(guard), json.dumps(facts["S2"]) + json.dumps(facts["S3"]))


class SufficiencyTest(unittest.TestCase):
    PILLARS = {"foundation": "土台", "safety": "安全", "grow": "育つ仕組み", "delegate": "任せ方"}
    ORDER = ["foundation", "safety", "grow", "delegate"]
    TOTALS = {"foundation": 8, "safety": 4, "grow": 3, "delegate": 5}

    def summary(self, judged: dict, passed: dict) -> dict:
        items = []
        for pid, total in self.TOTALS.items():
            for i in range(total):
                if i < judged[pid]:
                    st = "pass" if i < passed[pid] else "fail"
                    items.append({"pillar": pid, "status": st, "credit": 1.0 if st == "pass" else 0.0})
                else:
                    items.append({"pillar": pid, "status": "unmeasured", "credit": None})
        return score.compute_pillar_summary(items, self.PILLARS, self.ORDER)

    def test_half_is_enough(self):
        self.assertTrue(score.is_sufficient(4, 8))
        self.assertTrue(score.is_sufficient(2, 3))
        self.assertFalse(score.is_sufficient(1, 3))
        self.assertFalse(score.is_sufficient(9, 20))
        self.assertTrue(score.is_sufficient(10, 20))

    def test_one_judged_item_does_not_make_a_pillar_strong(self):
        s = self.summary({"foundation": 8, "safety": 1, "grow": 2, "delegate": 3},
                         {"foundation": 4, "safety": 1, "grow": 0, "delegate": 0})
        self.assertFalse(s["safety"]["sufficient"])
        self.assertEqual(s["safety"]["rate"], 1.0)
        name = score.compute_type_name(s)
        self.assertNotIn("安全", name)
        sc, _ = score.compute_score(s)
        # 安全（判定不足）を除いた3本: 0.5, 0, 0 の平均
        self.assertEqual(sc, 17)

    def test_overall_withheld_below_half(self):
        s = self.summary({"foundation": 4, "safety": 2, "grow": 2, "delegate": 1},
                         {"foundation": 4, "safety": 2, "grow": 2, "delegate": 1})
        sc, judged = score.compute_score(s)
        self.assertEqual(judged, 9)
        self.assertIsNone(sc)
        self.assertIsNone(score.compute_type_name(s))


class DailyActivityTest(unittest.TestCase):
    def test_thirty_days_in_jst_oldest_first(self):
        now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)  # JST 21:00
        # JST 11-11 00:10 と 00:12（= UTC 11-10 15:10, 15:12）。2分の連続
        t1 = datetime(2026, 11, 10, 15, 10, tzinfo=timezone.utc).timestamp()
        t2 = datetime(2026, 11, 10, 15, 12, tzinfo=timezone.utc).timestamp()
        days = common.daily_activity_jst([t1, t2], [t1], now=now, days=30)
        self.assertEqual(len(days), 30)
        self.assertEqual(days[-1]["date"], "11-11")
        self.assertEqual(days[-1]["active_seconds"], 120)
        self.assertEqual(days[-1]["sessions"], 1)
        self.assertEqual(days[-2]["active_seconds"], 0)
        self.assertEqual(days[0]["date"], "10-13")


class DashboardInResultTest(unittest.TestCase):
    def test_pass_fixture_has_dashboard_numbers_without_names(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            workdir = copy_fixture("repo_pass", tmp / "workdir")
            make_git_repo(workdir)
            claude_home = copy_fixture("claude_home_pass", tmp / "claude_home")
            codex_home = copy_fixture("codex_home_pass", tmp / "codex_home")
            home = copy_fixture("home_pass", tmp / "home")
            res = _run(tmp, workdir, claude_home, codex_home, home)
        self.assertEqual(len(res["daily_30d"]), 30)
        self.assertEqual(set(res["usage_breadth"]), {"skills", "agents", "connectors"})
        for v in res["usage_breadth"].values():
            self.assertLessEqual(v["used"], v["own"])
        self.assertEqual(set(res["autonomy"]),
                         {"tool_calls_30d", "max_consecutive", "sessions_20plus", "agent_relay_sessions"})
        dumped = json.dumps({k: res[k] for k in ("daily_30d", "usage_breadth", "autonomy")})
        for name in ("demo-skill", "demo-agent", "demo"):
            self.assertNotIn(name, dumped)


if __name__ == "__main__":
    unittest.main()
