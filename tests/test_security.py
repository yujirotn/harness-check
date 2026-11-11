"""完成の条件2・条件3の確認。

条件2: 見本フォルダの秘密の値・フォルダ名・本文が facts.json / result.json / HTML に出ない。
条件3: 出力フォルダの外に書き込まない。通信の機能を import していない。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import TEST_NOW, copy_fixture, make_git_repo  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_STRINGS = [
    "sk-FAKEJAPANESEFOLDERKEY7890ABCDEF",  # 見本に仕込んだ偽のキー（日本語名フォルダの中）
    "DEMO_API_TOKEN",  # 見本に仕込んだ、名前でわかる秘密のキー名
    "極秘クライアントXプロジェクト",  # 見本に仕込んだフォルダ名
    "これは外部に漏らしてはいけない社内会議の内容です",  # 見本に仕込んだ本文
    "極秘クライアントXの契約金額",
    "demo-skill",  # 見本に仕込んだ自作スキル名（既定では名前を出さない）
    "demo-agent",  # 見本に仕込んだ自作エージェント名
]

NETWORK_MODULE_PATTERN = re.compile(
    r"^\s*import\s+(socket|urllib\.request|http\.client|requests|ftplib|smtplib|telnetlib)\b"
    r"|^\s*from\s+(socket|urllib\.request|http\.client|requests|ftplib|smtplib|telnetlib)\b",
    re.MULTILINE,
)

SCRIPT_FILES = ["collect.py", "score.py", "render.py"]
READER_FILES = ["readers/common.py", "readers/claude_code.py", "readers/codex.py"]


def snapshot(path: Path) -> dict:
    out = {}
    for f in sorted(path.rglob("*")):
        if f.is_file():
            try:
                h = hashlib.sha256(f.read_bytes()).hexdigest()
            except OSError:
                h = None
            out[str(f.relative_to(path))] = (h, f.stat().st_mtime_ns)
    return out


class NoNetworkImportTest(unittest.TestCase):
    def test_no_networking_modules_imported(self):
        for rel in SCRIPT_FILES + READER_FILES:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            self.assertIsNone(
                NETWORK_MODULE_PATTERN.search(text),
                msg=f"{rel} が通信の機能を import している",
            )


class NoWriteOutsideOutputTest(unittest.TestCase):
    def test_full_pipeline_only_writes_inside_out_dir(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            workdir = copy_fixture("repo_pass", tmp_path / "workdir")
            make_git_repo(workdir, with_remote=True, track_all=True)
            claude_home = copy_fixture("claude_home_pass", tmp_path / "claude_home")
            codex_home = copy_fixture("codex_home_pass", tmp_path / "codex_home")
            home = copy_fixture("home_pass", tmp_path / "home")
            out_dir = tmp_path / "out"

            before = {
                "workdir": snapshot(workdir),
                "claude_home": snapshot(claude_home),
                "codex_home": snapshot(codex_home),
                "home": snapshot(home),
            }

            subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "collect.py"),
                    "--workdir", str(workdir), "--out", str(out_dir),
                    "--claude-home", str(claude_home), "--codex-home", str(codex_home),
                    "--home", str(home), "--now", TEST_NOW,
                ],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "score.py"), "--out", str(out_dir)],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "render.py"), "--out", str(out_dir), "--no-pdf"],
                check=True, capture_output=True, text=True,
            )

            after = {
                "workdir": snapshot(workdir),
                "claude_home": snapshot(claude_home),
                "codex_home": snapshot(codex_home),
                "home": snapshot(home),
            }

            self.assertEqual(before, after, "出力フォルダの外が変更されている")
            self.assertTrue((out_dir / "facts.json").exists())
            self.assertTrue((out_dir / "result.json").exists())
            self.assertTrue((out_dir / "report.html").exists())

    def test_pdf_path_only_writes_inside_out_dir_and_cleans_up_chrome_profile(self):
        """条件3: PDFを書き出す経路も含めて確かめる（Chromeが無ければ飛ばす）。"""
        import sys as _sys

        sys.path.insert(0, str(REPO_ROOT))
        from readers import common as _common

        if _common._find_chrome() is None:
            self.skipTest("Chrome が見つからない環境なので飛ばす")

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            workdir = copy_fixture("repo_pass", tmp_path / "workdir")
            make_git_repo(workdir, with_remote=True, track_all=True)
            claude_home = copy_fixture("claude_home_pass", tmp_path / "claude_home")
            codex_home = copy_fixture("codex_home_pass", tmp_path / "codex_home")
            home = copy_fixture("home_pass", tmp_path / "home")
            out_dir = tmp_path / "out"

            before = {
                "workdir": snapshot(workdir),
                "claude_home": snapshot(claude_home),
                "codex_home": snapshot(codex_home),
                "home": snapshot(home),
            }

            subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "collect.py"),
                    "--workdir", str(workdir), "--out", str(out_dir),
                    "--claude-home", str(claude_home), "--codex-home", str(codex_home),
                    "--home", str(home), "--now", TEST_NOW,
                ],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "score.py"), "--out", str(out_dir)],
                check=True, capture_output=True, text=True,
            )
            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "render.py"), "--out", str(out_dir)],
                capture_output=True, text=True,
            )

            after = {
                "workdir": snapshot(workdir),
                "claude_home": snapshot(claude_home),
                "codex_home": snapshot(codex_home),
                "home": snapshot(home),
            }
            self.assertEqual(before, after, "出力フォルダの外が変更されている（PDF経路）")
            self.assertTrue((out_dir / "report.pdf").exists(), proc.stdout + proc.stderr)
            leftover = [p for p in out_dir.iterdir() if p.name.startswith("chrome-profile-")]
            self.assertEqual(leftover, [], "Chrome の専用設定フォルダが消されずに残っている")


class NoLeakTest(unittest.TestCase):
    """見本（不合格側・秘密/フォルダ名/本文入り）で各出力に漏れが無いことを確かめる。"""

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
        cls.out_dir = tmp_path / "out"

        subprocess.run(
            [
                sys.executable, str(REPO_ROOT / "collect.py"),
                "--workdir", str(cls.workdir), "--out", str(cls.out_dir),
                "--claude-home", str(cls.claude_home), "--codex-home", str(cls.codex_home),
                "--home", str(cls.home), "--now", TEST_NOW,
            ],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "score.py"), "--out", str(cls.out_dir)],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "render.py"), "--out", str(cls.out_dir), "--no-pdf"],
            check=True, capture_output=True, text=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def test_facts_json_has_no_forbidden_strings(self):
        text = (self.out_dir / "facts.json").read_text(encoding="utf-8")
        for s in FORBIDDEN_STRINGS:
            self.assertNotIn(s, text, f"facts.json に漏れ: {s[:10]}...")

    def test_result_json_has_no_forbidden_strings(self):
        text = (self.out_dir / "result.json").read_text(encoding="utf-8")
        for s in FORBIDDEN_STRINGS:
            self.assertNotIn(s, text, f"result.json に漏れ: {s[:10]}...")

    def test_report_html_has_no_forbidden_strings(self):
        text = (self.out_dir / "report.html").read_text(encoding="utf-8")
        for s in FORBIDDEN_STRINGS:
            self.assertNotIn(s, text, f"report.html に漏れ: {s[:10]}...")

    def test_s1_counts_are_counts_only_not_values(self):
        facts = json.loads((self.out_dir / "facts.json").read_text(encoding="utf-8"))
        s1 = facts["items"]["S1"]["combined"]
        self.assertIn("repo", s1)
        self.assertIn("config", s1)
        for section in ("repo", "config"):
            for v in s1[section]["counts_by_kind"].values():
                self.assertIsInstance(v, int)
        # 値そのもの（偽のキー文字列）はどこにも出ていないことを再確認
        dumped = json.dumps(s1, ensure_ascii=False)
        self.assertNotIn("sk-FAKEJAPANESEFOLDERKEY", dumped)
        self.assertNotIn("69ebc2c640a5bf43d254ff004ff8a274", dumped)

    def test_s1_finds_secret_in_japanese_named_folder(self):
        """CRITICAL finding #1 の再現テスト: git ls-files -z でないと日本語名を飛ばす。"""
        facts = json.loads((self.out_dir / "facts.json").read_text(encoding="utf-8"))
        s1 = facts["items"]["S1"]["combined"]
        self.assertGreaterEqual(sum(s1["repo"]["counts_by_kind"].values()), 1)

    def test_s1_repo_scan_did_not_skip_most_files(self):
        """git ls-files のクォート済みパスを実在しないファイルとして黙って飛ばしていないか。"""
        facts = json.loads((self.out_dir / "facts.json").read_text(encoding="utf-8"))
        s1 = facts["items"]["S1"]["combined"]
        # 見本リポジトリの全追跡ファイル数に対して、走査できた数が大きく下回っていないこと
        self.assertGreater(s1["repo"]["scanned_file_count"], 0)
        self.assertEqual(s1["repo"]["skipped_file_count"], 0)

    def test_s1_config_named_secret_detected(self):
        """設定ファイルの中の、名前でわかる秘密（token等）を見つける。見本の値は数えない。"""
        facts = json.loads((self.out_dir / "facts.json").read_text(encoding="utf-8"))
        s1 = facts["items"]["S1"]["combined"]
        self.assertGreaterEqual(s1["config"]["counts_by_kind"].get("named_secret", 0), 1)

    def test_s1_placeholder_values_not_counted(self):
        """見本の値（xxxx・example等）は数えない。"""
        facts = json.loads((self.out_dir / "facts.json").read_text(encoding="utf-8"))
        s1 = facts["items"]["S1"]["combined"]
        # leaky.txt の sk-xxxx.../AIza...Example... は除外され、repo側に openai/google種別の
        # 誤検出が無いこと（日本語フォルダ側の openai_or_anthropic 以外は増えない）
        self.assertNotIn("google_aiza", s1["repo"]["counts_by_kind"])


