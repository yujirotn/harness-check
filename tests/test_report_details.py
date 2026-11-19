"""ローカルレポートの一覧と木が、件数・定型文だけで構成されることを確認する。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import report_details
import render

ROOT = Path(__file__).resolve().parent.parent


class ReportDetailsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.work = self.root / "非公開調査先"
        self.work.mkdir()
        self.home = self.root / "個人名の設定"
        self.claude = self.home / ".claude"
        self.codex = self.home / ".codex"
        self.out = self.work / "外に出さない出力先"

    def write(self, path: Path, text: str = "") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def collect(self):
        return report_details.collect_report_details(
            self.work, self.claude, self.codex, self.home, self.out,
            {"claude_code": True, "codex": True},
        )

    def test_catalog_groups_yaml_toml_cache_and_shared_links(self):
        shared = self.write(
            self.home / ".agents/skills/秘密の分析名/SKILL.md",
            "---\ndescription: >-\n  顧客の表計算を集計する\n---\n本文の秘密",
        )
        claude_skills = self.claude / "skills"
        claude_skills.mkdir(parents=True)
        (claude_skills / "共有の別名").symlink_to(shared.parent, target_is_directory=True)
        outside = self.write(self.root / "outside/SKILL.md", "---\ndescription: メール\n---")
        (claude_skills / "外部").symlink_to(outside.parent, target_is_directory=True)
        self.write(self.work / ".claude/agents/非公開.md", "---\ndescription: レビュー\n---")
        self.write(self.codex / "agents/個人.toml", 'description = "資料を準備する"\n')
        self.write(
            self.codex / "plugins/cache/非公開/配布元/1/skills/見本/SKILL.md",
            "---\nname: メール\n---\n本文の検索",
        )
        self.write(self.codex / "plugins/cache/非公開/配布元/1/agents/見本.md",
                   "---\ndescription: 画像\n---")

        data = self.collect()
        groups = {(g["tool"], g["scope"]): g for g in data["inventory"]}
        self.assertEqual(groups["claude_code", "personal"]["skills"], ["data"])
        self.assertEqual(groups["claude_code", "workspace"]["agents"], ["review"])
        self.assertEqual(groups["codex", "personal"]["skills"], ["data"])
        self.assertEqual(groups["codex", "personal"]["agents"], ["document"])
        self.assertEqual(groups["codex", "plugins"]["skills"], ["unknown"])
        self.assertEqual(groups["codex", "plugins"]["agents"], ["visual"])
        output = render.render_catalog(data) + json.dumps(data, ensure_ascii=False)
        for secret in ("秘密の分析名", "顧客の表計算", "本文の秘密", "非公開", "配布元", "共有の別名"):
            self.assertNotIn(secret, output)

    def test_tree_is_bounded_and_counts_only_direct_regular_entries(self):
        self.write(self.work / "深い1/深い2/深い3/深い4/取引先名.md")
        self.write(self.work / ".env", "読んではいけない内容")
        self.write(self.work / ".git/HEAD")
        self.write(self.out / "report.html")
        for i in range(report_details.TREE_FILE_LIMIT):
            self.write(self.work / "件数が多い枝" / f"会議録{i}.txt")
        self.write(self.work / "件数が多い枝/深い1/ファイル")
        (self.work / "外へのリンク").symlink_to(self.out, target_is_directory=True)
        with patch.object(Path, "open", side_effect=AssertionError("構成の取得でファイルを開いた")):
            data = self.collect()
        tree = data["trees"]["workspace"]
        self.assertEqual((tree["directories"], tree["files"]), (2, 1))
        crowded, nested = tree["children"]
        self.assertEqual(crowded["files"], report_details.TREE_FILE_LIMIT)
        self.assertEqual(crowded["children"], [])
        deepest = nested["children"][0]["children"][0]
        self.assertEqual(deepest, {"files": 0, "directories": 1, "children": []})
        output = render.render_folder_tree(data)
        self.assertIn("最大3階層", output)
        self.assertIn("内訳省略", output)
        for secret in (".env", "読んではいけない内容", "深い", "取引先名", "件数が多い枝", str(self.work)):
            self.assertNotIn(secret, output)

    def test_catalog_repeats_headings_and_keeps_numbering_across_pages(self):
        details = {"inventory": [{
            "tool": "codex", "scope": "plugins", "skills": ["document"] * 26, "agents": ["review"],
        }]}
        first, second = render.render_catalog(details).strip().split("</section>", 1)
        self.assertIn("<thead>", first)
        self.assertIn("<thead>", second)
        self.assertIn("スキル 25</th>", first)
        self.assertIn("スキル 26</th>", second)
        self.assertIn("エージェント 1</th>", second)
        self.assertNotIn("スキル 26</th>", first)

    def test_only_local_render_reads_details_and_old_results_still_render(self):
        self.write(self.claude / "settings.json", "{}")
        self.write(self.claude / "skills/個人名の取得/SKILL.md", "---\ndescription: 調査\n---")
        self.write(self.work / "顧客案件の資料/会議録.txt")
        for entry, args in (
            ("collect.py", [
                "--workdir", str(self.work), "--home", str(self.home),
                "--claude-home", str(self.claude), "--codex-home", str(self.codex),
            ]),
            ("score.py", []),
            ("render.py", ["--no-pdf"]),
        ):
            subprocess.run([sys.executable, str(ROOT / entry), "--out", str(self.out), *args],
                           check=True, capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        result = json.loads((self.out / "result.json").read_text(encoding="utf-8"))
        self.assertNotIn("report_details", result)
        self.assertEqual(result["tool_counts"]["claude_code"]["skills"], 1)
        html = (self.out / "report.html").read_text(encoding="utf-8")
        self.assertIn("スキル・エージェント一覧", html)
        self.assertIn("情報を探して整理する", html)
        self.assertIn("フォルダの構成", html)
        for path in ("facts.json", "result.json", "report.html"):
            text = (self.out / path).read_text(encoding="utf-8")
            for secret in ("個人名の取得", "顧客案件の資料", "会議録.txt", str(self.home)):
                self.assertNotIn(secret, text)
        facts = self.out / "facts.json"
        for invalid in ("{", None):
            with self.subTest(invalid=invalid):
                if invalid is None:
                    facts.unlink()
                else:
                    self.write(facts, invalid)
                subprocess.run([sys.executable, str(ROOT / "render.py"), "--out", str(self.out), "--no-pdf"],
                               check=True, capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
                html = (self.out / "report.html").read_text(encoding="utf-8")
                self.assertNotIn("スキル・エージェント一覧", html)
                self.assertNotIn("フォルダの構成", html)
