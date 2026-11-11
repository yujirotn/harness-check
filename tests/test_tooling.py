"""finding #6: 仕様書に書いてあるテストコマンドが実際にテストを走らせることの確認。"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class DiscoveryCommandTest(unittest.TestCase):
    def test_documented_discover_command_actually_runs_tests(self):
        """README/AGENTS.md に書く `python3 -m unittest discover -s tests` が
        0件で成功と表示しないことを確かめる（元の `python3 -m unittest` は0件でOKだった）。
        再帰起動を避けるため、このファイル以外の軽量な1ファイルに絞って実行する。
        """
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_score.py"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        m = re.search(r"Ran (\d+) tests?", proc.stderr + proc.stdout)
        self.assertIsNotNone(m, f"テスト件数が出力に見つからない: {proc.stderr}")
        self.assertGreater(int(m.group(1)), 0)
        self.assertEqual(proc.returncode, 0)

    def test_bare_unittest_with_no_args_runs_zero_tests_documented_pitfall(self):
        """仕様書が避けろと言っている旧コマンドが、本当に0件で成功してしまうことの記録。"""
        proc = subprocess.run(
            [sys.executable, "-m", "unittest"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertIn("Ran 0 tests", proc.stderr + proc.stdout)

    def test_readme_and_agents_md_document_the_correct_command(self):
        """正しいコマンドが書かれていて、かつコードブロック内に旧コマンド単体が無いこと。"""
        bad_in_code_block = re.compile(r"```bash\n(?:(?!```).)*?python3 -m unittest(?! discover)", re.DOTALL)
        for fname in ("README.md", "AGENTS.md"):
            text = (REPO_ROOT / fname).read_text(encoding="utf-8")
            self.assertIn(
                "unittest discover -s tests",
                text,
                f"{fname} に正しいテストコマンドが書かれていない",
            )
            self.assertIsNone(
                bad_in_code_block.search(text),
                f"{fname} の実行コマンド例に、0件でも成功してしまう旧コマンドが残っている",
            )


if __name__ == "__main__":
    unittest.main()
