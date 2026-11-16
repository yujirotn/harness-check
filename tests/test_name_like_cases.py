"""受付と同じ決まりの検査が、共通の見本に同じ答えを返すこと（日本語のパス・全角・拡張子・正当な文）。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inventory  # noqa: E402
import reasons  # noqa: E402
from namelike import scan_name_like  # noqa: E402

CASES = json.loads((Path(__file__).resolve().parent / "fixtures" / "name_like_cases.json").read_text(encoding="utf-8"))


class SharedCasesTest(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual((len(CASES["block"]), len(CASES["ok"])), (30, 30))

    def test_block_cases_are_stopped_by_all_three(self):
        for s in CASES["block"]:
            with self.subTest(s=s):
                self.assertNotEqual(scan_name_like(s), {}, "namelike")
                self.assertNotEqual(reasons.find_forbidden(s), [], "reasons")
                self.assertNotEqual(inventory.check_summary(s, set()), [], "inventory")

    def test_ok_cases_pass_all_three(self):
        for s in CASES["ok"]:
            with self.subTest(s=s):
                self.assertEqual(scan_name_like(s), {}, "namelike")
        # reasons は道具の呼び名以外の英字も止める。inventory は「Git」を通さない（説明には要らない）
        for s in CASES["ok"]:
            with self.subTest(s=s):
                if "Git" not in s:
                    self.assertEqual(inventory.check_summary(s, set()), [], "inventory")
                self.assertEqual(reasons.find_forbidden(s), [], "reasons")

    def test_full_width_slash_and_tool_file_names(self):
        self.assertEqual(scan_name_like("仕事／見積"), {"file_path_like": 1})
        self.assertEqual(scan_name_like("CLAUDE.md と 指示書AGENTS.md"), {})


if __name__ == "__main__":
    unittest.main()
