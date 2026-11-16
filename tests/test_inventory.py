"""説明の一覧（inventory）の検査と組み立ての単体テスト。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inventory  # noqa: E402

NAMES = ["monthly-report", "顧客-山田商事_月次報告", "acme-crm-sync", "株式会社ネコ", "pdf", "ai", "日報"]


class CheckSummaryTest(unittest.TestCase):
    def setUp(self):
        self.needles = inventory.name_needles(NAMES)

    def test_clean_summaries_pass(self):
        for s in [
            "月ごとの実績を表にまとめ、グラフと要点を付ける",
            "書いた文章を、読み手の立場で見直して指摘する",
            "チャットの道具とつないで、メッセージを読み書きする",
            "取引先からの問い合わせメールに返事の下書きを作る",
            "住宅の図面からPDFの資料を作る",
            "AIで日報の下書きを作る",
            "住宅の図面から3Dの内覧を作る",
        ]:
            with self.subTest(s=s):
                self.assertEqual(inventory.check_summary(s, self.needles), [])

    def test_names_and_shapes_are_caught(self):
        for s in [
            "monthly-report を動かす",
            "Monthly Report を作る",
            "ＭＯＮＴＨＬＹ　ＲＥＰＯＲＴの集計",
            "山田商事向けの月次報告を作る",
            "株式会社ネコの見積もりを作る",
            "ネコ株式会社 の見積もり",  # 部分（株式会社ネコ）ではないが ascii も無い → 下で別に確かめる
            "acmecrmsync とつなぐ",
            "Slackとつなぐ",
            "設定は config.toml にある",
            "場所は ~/.claude/skills",
            "https://example.com を開く",
            "taro@example.com に送る",
            "snake_case_name を使う",
            "CamelCaseName を使う",
            "あ" * 81,
            "改行\nあり",
            "",
            None,
            "電話は 09012345678",
        ]:
            with self.subTest(s=s):
                found = inventory.check_summary(s, self.needles)
                if s == "ネコ株式会社 の見積もり":
                    # 語順を入れ替えた日本語の社名は機械では見つけきれない（下見で本人が確かめる）
                    continue
                self.assertNotEqual(found, [], s)

    def test_short_names_are_not_used_as_needles(self):
        self.assertNotIn("ai", self.needles)
        self.assertNotIn("pdf", self.needles)
        self.assertNotIn("日報", self.needles)
        self.assertIn("monthlyreport", self.needles)
        self.assertIn("山田商事", self.needles)
        self.assertIn("株式会社ネコ", self.needles)


class BuildInventoryTest(unittest.TestCase):
    def skeleton(self):
        return {
            "skills": [{"id": "K1", "used_30d": 4}, {"id": "K2", "used_30d": 0}, {"id": "K3", "used_30d": None}],
            "agents": [{"id": "A1", "used_30d": 2}],
            "connectors": [{"id": "C1", "used_30d": 12}],
        }

    def test_good_and_bad_summaries(self):
        ai = {
            "skills": {
                "K1": {"summary": "月ごとの実績を表にまとめる", "category": "集計"},
                "K2": {"summary": "monthly-report の手順", "category": "資料"},
                "K3": {"summary": "見積もりを作る", "category": "でたらめ"},
            },
            "agents": {"A1": {"summary": "株式会社ネコ向けに文章を直す"}},
        }
        inv, cut, replaced = inventory.build_inventory(self.skeleton(), ai, inventory.name_needles(NAMES))
        self.assertEqual(inv["skills"][0], {"summary": "月ごとの実績を表にまとめる", "category": "集計", "used_30d": 4})
        self.assertEqual(inv["skills"][1], {"summary": inventory.FALLBACK_SUMMARY, "category": "その他", "used_30d": 0})
        self.assertEqual(inv["skills"][2], {"summary": "見積もりを作る", "category": "その他", "used_30d": None})
        self.assertEqual(inv["agents"], [{"summary": inventory.FALLBACK_SUMMARY, "used_30d": 2}])
        # AIが書いていない（コネクタ）も置き換え
        self.assertEqual(inv["connectors"], [{"summary": inventory.FALLBACK_SUMMARY, "used_30d": 12}])
        self.assertEqual(replaced, {"skills": 1, "agents": 1, "connectors": 1})
        self.assertEqual(cut, {"skills": 0, "agents": 0, "connectors": 0})

    def test_without_name_list_everything_is_replaced(self):
        ai = {"skills": {"K1": {"summary": "表にまとめる", "category": "集計"}}}
        inv, _, replaced = inventory.build_inventory(self.skeleton(), ai, None)
        self.assertTrue(all(r["summary"] == inventory.FALLBACK_SUMMARY for r in inv["skills"]))
        self.assertEqual(replaced["skills"], 3)

    def test_truncates_to_300(self):
        sk = {"skills": [{"id": f"K{i}", "used_30d": i % 5} for i in range(320)], "agents": [], "connectors": []}
        inv, cut, _ = inventory.build_inventory(sk, {}, set())
        self.assertEqual(len(inv["skills"]), 300)
        self.assertEqual(cut["skills"], 20)
        used = [r["used_30d"] for r in inv["skills"]]
        self.assertEqual(used, sorted(used, reverse=True))

    def test_missing_skeleton_gives_empty_lists(self):
        inv, cut, replaced = inventory.build_inventory(None, None, set())
        self.assertEqual(inv, {"skills": [], "agents": [], "connectors": []})


if __name__ == "__main__":
    unittest.main()
