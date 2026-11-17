"""render.py の単体テスト。HTMLエスケープ・表示フォーマット・名前の既定非表示。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import render  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def minimal_result(**overrides) -> dict:
    base = {
        "schema_version": 2,
        "score": 50,
        "judged_item_count": 19,
        "total_item_count": 23,
        "type_name": "全体がほどほどの型",
        "pillar_order": ["foundation", "safety", "grow", "delegate"],
        "pillars": {
            "foundation": {"name": "土台", "judged_count": 5, "total_count": 11, "passed_count": 3, "rate": 0.6},
            "safety": {"name": "安全", "judged_count": 2, "total_count": 4, "passed_count": 1, "rate": 0.5},
            "grow": {"name": "育つ仕組み", "judged_count": 2, "total_count": 3, "passed_count": 2, "rate": 1.0},
            "delegate": {"name": "任せ方", "judged_count": 1, "total_count": 5, "passed_count": 0, "rate": 0.0},
        },
        "items": {
            "F1": {"name": "作業フォルダに指示書がある", "pillar": "foundation", "judge": "machine", "judge_label": "機械", "status": "pass"},
            "F10": {"name": "コネクタが1つ以上ある", "pillar": "foundation", "judge": "machine", "judge_label": "機械", "status": "pass"},
            "F11": {"name": "コネクタが、直近30日に1回以上使われた", "pillar": "foundation", "judge": "machine", "judge_label": "機械", "status": "pass"},
            "F2": {"name": "毎回読まれる指示ファイルが、どれも長すぎない", "pillar": "foundation", "judge": "machine", "judge_label": "機械", "status": "pass"},
        },
        "next_fixes": [],
        "reference": {
            "names_included": False,
            "skills": {"own_count": 2, "used_recent_count": 1, "usage_counts": [5, 1]},
            "agents": {"own_count": 1, "used_recent_count": 1, "usage_counts": [3]},
            "connectors": {"count": 1, "calls_30d": 4},
            "max_consecutive_tool_calls": {"claude_code": 0},
            "startup_instructions": {
                "claude_code_total_lines": 0,
                "claude_code_file_count": 0,
                "codex_total_bytes": 0,
                "codex_file_count": 0,
            },
            "secret_scan": {
                "repo": {"counts_by_kind": {}, "scanned_file_count": 0, "skipped_file_count": 0},
                "config": {"counts_by_kind": {}, "scanned_file_count": 0},
            },
        },
        "tools_detected": {"claude_code": True, "codex": False},
        "window_days": 30,
    }
    base.update(overrides)
    return base


class EscapeTest(unittest.TestCase):
    def test_html_is_escaped_in_named_counts(self):
        result = minimal_result()
        result["reference"]["names_included"] = True
        result["reference"]["named"] = {
            "skills": {"<script>alert(1)</script>": 3},
            "agents": {},
            "connectors": {},
        }
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertNotIn("<script>alert(1)</script>", html_out)
        self.assertIn("&lt;script&gt;", html_out)


class BasicStructureTest(unittest.TestCase):
    def test_build_html_contains_score_and_type(self):
        result = minimal_result()
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertIn("50", html_out)
        self.assertIn("全体がほどほどの型", html_out)
        self.assertIn("<!doctype html>", html_out.lower())

    def test_unmeasured_item_marked(self):
        result = minimal_result()
        result["items"]["F3"] = {
            "name": "指示が具体的で、守れたか確かめられるか",
            "pillar": "foundation",
            "judge": "ai",
            "judge_label": "AIの判断",
            "status": "unmeasured",
        }
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertIn("測定できず", html_out)

    def test_cover_shows_total_over_judged_not_judged_twice(self):
        """HIGH finding #5: 表紙の判定数表示が誤っていた（judged/judgedになっていた）。"""
        result = minimal_result(judged_item_count=19, total_item_count=23)
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertIn("全23項目中19項目を判定", html_out)
        self.assertNotIn("19項目中19項目を判定", html_out)

    def test_cover_has_two_fixed_intro_lines(self):
        result = minimal_result()
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertIn("ハーネス＝AIの周りに置く設定・指示・道具の一式", html_out)
        self.assertIn("チャット画面での利用は数えていない", html_out)

    def test_next_fix_uses_verb_fix_text_not_bare_item_name(self):
        result = minimal_result(
            next_fixes=[{"id": "S2", "pillar": "safety", "name": "秘密ファイルを読ませない設定がある", "fix_text": "秘密ファイルを読ませない設定を足す"}]
        )
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertIn("秘密ファイルを読ませない設定を足す", html_out)

    def test_items_are_sorted_by_numeric_id_order(self):
        """F1, F2, ..., F10, F11 の順（文字列ソートだと F1,F10,F11,F2... になってしまう）。"""
        result = minimal_result()
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        pos = {iid: html_out.find(f">{iid}　") for iid in ("F1", "F2", "F10", "F11")}
        self.assertTrue(pos["F1"] < pos["F2"] < pos["F10"] < pos["F11"])

    def test_items_table_has_thead_for_page_break_repeat(self):
        result = minimal_result()
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertIn("<thead>", html_out)

    def test_counttable_has_thead(self):
        result = minimal_result()
        result["reference"]["names_included"] = True
        result["reference"]["named"] = {"skills": {"foo": 3}, "agents": {}, "connectors": {}}
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertRegex(html_out, r"counttable\">\s*<thead>")


