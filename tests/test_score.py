"""score.py の単体テスト。AI・本人回答の確定ロジック、点数・型・次に直す項目の計算。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import score  # noqa: E402


def item_def(iid, pillar, judge, merge="any"):
    return {"id": iid, "pillar": pillar, "judge": judge, "name": f"項目{iid}", "merge": merge}


class AiDoubleCheckTest(unittest.TestCase):
    def test_ai_item_pass_when_two_answers_agree_yes(self):
        d = item_def("F3", "foundation", "ai")
        facts = {"per_tool": {"claude_code": {"target_found": True}}}
        aij = {"F3": {"claude_code": {"answer_1": True, "answer_2": True, "evidence_lines": [3]}}}
        r = score.score_item(d, facts, aij)
        self.assertEqual(r["status"], "pass")

    def test_ai_item_fail_when_two_answers_agree_no(self):
        d = item_def("F4", "foundation", "ai")
        facts = {"per_tool": {"claude_code": {"target_found": True}}}
        aij = {"F4": {"claude_code": {"answer_1": False, "answer_2": False}}}
        r = score.score_item(d, facts, aij)
        self.assertEqual(r["status"], "fail")

    def test_ai_item_unmeasured_when_two_answers_disagree(self):
        d = item_def("F7", "foundation", "ai")
        facts = {"per_tool": {"claude_code": {"target_found": True, "candidates": ["a"]}}}
        aij = {"F7": {"claude_code": {"answer_1": True, "answer_2": False}}}
        r = score.score_item(d, facts, aij)
        self.assertEqual(r["status"], "unmeasured")

    def test_ai_item_unmeasured_when_no_target(self):
        d = item_def("F3", "foundation", "ai")
        facts = {"per_tool": {"claude_code": {"target_found": False}}}
        r = score.score_item(d, facts, {})
        self.assertEqual(r["status"], "unmeasured")


class MachineAiFallbackTest(unittest.TestCase):
    def test_d3_pass_from_machine_without_ai(self):
        d = item_def("D3", "delegate", "machine_ai")
        facts = {"per_tool": {"claude_code": {"measured": True, "pass": True, "needs_ai_fallback": False}}}
        r = score.score_item(d, facts, {})
        self.assertEqual(r["status"], "pass")

    def test_d3_fallback_to_ai_when_not_found(self):
        d = item_def("D3", "delegate", "machine_ai")
        facts = {"per_tool": {"claude_code": {"measured": False, "pass": None, "needs_ai_fallback": True}}}
        aij = {"D3": {"claude_code": {"answer_1": False, "answer_2": False}}}
        r = score.score_item(d, facts, aij)
        self.assertEqual(r["status"], "fail")

    def test_d3_unmeasured_when_fallback_not_answered_yet(self):
        d = item_def("D3", "delegate", "machine_ai")
        facts = {"per_tool": {"claude_code": {"measured": False, "pass": None, "needs_ai_fallback": True}}}
        r = score.score_item(d, facts, {})
        self.assertEqual(r["status"], "unmeasured")

    def test_g3_needs_ai_confirmation_even_when_candidate_found(self):
        d = item_def("G3", "grow", "machine_ai")
        facts = {"combined": {"measured": True, "needs_ai_confirmation": True}}
        aij = {"G3": {"combined": {"answer_1": True, "answer_2": True}}}
        r = score.score_item(d, facts, aij)
        self.assertEqual(r["status"], "pass")

    def test_g3_unmeasured_when_no_candidate(self):
        d = item_def("G3", "grow", "machine_ai")
        facts = {"combined": {"measured": False, "needs_ai_confirmation": False}}
        r = score.score_item(d, facts, {})
        self.assertEqual(r["status"], "unmeasured")


class MachineUserFallbackTest(unittest.TestCase):
    def test_d2_pass_from_machine(self):
        d = item_def("D2", "delegate", "machine_user")
        facts = {"per_tool": {"claude_code": {"measured": True, "pass": True}}}
        r = score.score_item(d, facts, {})
        self.assertEqual(r["status"], "pass")

    def test_d2_user_answers_yes(self):
        d = item_def("D2", "delegate", "machine_user")
        facts = {"per_tool": {"claude_code": {"measured": False, "pass": None, "needs_user_fallback": True}}}
        aij = {"D2": {"claude_code": {"answer": True}}}
        r = score.score_item(d, facts, aij)
        self.assertEqual(r["status"], "pass")

    def test_d2_unmeasured_without_user_answer(self):
        d = item_def("D2", "delegate", "machine_user")
        facts = {"per_tool": {"claude_code": {"measured": False, "pass": None, "needs_user_fallback": True}}}
        r = score.score_item(d, facts, {})
        self.assertEqual(r["status"], "unmeasured")


class PillarMergeTest(unittest.TestCase):
    """SPEC 5-2（2回目差し戻し）: 合わせ方は柱ではなく項目ごと（merge: all/any）で決まる。"""

    def test_merge_all_requires_all_measured_tools_to_pass(self):
        d = item_def("S3", "safety", "machine", merge="all")
        facts = {
            "per_tool": {
                "claude_code": {"measured": True, "pass": True},
                "codex": {"measured": True, "pass": False},
            }
        }
        r = score.score_item(d, facts, {})
        self.assertEqual(r["status"], "fail")

    def test_merge_any_passes_if_any_tool_passes(self):
        d = item_def("F10", "foundation", "machine", merge="any")
        facts = {
            "per_tool": {
                "claude_code": {"measured": True, "pass": True},
                "codex": {"measured": True, "pass": False},
            }
        }
        r = score.score_item(d, facts, {})
        self.assertEqual(r["status"], "pass")

    def test_unmeasured_when_no_tool_measured(self):
        d = item_def("F11", "foundation", "machine", merge="any")
        facts = {"per_tool": {"codex": {"measured": False, "pass": None}}}
        r = score.score_item(d, facts, {})
        self.assertEqual(r["status"], "unmeasured")

    def test_f4_is_merge_all_even_though_foundation_pillar_has_other_any_items(self):
        """裁定の理由そのもの: F4は土台の柱だが、矛盾（×）が片方にあれば全体も×。"""
        d = item_def("F4", "foundation", "ai", merge="all")
        facts = {"per_tool": {"claude_code": {"target_found": True}, "codex": {"target_found": True}}}
        aij = {
            "F4": {
                "claude_code": {"answer_1": False, "answer_2": False},  # 矛盾あり
                "codex": {"answer_1": True, "answer_2": True},  # 矛盾なし
            }
        }
        r = score.score_item(d, facts, aij)
        self.assertEqual(r["status"], "fail")

    def test_f2_is_merge_all(self):
        d = item_def("F2", "foundation", "machine", merge="all")
        facts = {
            "per_tool": {
                "claude_code": {"measured": True, "pass": False},
                "codex": {"measured": True, "pass": True},
            }
        }
        r = score.score_item(d, facts, {})
        self.assertEqual(r["status"], "fail")

    def test_f1_unaffected_stays_pass_under_mixed_tools(self):
        """F1等（merge: any）は、片方が×でも全体は○のまま。"""
        d = item_def("F1", "foundation", "machine", merge="any")
        facts = {
            "per_tool": {
                "claude_code": {"measured": True, "pass": False},
                "codex": {"measured": True, "pass": True},
            }
        }
        r = score.score_item(d, facts, {})
        self.assertEqual(r["status"], "pass")

    def test_items_json_assigns_merge_all_only_to_specified_six_items(self):
        import json

        items_path = Path(__file__).resolve().parent.parent / "items.json"
        with items_path.open(encoding="utf-8") as fh:
            items_def = json.load(fh)
        all_merge_ids = {it["id"] for it in items_def["items"] if it.get("merge") == "all"}
        self.assertEqual(all_merge_ids, {"S1", "S2", "S3", "S4", "F2", "F4"})


class ScoringMathTest(unittest.TestCase):
    def test_round_half_up(self):
        self.assertEqual(score.round_half_up(59.5), 60)
        self.assertEqual(score.round_half_up(59.49), 59)
        self.assertEqual(score.round_half_up(0.0), 0)

    def test_pillar_excluded_when_zero_judged(self):
        summary = {
            "foundation": {"name": "土台", "judged_count": 0, "total_count": 2, "passed_count": 0, "rate": None},
            "safety": {"name": "安全", "judged_count": 2, "passed_count": 2, "total_count": 2, "rate": 1.0},
        }
        s, judged = score.compute_score(summary)
        self.assertEqual(s, 100)

    def test_score_none_when_nothing_judged(self):
        summary = {
            "foundation": {"name": "土台", "judged_count": 0, "total_count": 2, "passed_count": 0, "rate": None},
        }
        s, judged = score.compute_score(summary)
        self.assertIsNone(s)


class TypeNameTest(unittest.TestCase):
    def _summary(self, rates):
        return {
            pid: {"name": name, "rate": rate, "judged_count": 1, "passed_count": 1, "total_count": 1}
            for pid, name, rate in rates
        }

    def test_all_strong(self):
        summary = self._summary(
            [("foundation", "土台", 1.0), ("safety", "安全", 0.9), ("grow", "育つ仕組み", 0.85), ("delegate", "任せ方", 1.0)]
        )
        self.assertEqual(score.compute_type_name(summary), "全体が揃っている型")

    def test_all_weak(self):
        summary = self._summary(
            [("foundation", "土台", 0.1), ("safety", "安全", 0.2), ("grow", "育つ仕組み", 0.0), ("delegate", "任せ方", 0.3)]
        )
        self.assertEqual(score.compute_type_name(summary), "これから整える型")

    def test_mixed_strong_and_weak(self):
        summary = self._summary(
            [("foundation", "土台", 0.9), ("safety", "安全", 0.2), ("grow", "育つ仕組み", 0.7), ("delegate", "任せ方", 0.7)]
        )
        self.assertEqual(score.compute_type_name(summary), "土台は強く、安全が薄い型")

    def test_multiple_strong_and_weak_joined_with_touten(self):
        """v2.1 6章: 複数あるときは読点「、」でつなぐ（「と」ではない）。"""
        summary = self._summary(
            [("foundation", "土台", 0.9), ("safety", "安全", 0.2), ("grow", "育つ仕組み", 0.85), ("delegate", "任せ方", 0.1)]
        )
        self.assertEqual(score.compute_type_name(summary), "土台、育つ仕組みは強く、安全、任せ方が薄い型")

    def test_strong_only(self):
        summary = self._summary([("foundation", "土台", 0.9), ("safety", "安全", 0.7)])
        self.assertEqual(score.compute_type_name(summary), "土台が強い型")

    def test_weak_only(self):
        summary = self._summary([("foundation", "土台", 0.2), ("safety", "安全", 0.7)])
        self.assertEqual(score.compute_type_name(summary), "土台が薄い型")

    def test_neither(self):
        summary = self._summary([("foundation", "土台", 0.7), ("safety", "安全", 0.65)])
        self.assertEqual(score.compute_type_name(summary), "全体がほどほどの型")


class NextFixesTest(unittest.TestCase):
    def test_orders_safety_first_then_foundation_then_delegate_then_grow(self):
        scored = [
            {"id": "G1", "pillar": "grow", "status": "fail"},
            {"id": "F1", "pillar": "foundation", "status": "fail"},
            {"id": "S1", "pillar": "safety", "status": "fail"},
            {"id": "D1", "pillar": "delegate", "status": "fail"},
            {"id": "F2", "pillar": "foundation", "status": "pass"},
        ]
        items_def_by_id = {
            "G1": {"name": "G1名", "fix_text": "G1を直す"},
            "F1": {"name": "F1名", "fix_text": "F1を直す"},
            "S1": {"name": "S1名", "fix_text": "S1を直す"},
            "D1": {"name": "D1名", "fix_text": "D1を直す"},
        }
        out = score.compute_next_fixes(scored, items_def_by_id, limit=3)
        self.assertEqual([o["id"] for o in out], ["S1", "F1", "D1"])
        self.assertEqual(out[0]["fix_text"], "S1を直す")


if __name__ == "__main__":
    unittest.main()
