"""完成の条件4: 同じ入力で2回実行して result.json が一致する。"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import TEST_NOW, copy_fixture, make_git_repo  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_pipeline(tmp_path: Path, out_name: str) -> str:
    workdir = copy_fixture("repo_pass", tmp_path / f"workdir_{out_name}")
    make_git_repo(workdir, with_remote=True, track_all=True)
    claude_home = copy_fixture("claude_home_pass", tmp_path / f"claude_home_{out_name}")
    codex_home = copy_fixture("codex_home_pass", tmp_path / f"codex_home_{out_name}")
    home = copy_fixture("home_pass", tmp_path / f"home_{out_name}")
    out_dir = tmp_path / out_name

    import os
    import datetime

    now_ts = datetime.datetime.fromisoformat(TEST_NOW).timestamp()
    recent_file = claude_home / "scheduled-tasks" / "daily-job" / "log.txt"
    os.utime(recent_file, (now_ts, now_ts))
    recent_file2 = codex_home / "automations" / "daily" / "log.txt"
    os.utime(recent_file2, (now_ts, now_ts))

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
    return (out_dir / "result.json").read_text(encoding="utf-8")


class DeterminismTest(unittest.TestCase):
    def test_same_input_produces_identical_result_json(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            result_1 = run_pipeline(tmp_path, "run1")
            result_2 = run_pipeline(tmp_path, "run2")
            self.assertEqual(result_1, result_2)


if __name__ == "__main__":
    unittest.main()