class NameDisplayTest(unittest.TestCase):
    def test_names_not_shown_when_names_included_false(self):
        result = minimal_result()
        result["reference"]["names_included"] = False
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertNotIn("固有名を含みます", html_out)

    def test_names_shown_with_show_names_note(self):
        result = minimal_result()
        result["reference"]["names_included"] = True
        result["reference"]["named"] = {
            "skills": {"my-own-skill": 3},
            "agents": {"my-agent": 1},
            "connectors": {"my-connector": 2},
        }
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertIn("my-own-skill", html_out)
        self.assertIn("固有名を含みます", html_out)

    def test_meaningless_identifier_filtered_out_even_with_show_names(self):
        result = minimal_result()
        result["reference"]["names_included"] = True
        result["reference"]["named"] = {
            "skills": {},
            "agents": {},
            "connectors": {
                "88c7e73d-7e62-4739-a49f-6947046200cd": 58,
                "real-connector-name": 10,
            },
        }
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertNotIn("88c7e73d-7e62-4739-a49f-6947046200cd", html_out)
        self.assertIn("real-connector-name", html_out)
        self.assertIn("ほか1件", html_out)


class WordingUpdateTest(unittest.TestCase):
    """3回目差し戻し 文言のみの変更（4・5）。"""

    def test_skipped_file_wording_is_yomanakatta_with_reason(self):
        result = minimal_result()
        result["reference"]["secret_scan"]["repo"]["skipped_file_count"] = 3
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertIn("読まなかった", html_out)
        self.assertIn("画像など文字でないもの、1MBを超えるもの", html_out)
        self.assertNotIn("飛ばした", html_out)

    def test_usage_counts_note_mentions_bias_check(self):
        result = minimal_result()
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertIn("少数の道具に偏っていないかの目安", html_out)

    def test_blindspots_page_mentions_lowercase_value_exclusion(self):
        result = minimal_result()
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        html_out = render.build_html(template, result)
        self.assertIn(
            "小文字だけの値や、小文字・数字・ハイフンだけの値は、名前や見本とみなして数えない",
            html_out,
        )


class CoverLayoutTest(unittest.TestCase):
    """v2.5（16-3・16-4）: 色の帯は無くした。説明の2行は見出しの直後、ダッシュボードと点数より前に置く。"""

    def _html(self, result):
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        return render.build_html(template, result)

    def test_intro_comes_right_after_header_and_before_score(self):
        html_out = self._html(minimal_result())
        head_end = html_out.index("</header>")
        intro_pos = html_out.index('class="intro"')
        score_pos = html_out.index('class="scorebox')
        self.assertTrue(head_end < intro_pos < score_pos)

    def test_withheld_score_shows_message_not_number(self):
        result = minimal_result()
        result["score"] = None
        result["type_name"] = None
        result["score_withheld"] = True
        html_out = self._html(result)
        self.assertIn("まだ測れるものが少ないため", html_out)
        self.assertNotIn("None", html_out)

    def test_insufficient_pillar_is_labelled(self):
        result = minimal_result()
        pid = result["pillar_order"][0]
        result["pillars"][pid]["sufficient"] = False
        self.assertIn("判定不足", self._html(result))

    def test_daily_chart_has_one_bar_per_day(self):
        result = minimal_result()
        result["daily_30d"] = [{"date": f"11-{i:02d}", "active_seconds": i * 60, "sessions": 1} for i in range(1, 31)]
        result["usage_breadth"] = {k: {"own": 4, "used": 1} for k in ("skills", "agents", "connectors")}
        result["autonomy"] = {"tool_calls_30d": 1234, "max_consecutive": 35, "sessions_20plus": 2,
                              "agent_relay_sessions": 1}
        html_out = self._html(result)
        self.assertEqual(html_out.count('class="bar"') + html_out.count('class="bar zero"'), 30)
        self.assertIn("使用 <b class=\"num\">1</b> / 4本", html_out)
        self.assertIn("1,234", html_out)

    def test_v4_result_without_dashboard_keys_still_renders(self):
        html_out = self._html(minimal_result())
        self.assertNotIn('class="chart"', html_out)


class MeaninglessIdentifierUnitTest(unittest.TestCase):
    def test_uuid_is_meaningless(self):
        self.assertTrue(render.is_meaningless_identifier("88c7e73d-7e62-4739-a49f-6947046200cd"))

    def test_long_hex_is_meaningless(self):
        self.assertTrue(render.is_meaningless_identifier("a1b2c3d4e5f60718"))

    def test_normal_name_is_not_meaningless(self):
        self.assertFalse(render.is_meaningless_identifier("publish-client-html"))
        self.assertFalse(render.is_meaningless_identifier("dev-loop"))


class ItemReasonTest(unittest.TestCase):
    """v3: 項目ごとの理由をレポートに出す。v2（理由なし）でも壊れない。"""

    def _html(self, result):
        template = (REPO_ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        return render.build_html(template, result)

    def test_v3_reason_is_shown_and_escaped(self):
        result = minimal_result(schema_version=3)
        result["items"]["F1"] = dict(result["items"]["F1"], reason="指示書が2件あり、1件以上という基準を満たしています。<b>x</b>",
                                     facts=[{"label": "指示書の数", "value": "2件"}])
        out = self._html(result)
        self.assertIn("指示書が2件あり、1件以上という基準を満たしています。", out)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", out)
        self.assertIn('class="reason"', out)

    def test_v2_without_reason_still_renders(self):
        result = minimal_result()
        out = self._html(result)
        self.assertNotIn('class="reason"', out)
        self.assertIn("作業フォルダに指示書がある", out)

    def test_non_string_reason_is_ignored(self):
        result = minimal_result(schema_version=3)
        result["items"]["F1"] = dict(result["items"]["F1"], reason=None, facts=None)
        out = self._html(result)
        self.assertNotIn('class="reason"', out)


if __name__ == "__main__":
    unittest.main()
