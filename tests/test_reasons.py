"""項目ごとの理由（reason・facts、schema_version 3）のテスト。

- 23項目 × 3状態（通った・通らなかった・判定なし）で、理由が空でなく300字以内で、
  禁止のもの（パス・拡張子つきの名前・URL・メール・英数字の識別子）を含まないこと
- facts が 0〜6個で、label 1〜40字・value 1〜60字
- 検査の関数そのものが、禁止のものを見つけられること
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reasons  # noqa: E402
import score  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ITEMS = {it["id"]: it for it in json.loads((REPO_ROOT / "items.json").read_text(encoding="utf-8"))["items"]}

YES = {"answer_1": True, "answer_2": True, "evidence_lines": [3, 9]}
NO = {"answer_1": False, "answer_2": False, "evidence_lines": [4]}
SPLIT = {"answer_1": True, "answer_2": False}


def cc_cx(cc=None, cx=None):
    per_tool = {}
    if cc is not None:
        per_tool["claude_code"] = cc
    if cx is not None:
        per_tool["codex"] = cx
    return {"per_tool": per_tool}


def ai_target(n):
    return {"target_found": n > 0, "target_count": n}


CODEX_UNREADABLE = {"measured": False, "pass": None}
FLAGS_OK = {"never_ask": False, "full_access": False, "always_ask": False}
FLAGS_BAD = {"never_ask": True, "full_access": True, "always_ask": True}
NO_SIGNAL = {"measured": False, "pass": None, **FLAGS_OK}

# 項目ID → 状態 → [(item_facts, ai_judgments の項目分), ...]
SCENARIOS = {
    "F1": {
        "pass": [(cc_cx({"measured": True, "pass": True, "count": 2}, {"measured": True, "pass": True, "count": 1}), {})],
        "fail": [(cc_cx({"measured": True, "pass": False, "count": 0}), {})],
        "unmeasured": [(cc_cx(), {})],
    },
    "F2": {
        "pass": [(cc_cx({"measured": True, "pass": True, "file_count": 4, "max_lines": 120, "over_count": 0,
                         "limit_lines": 200, "total_lines": 300},
                        {"measured": True, "pass": True, "file_count": 1, "total_bytes": 2048, "limit_bytes": 32768}), {})],
        "fail": [
            (cc_cx({"measured": True, "pass": False, "file_count": 3, "max_lines": 412, "over_count": 2,
                    "limit_lines": 200, "total_lines": 700}), {}),
            (cc_cx(None, {"measured": True, "pass": False, "file_count": 2, "total_bytes": 40000, "limit_bytes": 32768}), {}),
        ],
        "unmeasured": [(cc_cx({"measured": False, "pass": None, "file_count": 0, "max_lines": 0, "over_count": 0,
                               "limit_lines": 200}), {})],
    },
    "F3": {
        "pass": [(cc_cx(ai_target(2), ai_target(1)), {"claude_code": YES, "codex": YES})],
        "fail": [(cc_cx(ai_target(2)), {"claude_code": NO})],
        "unmeasured": [
            (cc_cx(ai_target(0)), {}),
            (cc_cx(ai_target(1)), {"claude_code": SPLIT}),
            (cc_cx(ai_target(1)), {}),
        ],
    },
    "F4": {
        "pass": [(cc_cx(ai_target(13)), {"claude_code": YES})],
        "fail": [(cc_cx(ai_target(13), ai_target(1)), {"claude_code": YES, "codex": NO})],
        "unmeasured": [(cc_cx(ai_target(3)), {"claude_code": SPLIT}), (cc_cx(), {})],
    },
    "F5": {
        "pass": [(cc_cx({"measured": True, "pass": True, "count": 12}), {})],
        "fail": [(cc_cx({"measured": True, "pass": False, "count": 0}, {"measured": True, "pass": False, "count": 0}), {})],
        "unmeasured": [(cc_cx(), {})],
    },
    "F6": {
        "pass": [(cc_cx({"measured": True, "pass": True, "count": 3, "own_count": 12, "use_total": 41,
                         "session_count": 90}, CODEX_UNREADABLE), {})],
        "fail": [(cc_cx({"measured": True, "pass": False, "count": 0, "own_count": 2, "use_total": 0,
                         "session_count": 5}), {})],
        "unmeasured": [
            (cc_cx({"measured": False, "pass": False, "count": 0, "own_count": 0, "use_total": 0, "session_count": 5}), {}),
            (cc_cx({"measured": False, "pass": False, "count": 0, "own_count": 3, "use_total": 0, "session_count": 0}), {}),
            (cc_cx(None, CODEX_UNREADABLE), {}),
        ],
    },
    "F7": {
        "pass": [(cc_cx(ai_target(5)), {"claude_code": YES})],
        "fail": [(cc_cx(ai_target(5)), {"claude_code": NO})],
        "unmeasured": [(cc_cx(ai_target(0)), {}), (cc_cx(ai_target(5)), {"claude_code": SPLIT})],
    },
    "F8": {
        "pass": [(cc_cx({"measured": True, "pass": True, "count": 4}), {})],
        "fail": [(cc_cx({"measured": True, "pass": False, "count": 0}), {})],
        "unmeasured": [(cc_cx(), {})],
    },
    "F9": {
        "pass": [(cc_cx({"measured": True, "pass": True, "count": 2, "own_count": 4, "use_total": 7,
                         "session_count": 9}), {})],
        "fail": [(cc_cx({"measured": True, "pass": False, "count": 0, "own_count": 4, "use_total": 0,
                         "session_count": 9}), {})],
        "unmeasured": [
            (cc_cx({"measured": False, "pass": False, "count": 0, "own_count": 0, "use_total": 0, "session_count": 9}), {}),
            (cc_cx(None, CODEX_UNREADABLE), {}),
        ],
    },
    "F10": {
        "pass": [
            (cc_cx({"measured": True, "pass": True, "config_count": 3, "used_in_records": True},
                   {"measured": True, "pass": True}), {}),
            (cc_cx({"measured": True, "pass": True, "config_count": 0, "used_in_records": True}), {}),
        ],
        "fail": [(cc_cx({"measured": True, "pass": False, "config_count": 0, "used_in_records": False},
                        {"measured": True, "pass": False}), {})],
        "unmeasured": [(cc_cx(), {})],
    },
    "F11": {
        "pass": [
            (cc_cx({"measured": True, "pass": True, "calls_30d": 17, "session_count": 9}), {}),
            (cc_cx({"measured": True, "pass": True, "calls_30d": 0, "session_count": 9}), {}),
        ],
        "fail": [(cc_cx({"measured": True, "pass": False, "calls_30d": 0, "session_count": 9}, CODEX_UNREADABLE), {})],
        "unmeasured": [(cc_cx({"measured": False, "pass": False, "calls_30d": 0, "session_count": 0}), {})],
    },
    "S1": {
        "pass": [({"combined": {"measured": True, "pass": True,
                                "repo": {"counts_by_kind": {}, "scanned_file_count": 663, "skipped_file_count": 2},
                                "config": {"counts_by_kind": {}, "scanned_file_count": 5, "skipped_file_count": 0}}}, {})],
        "fail": [({"combined": {"measured": True, "pass": False,
                                "repo": {"counts_by_kind": {"openai_or_anthropic": 2}, "scanned_file_count": 10,
                                         "skipped_file_count": 0},
                                "config": {"counts_by_kind": {"named_secret": 1}, "scanned_file_count": 3,
                                           "skipped_file_count": 1}}}, {})],
        "unmeasured": [({"combined": {"measured": False, "pass": None}}, {})],
    },
    "S2": {
        "pass": [(cc_cx({"measured": True, "pass": True, "rule_count": 3}, CODEX_UNREADABLE), {})],
        "fail": [(cc_cx({"measured": True, "pass": False, "rule_count": 0}), {})],
        "unmeasured": [(cc_cx(None, CODEX_UNREADABLE), {})],
    },
    "S3": {
        "pass": [(cc_cx({"measured": True, "pass": True, "rule_count": 6}, {"measured": True, "pass": True, **FLAGS_OK}), {})],
        "fail": [
            (cc_cx({"measured": True, "pass": False, "rule_count": 0}), {}),
            (cc_cx(None, {"measured": True, "pass": False, **FLAGS_BAD}), {}),
        ],
        "unmeasured": [(cc_cx(None, NO_SIGNAL), {})],
    },
    "S4": {
        "pass": [
            (cc_cx({"measured": True, "pass": True, "mode_set": True}, {"measured": True, "pass": True, **FLAGS_OK}), {}),
            (cc_cx({"measured": True, "pass": True, "mode_set": False}), {}),
        ],
        "fail": [
            (cc_cx({"measured": True, "pass": False, "mode_set": True}), {}),
            (cc_cx(None, {"measured": True, "pass": False, **FLAGS_BAD}), {}),
        ],
        "unmeasured": [(cc_cx(None, NO_SIGNAL), {})],
    },
    "G1": {
        "pass": [({"combined": {"measured": True, "pass": True, "is_git_repo": True, "has_remote": True,
                                "instruction_tracked": True}}, {})],
        "fail": [
            ({"combined": {"measured": True, "pass": False, "is_git_repo": False, "has_remote": False,
                           "instruction_tracked": False}}, {}),
            ({"combined": {"measured": True, "pass": False, "is_git_repo": True, "has_remote": False,
                           "instruction_tracked": True}}, {}),
            ({"combined": {"measured": True, "pass": False, "is_git_repo": True, "has_remote": True,
                           "instruction_tracked": False}}, {}),
        ],
        "unmeasured": [({"combined": {"measured": False, "pass": None}}, {})],
    },
    "G2": {
        "pass": [
            ({"combined": {"measured": True, "pass": True, "global_has_content": True, "local_has_content": True,
                           "has_override": False}}, {}),
            ({"combined": {"measured": True, "pass": True, "global_has_content": False, "local_has_content": True,
                           "has_override": True}}, {}),
        ],
        "fail": [({"combined": {"measured": True, "pass": False, "global_has_content": False,
                                "local_has_content": True, "has_override": False}}, {})],
        "unmeasured": [({"combined": {"measured": False, "pass": False, "global_has_content": False,
                                      "local_has_content": False, "has_override": False}}, {})],
    },
    "G3": {
        "pass": [({"combined": {"measured": True, "pass": None, "needs_ai_confirmation": True, "stop_hook_count": 2,
                                "scheduled_count": 3}}, {"combined": YES})],
        "fail": [({"combined": {"measured": True, "pass": None, "needs_ai_confirmation": True, "stop_hook_count": 1,
                                "scheduled_count": 0}}, {"combined": NO})],
        "unmeasured": [
            ({"combined": {"measured": False, "pass": None, "needs_ai_confirmation": False, "stop_hook_count": 0,
                           "scheduled_count": 0}}, {}),
            ({"combined": {"measured": True, "pass": None, "needs_ai_confirmation": True, "stop_hook_count": 0,
                           "scheduled_count": 2}}, {"combined": SPLIT}),
            ({"combined": {"measured": True, "pass": None, "needs_ai_confirmation": True, "stop_hook_count": 0,
                           "scheduled_count": 2}}, {}),
        ],
    },
    "D1": {
        "pass": [
            (cc_cx({"measured": True, "pass": True, "allow_count": 40, "auto_mode": False},
                   {"measured": True, "pass": True, **FLAGS_OK}), {}),
            (cc_cx({"measured": True, "pass": True, "allow_count": 0, "auto_mode": True}), {}),
        ],
        "fail": [
            (cc_cx({"measured": True, "pass": False, "allow_count": 0, "auto_mode": False}), {}),
            (cc_cx(None, {"measured": True, "pass": False, **FLAGS_BAD}), {}),
        ],
        "unmeasured": [(cc_cx(None, NO_SIGNAL), {})],
    },
    "D2": {
        "pass": [
            (cc_cx({"measured": True, "pass": True, "needs_user_fallback": False, "definition_count": 2,
                    "recent": True}), {}),
            (cc_cx({"measured": False, "pass": None, "needs_user_fallback": True, "definition_count": 1,
                    "recent": False}), {"claude_code": {"answer": True}}),
        ],
        "fail": [(cc_cx({"measured": False, "pass": None, "needs_user_fallback": True, "definition_count": 1,
                         "recent": False}), {"claude_code": {"answer": False}})],
        "unmeasured": [
            (cc_cx({"measured": False, "pass": None, "needs_user_fallback": False, "definition_count": 0,
                    "recent": False}), {}),
            (cc_cx({"measured": False, "pass": None, "needs_user_fallback": True, "definition_count": 3,
                    "recent": False}), {}),
        ],
    },
    "D3": {
        "pass": [
            (cc_cx({"measured": True, "pass": True, "needs_ai_fallback": False, "stop_hook_count": 2,
                    "readonly_agent_count": 1}), {}),
            (cc_cx({"measured": True, "pass": False, "needs_ai_fallback": True, "stop_hook_count": 0,
                    "readonly_agent_count": 0}), {"claude_code": YES}),
            (cc_cx(None, {"measured": True, "pass": True, "needs_ai_fallback": False, "hook_file_found": True,
                          "stop_hook_count": 1}), {}),
        ],
        "fail": [
            (cc_cx({"measured": True, "pass": False, "needs_ai_fallback": True, "stop_hook_count": 0,
                    "readonly_agent_count": 0}), {"claude_code": NO}),
            (cc_cx(None, {"measured": True, "pass": False, "needs_ai_fallback": True, "hook_file_found": True,
                          "stop_hook_count": 0}), {"codex": NO}),
        ],
        "unmeasured": [
            (cc_cx({"measured": True, "pass": False, "needs_ai_fallback": True, "stop_hook_count": 0,
                    "readonly_agent_count": 0}), {"claude_code": SPLIT}),
            (cc_cx(None, {"measured": False, "pass": None, "needs_ai_fallback": True, "hook_file_found": False,
                          "stop_hook_count": 0}), {}),
        ],
    },
    "D4": {
        "pass": [(cc_cx({"measured": True, "pass": True, "hit_count": 3, "own_count": 5, "session_count": 40},
                        CODEX_UNREADABLE), {})],
        "fail": [(cc_cx({"measured": True, "pass": False, "hit_count": 0, "own_count": 5, "session_count": 40}), {})],
        "unmeasured": [
            (cc_cx({"measured": False, "pass": False, "hit_count": 0, "own_count": 0, "session_count": 40}), {}),
            (cc_cx({"measured": False, "pass": False, "hit_count": 0, "own_count": 2, "session_count": 0}), {}),
        ],
    },
    "D5": {
        "pass": [(cc_cx({"measured": True, "pass": True, "max_consecutive": 26, "threshold": 20,
                         "session_count": 40}), {})],
        "fail": [(cc_cx({"measured": True, "pass": False, "max_consecutive": 7, "threshold": 20,
                         "session_count": 40}), {})],
        "unmeasured": [
            (cc_cx({"measured": False, "pass": False, "max_consecutive": 0, "threshold": 20, "session_count": 0}), {}),
            (cc_cx(None, CODEX_UNREADABLE), {}),
        ],
    },
}


def run_scenario(iid, item_facts, ai_for_item):
    item_def = ITEMS[iid]
    aij = {iid: ai_for_item} if ai_for_item else {}
    scored = score.score_item(item_def, item_facts, aij)
    reason, facts = reasons.build_reason(item_def, item_facts, scored, aij)
    return scored["status"], reason, facts


class AllItemsAllStatesTest(unittest.TestCase):
    def test_scenarios_cover_23_items_and_3_states(self):
        self.assertEqual(set(SCENARIOS), set(ITEMS))
        self.assertEqual(len(ITEMS), 23)
        for iid, by_status in SCENARIOS.items():
            self.assertEqual(set(by_status), {"pass", "fail", "unmeasured"}, iid)

    def test_every_reason_is_valid_and_clean(self):
        seen = 0
        for iid, by_status in SCENARIOS.items():
            for expected, cases in by_status.items():
                for i, (item_facts, ai_for_item) in enumerate(cases):
                    with self.subTest(item=iid, status=expected, case=i):
                        status, reason, facts = run_scenario(iid, item_facts, ai_for_item)
                        self.assertEqual(status, expected)
                        self.assertIsInstance(reason, str)
                        self.assertTrue(1 <= len(reason) <= reasons.MAX_REASON_CHARS, reason)
                        self.assertEqual(reasons.find_forbidden(reason), [], reason)
                        self.assertTrue(reason.endswith("。"), reason)
                        self.assertIsInstance(facts, list)
                        self.assertLessEqual(len(facts), reasons.MAX_FACTS)
                        for f in facts:
                            self.assertEqual(set(f), {"label", "value"})
                            self.assertTrue(1 <= len(f["label"]) <= reasons.MAX_LABEL_CHARS, f)
                            self.assertTrue(1 <= len(f["value"]) <= reasons.MAX_VALUE_CHARS, f)
                            self.assertEqual(reasons.find_forbidden(f["label"]), [], f)
                            self.assertEqual(reasons.find_forbidden(f["value"]), [], f)
                        seen += 1
        self.assertGreaterEqual(seen, 69)

    def test_reason_states_comparison_with_criterion(self):
        _, reason, facts = run_scenario("F2", *SCENARIOS["F2"]["fail"][0])
        self.assertIn("412行", reason)
        self.assertIn("200行", reason)
        values = {f["label"]: f["value"] for f in facts}
        self.assertEqual(values.get("いちばん長い指示ファイル"), "412行")
        self.assertIn("200行未満", values.values())

    def test_no_evaluation_words(self):
        for iid, by_status in SCENARIOS.items():
            for cases in by_status.values():
                for item_facts, ai_for_item in cases:
                    _, reason, _ = run_scenario(iid, item_facts, ai_for_item)
                    for w in ("問題です", "素晴らしい", "危険", "優秀", "残念", "べきです"):
                        self.assertNotIn(w, reason, (iid, reason))

    def test_unmeasured_says_what_was_missing(self):
        _, reason, _ = run_scenario("F6", *SCENARIOS["F6"]["unmeasured"][1])
        self.assertIn("会話の記録", reason)
        self.assertIn("判定できませんでした", reason)

    def test_two_tools_are_both_described(self):
        _, reason, facts = run_scenario("F1", *SCENARIOS["F1"]["pass"][0])
        self.assertIn("Claude Code", reason)
        self.assertIn("Codex", reason)
        self.assertTrue(any("（Codex）" in f["label"] for f in facts))

    def test_ai_free_text_in_judgments_is_never_used(self):
        evil = dict(YES, reason="株式会社ヤマダの顧客-山田 ~/secret/a.md を参照", facts=[{"label": "x", "value": "y"}])
        _, reason, facts = run_scenario("F3", cc_cx(ai_target(1)), {"claude_code": evil})
        self.assertNotIn("ヤマダ", reason)
        self.assertNotIn("山田", json.dumps(facts, ensure_ascii=False))


class ForbiddenScannerTest(unittest.TestCase):
    def test_detects_forbidden_things(self):
        bad = [
            "場所は ~/.claude/skills/demo です",
            "a/b にあります",
            "C:\\Users\\x にある",
            "demo-skill が使われた",
            "report_writer が使われた",
            "mcp__slack を呼んだ",
            "設定は config.toml にある",
            "CLAUDE.local.md がある",
            "見本は .env にある",
            "https://example.com を見た",
            "www.example.com を見た",
            "taro@example.com に送った",
            "Slack が使われた",
            "permissions を見た",
            "03-1234-5678 に電話",
            "09012345678 に電話",
            "x" * 3,
        ]
        for s in bad:
            with self.subTest(s=s):
                self.assertNotEqual(reasons.find_forbidden(s), [], s)

    def test_allows_plain_japanese_with_tool_names_and_numbers(self):
        ok = [
            "Claude Codeでは、指示書が3件あり、1件以上という基準を満たしています。",
            "Codexでは、読まれる指示書の合計は40000バイトで、32768バイト未満という目安を超えています。",
            "作業フォルダはGitで管理されています。AIが2回読みました。",
            "200行未満",
            "41回",
        ]
        for s in ok:
            with self.subTest(s=s):
                self.assertEqual(reasons.find_forbidden(s), [], s)

    def test_sanitize_replaces_dirty_reason_with_fixed_text(self):
        reason, facts, replaced = reasons.sanitize("F5", "pass", "demo-skill が見つかった。", [{"label": "名前", "value": "a/b"}])
        self.assertTrue(replaced)
        self.assertEqual(reasons.find_forbidden(reason), [])
        self.assertEqual(facts, [])
        reason2, facts2, replaced2 = reasons.sanitize("F5", "pass", "スキルが2本あります。", [{"label": "数", "value": "2本"}])
        self.assertFalse(replaced2)
        self.assertEqual(reason2, "スキルが2本あります。")
        self.assertEqual(facts2, [{"label": "数", "value": "2本"}])

    def test_sanitize_rejects_too_long(self):
        reason, _, replaced = reasons.sanitize("F5", "fail", "あ" * 301, [])
        self.assertTrue(replaced)
        self.assertLessEqual(len(reason), 300)


if __name__ == "__main__":
    unittest.main()
