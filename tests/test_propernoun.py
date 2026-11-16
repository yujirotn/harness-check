"""説明の1文の社名・人名の印。止めたい見本でどれだけ止まり、正当な見本でどれだけ誤って止まるか。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inventory  # noqa: E402
from propernoun import find_marks  # noqa: E402

CASES = json.loads((Path(__file__).resolve().parent / "fixtures" / "proper_noun_cases.json").read_text(encoding="utf-8"))


def stopped(s: str) -> bool:
    return bool(inventory.check_summary(s, set()))


class ProperNounMarksTest(unittest.TestCase):
    def test_company_and_person_with_marks_are_all_stopped(self):
        for cat in ("company", "person", "client"):
            for s in CASES["adversarial"][cat]:
                with self.subTest(cat=cat, s=s):
                    self.assertTrue(stopped(s))

    def test_total_stopped_count_is_recorded(self):
        n = sum(stopped(s) for xs in CASES["adversarial"].values() for s in xs)
        self.assertEqual(sum(len(xs) for xs in CASES["adversarial"].values()), 40)
        self.assertGreaterEqual(n, 25)

    def test_legit_false_positive_rate_at_most_3_percent(self):
        self.assertEqual(len(CASES["legit"]), 100)
        fp = [s for s in CASES["legit"] if stopped(s)]
        self.assertLessEqual(len(fp), 3, fp)

    def test_general_phrases_pass(self):
        for s in ["お客様への案内", "担当者様あて", "皆様へ", "社長向けの資料", "ホームページの更新", "ハウスメーカーの比較",
                  "建設業の動向", "不動産会社への提案", "地域の工務店", "マイホームの記事", "モデルハウスの集客", "設計事務所との調整",
                  "代表取締役社長への報告", "経理部長への資料", "副社長の承認", "家の仕様", "同様の手順", "顧客の氏名を入力する"]:
            with self.subTest(s=s):
                self.assertEqual(find_marks(s), [])

    def test_marks(self):
        for s in ["田中さんの週報", "鈴木様あて", "株式会社ネコ", "(株)ネコ", "㈱ネコ", "ネコ御中", "山田工務店", "ツバメホームの資料",
                  "東西不動産の物件", "アオイ商事", "高橋部長", "ヤマダくん", "加藤氏"]:
            with self.subTest(s=s):
                self.assertNotEqual(find_marks(s), [])

    def test_unmarked_proper_nouns_are_a_known_limit(self):
        # 印の無い固有名詞は機械では止まらない（送る前の一覧で本人が確かめる）
        for s in ["田中の週報をまとめる", "ソラマドの施工手順を整理する", "港北展示場の来場者を集計する"]:
            with self.subTest(s=s):
                self.assertEqual(find_marks(s), [])


if __name__ == "__main__":
    unittest.main()