class NameSuppressionTest(unittest.TestCase):
    """HIGH finding #2・#4: 既定では名前を出さない。--show-names の時だけ出す。"""

    NAMES = ["demo-skill", "demo-agent", "demo-agent-2", "demo-connector", "carmack-engineering"]

    @classmethod
    def setUpClass(cls):
        import tempfile

        cls._tmpdir = tempfile.TemporaryDirectory()
        tmp_path = Path(cls._tmpdir.name)
        cls.workdir = copy_fixture("repo_pass", tmp_path / "workdir")
        make_git_repo(cls.workdir, with_remote=True, track_all=True)
        cls.claude_home = copy_fixture("claude_home_pass", tmp_path / "claude_home")
        cls.codex_home = copy_fixture("codex_home_pass", tmp_path / "codex_home")
        cls.home = copy_fixture("home_pass", tmp_path / "home")

        import datetime
        import os as _os

        now_ts = datetime.datetime.fromisoformat(TEST_NOW).timestamp()
        _os.utime(cls.claude_home / "scheduled-tasks" / "daily-job" / "log.txt", (now_ts, now_ts))
        _os.utime(cls.codex_home / "automations" / "daily" / "log.txt", (now_ts, now_ts))

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def _run(self, out_dir: Path, show_names: bool):
        cmd = [
            sys.executable, str(REPO_ROOT / "collect.py"),
            "--workdir", str(self.workdir), "--out", str(out_dir),
            "--claude-home", str(self.claude_home), "--codex-home", str(self.codex_home),
            "--home", str(self.home), "--now", TEST_NOW,
        ]
        if show_names:
            cmd.append("--show-names")
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "score.py"), "--out", str(out_dir)],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "render.py"), "--out", str(out_dir), "--no-pdf"],
            check=True, capture_output=True, text=True,
        )

    def test_names_absent_by_default(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "out"
            self._run(out_dir, show_names=False)
            for fname in ("facts.json", "result.json", "report.html"):
                text = (out_dir / fname).read_text(encoding="utf-8")
                for name in self.NAMES:
                    self.assertNotIn(name, text, f"{fname} に名前 {name} が既定で出ている")

    def test_names_present_with_show_names_flag(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "out"
            self._run(out_dir, show_names=True)
            html = (out_dir / "report.html").read_text(encoding="utf-8")
            self.assertIn("demo-skill", html)
            self.assertIn("固有名を含みます", html)


class ExternalProgramGuardTest(unittest.TestCase):
    """HIGH finding #3・4回目レビュー（シュナイアー）: 起動する命令の形は3つに固定。

    任意の引数の並びを受け取る汎用の入口（旧 run_external）は無い。
    readers/common.py が公開するのは、固定の命令1本ずつの専用関数だけ。
    """

    SUBPROCESS_CALL_PATTERN = re.compile(r"subprocess\.(run|Popen|call|check_output|check_call)\s*\(")

    def test_subprocess_called_only_from_common_chokepoint(self):
        chokepoint_file = REPO_ROOT / "readers" / "common.py"
        other_files = [
            REPO_ROOT / "collect.py",
            REPO_ROOT / "score.py",
            REPO_ROOT / "render.py",
            REPO_ROOT / "readers" / "claude_code.py",
            REPO_ROOT / "readers" / "codex.py",
        ]
        for f in other_files:
            text = f.read_text(encoding="utf-8")
            self.assertIsNone(
                self.SUBPROCESS_CALL_PATTERN.search(text),
                msg=f"{f.name} が readers/common.py の関所を通さずに subprocess を直接呼んでいる",
            )
        chokepoint_text = chokepoint_file.read_text(encoding="utf-8")
        # 唯一の呼び出し箇所（_run_subprocess 内）だけが subprocess.run を呼ぶこと
        self.assertEqual(len(self.SUBPROCESS_CALL_PATTERN.findall(chokepoint_text)), 1)

    def test_no_generic_argv_entrypoint_is_exposed(self):
        """任意の引数の並びを受け取る汎用の入口（run_external・run_git）を外に見せていない。"""
        sys.path.insert(0, str(REPO_ROOT))
        from readers import common

        self.assertFalse(hasattr(common, "run_external"))
        self.assertFalse(hasattr(common, "run_git"))
        self.assertFalse(hasattr(common, "GIT_ALLOWED_SUBCOMMANDS"))

    def test_render_pdf_signature_does_not_accept_a_program_location(self):
        """Chrome の実行ファイルの場所を、呼び出す側から渡せないことを型で確認する。"""
        sys.path.insert(0, str(REPO_ROOT))
        from readers import common
        import inspect

        params = set(inspect.signature(common.render_pdf_with_chrome).parameters)
        self.assertEqual(params, {"html_path", "pdf_path", "out_dir", "timeout"})

    def test_git_ls_files_z_still_works_with_japanese_names(self):
        sys.path.insert(0, str(REPO_ROOT))
        from readers import common

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            workdir = copy_fixture("repo_fail", tmp_path / "workdir")
            make_git_repo(workdir, with_remote=False, track_all=True)
            tracked = common.git_ls_files_z(workdir)
            self.assertTrue(any("極秘クライアントXプロジェクト" in p for p in tracked))

    def test_git_has_remote_true_and_false(self):
        sys.path.insert(0, str(REPO_ROOT))
        from readers import common

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            with_remote = copy_fixture("repo_pass", tmp_path / "with_remote")
            make_git_repo(with_remote, with_remote=True, track_all=True)
            self.assertTrue(common.git_has_remote(with_remote))

            without_remote = copy_fixture("repo_pass", tmp_path / "without_remote")
            make_git_repo(without_remote, with_remote=False, track_all=True)
            self.assertFalse(common.git_has_remote(without_remote))

    def test_chokepoint_enforces_safe_env_and_prefix_for_both_git_commands(self):
        """呼び出し側が何も渡さなくても、入口が必ず安全な設定を付ける（両方の固定命令で確認）。"""
        sys.path.insert(0, str(REPO_ROOT))
        from readers import common
        import unittest.mock as mock

        captured = []
        real_run = common.subprocess.run

        def spy(argv, **kwargs):
            captured.append((list(argv), dict(kwargs.get("env") or {})))
            return real_run(argv, **kwargs)

        with mock.patch.object(common.subprocess, "run", side_effect=spy):
            common.git_ls_files_z(REPO_ROOT)
            common.git_has_remote(REPO_ROOT)

        self.assertEqual(len(captured), 2)
        for argv, env in captured:
            self.assertIn("-c", argv)
            self.assertIn("core.fsmonitor=false", argv)
            self.assertIn("core.hooksPath=/dev/null", argv)
            self.assertEqual(env.get("GIT_CONFIG_NOSYSTEM"), "1")

    def test_remote_update_config_list_config_file_error_unmatch_not_reachable(self):
        """シュナイアー実測の抜け道（後ろの引数が素通し）が、固定命令化で届かないことの確認。

        `git_ls_files_z`・`git_has_remote` はどちらも固定の argv しか組み立てないため、
        `remote update`・`config --list`・`config -f <file>`・`ls-files --error-unmatch x`
        を実際に起動する経路自体が存在しない。実際に subprocess へ渡る argv を記録して確認する。
        """
        sys.path.insert(0, str(REPO_ROOT))
        from readers import common
        import unittest.mock as mock

        captured = []
        real_run = common.subprocess.run

        def spy(argv, **kwargs):
            captured.append(list(argv))
            return real_run(argv, **kwargs)

        with mock.patch.object(common.subprocess, "run", side_effect=spy):
            common.git_ls_files_z(REPO_ROOT)
            common.git_has_remote(REPO_ROOT)

        forbidden_tokens = {"update", "--list", "-f", "--error-unmatch", "rev-parse", "config"}
        for argv in captured:
            self.assertTrue(set(argv).isdisjoint(forbidden_tokens), f"許可されない引数が混入: {argv}")

    def test_chrome_rejects_html_pdf_outside_out_dir(self):
        """Chrome に出力フォルダの外のHTML・PDFを渡すと起動しない（subprocess が呼ばれない）。"""
        sys.path.insert(0, str(REPO_ROOT))
        from readers import common
        import unittest.mock as mock
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "out"
            out_dir.mkdir()
            outside_dir = Path(td) / "outside"
            outside_dir.mkdir()

            cases = [
                (outside_dir / "report.html", out_dir / "report.pdf"),
                (out_dir / "report.html", outside_dir / "report.pdf"),
                (Path("http://example.invalid/report.html"), out_dir / "report.pdf"),
            ]
            for html_path, pdf_path in cases:
                with mock.patch.object(common.subprocess, "run") as spy:
                    ok = common.render_pdf_with_chrome(html_path, pdf_path, out_dir)
                    self.assertFalse(ok, f"{html_path} / {pdf_path} で起動を拒否しなかった")
                    spy.assert_not_called()

    def test_chrome_allows_html_pdf_inside_out_dir_when_chrome_present(self):
        sys.path.insert(0, str(REPO_ROOT))
        from readers import common
        import tempfile

        if common._find_chrome() is None:
            self.skipTest("Chrome が見つからない環境なので飛ばす")

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            html_path = out_dir / "report.html"
            html_path.write_text("<!doctype html><title>t</title><body>hi</body>", encoding="utf-8")
            pdf_path = out_dir / "report.pdf"
            ok = common.render_pdf_with_chrome(html_path, pdf_path, out_dir)
            self.assertTrue(ok)
            self.assertTrue(pdf_path.exists())
            leftover = [p for p in out_dir.iterdir() if p.name.startswith("chrome-profile-")]
            self.assertEqual(leftover, [])

    def test_find_chrome_does_not_match_by_substring(self):
        """finding #1（4回目レビュー・シュナイアー実測）: `chrome`を含む別プログラムを選ばない。

        決まった場所の一覧を空にした状態（PATH頼みの経路）で、`my-chrome`のような
        部分一致の名前は選ばれず、完全に一致する名前（`google-chrome`等）だけが選ばれることを確認する。
        """
        sys.path.insert(0, str(REPO_ROOT))
        from readers import common
        import unittest.mock as mock
        import tempfile
        import stat

        with tempfile.TemporaryDirectory() as td:
            fake_dir = Path(td)
            fake_substring_match = fake_dir / "my-chrome-evil"
            fake_exact_match = fake_dir / "google-chrome"
            for p in (fake_substring_match, fake_exact_match):
                p.write_text("#!/bin/sh\necho fake\n", encoding="utf-8")
                p.chmod(p.stat().st_mode | stat.S_IEXEC)

            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{fake_dir}{os.pathsep}{old_path}"
            try:
                with mock.patch.object(common, "_CHROME_EXACT_PATHS", []):
                    found = common._find_chrome()
            finally:
                os.environ["PATH"] = old_path

            self.assertEqual(found, str(fake_exact_match))
            self.assertNotEqual(found, str(fake_substring_match))

    def test_no_shell_true_anywhere(self):
        for f in [REPO_ROOT / "readers" / "common.py", REPO_ROOT / "collect.py", REPO_ROOT / "render.py"]:
            text = f.read_text(encoding="utf-8")
            self.assertNotIn("shell=True", text)


if __name__ == "__main__":
    unittest.main()
