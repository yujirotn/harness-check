"""テスト共通のヘルパー。見本フォルダのコピー・簡易Gitリポジトリ化など。"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

TEST_NOW = "2026-11-11T12:00:00+00:00"


def copy_fixture(name: str, dest: Path) -> Path:
    src = FIXTURES_DIR / name
    shutil.copytree(src, dest)
    return dest


def make_git_repo(path: Path, with_remote: bool = True, track_all: bool = True) -> None:
    """path を Git リポジトリ化する（ローカルのみ・通信なし）。"""
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_AUTHOR_NAME"] = "test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"

    def run(*args):
        subprocess.run(["git", *args], cwd=str(path), env=env, check=True, capture_output=True)

    run("init", "-q")
    if with_remote:
        run("remote", "add", "origin", "https://example.invalid/not-a-real-remote.git")
    if track_all:
        run("add", "-A")
        run("commit", "-q", "-m", "initial")
