"""理由の文と数字が食い違わないことの総当たり（通ったのに数字が基準未満・通らなかったのに数字が基準以上が無いこと）。

collect.py・readers の判定の式を写した「判定の見本」で、数の組み合わせを総当たりし、
reasons.py の文の型が出す facts の数字と、文の結論（満たしています／満たしていません）が合うかを確かめる。
"""

from __future__ import annotations

import itertools
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reasons  # noqa: E402

N = (0, 1, 2, 19, 20, 25)
B = (False, True)


def num(v):
    m = re.match(r"^(\d+)", v)
    return int(m.group(1)) if m else None


# 項目 → 道具 → [(v, pass)] を作る関数。pass は collect・readers と同じ式で決める
def gen(iid, tool):
    if iid in ("F1",):
        for n in N:
            yield {"count": n}, n > 0
    elif iid in ("F6", "F9"):
        if tool == "codex":
            return
        for own, used, total in itertools.product(N, N, N):
            if used > own or (used > 0 and total < used) or (used == 0 and total > 0):
                continue  # collect では起きない組み合わせ（使われた本数と回数は同じ記録から数える）
            yield {"own_count": own, "count": used, "use_total": total, "session_count": 3}, used > 0
    elif iid == "F2":
        if tool == "codex":
            for total in (0, 100, 32767, 32768, 40000):
                yield {"file_count": 1, "total_bytes": total, "limit_bytes": 32768}, total < 32768
        else:
            for mx in (1, 199, 200, 412):
                over = 1 if mx >= 200 else 0
                yield {"file_count": 2, "max_lines": mx, "over_count": over, "limit_lines": 200}, mx < 200
    elif iid == "F11":
        if tool == "codex":
            return
        for calls, recent_session_used in itertools.product(N, B):
            # 判定は「直近30日に動いた会話に呼び出しがある」。回数は日付つきの呼び出しだけを数える
            yield {"calls_30d": calls, "session_count": 3}, recent_session_used or calls > 0
    elif iid in ("S2", "S3") and tool == "claude_code":
        cats = ("env", "keys") if iid == "S2" else ("delete", "force", "outward")
        for flags in itertools.product(B, repeat=len(cats)):
            for n, hooks in itertools.product(N, N):
                cov = dict(zip(cats, flags))
                yield {"rule_count": n, "hook_count": hooks, "covered": cov}, all(flags)
    elif iid == "D1" and tool == "claude_code":
        for n, auto in itertools.product(N, B):
            yield {"allow_count": n, "auto_mode": auto}, n > 0 or auto
    elif iid == "D3" and tool == "claude_code":
        for hooks, agents, key in itertools.product(N, N, B):
            has_hook = key or hooks > 0
            if hooks > 0 and not key:
                continue
            passed = has_hook or agents > 0
            yield {"stop_hook_count": hooks, "readonly_agent_count": agents, "needs_ai_fallback": not passed}, passed
    elif iid == "D4" and tool == "claude_code":
        for hits in N:
            yield {"hit_count": hits, "own_count": 3, "session_count": 30}, hits > 0
    elif iid == "D5" and tool == "claude_code":
        for mx in N:
            yield {"max_consecutive": mx, "threshold": 20, "session_count": 3}, mx >= 20


# 数字の向き: label → 通ったときに満たすべき条件
RULES = {
    "指示書の数": lambda x: x >= 1,
    "自分で用意したスキルの数": lambda x: x >= 1,
    "自分で定義したエージェントの数": lambda x: x >= 1,
    "直近30日に使われた数": lambda x: x >= 1,
    "直近30日の回数の合計": lambda x: x >= 1,
    "直近30日の呼び出し": lambda x: x >= 1,
    "該当する会話": lambda x: x >= 1,
    "いちばん長く続いた回数": lambda x: x >= 20,
    "いちばん長い指示ファイル": lambda x: x < 200,
    "目安を超えたファイル": lambda x: x == 0,
    "合計の大きさ": lambda x: x < 32768,
}
# その項目の主な数字のときだけ当てる（F6 の「自分で用意したスキルの数」は分母なので当てない）
ONLY_FOR = {"自分で用意したスキルの数": (), "自分で定義したエージェントの数": ()}
# 複数の数字のどれかで満たす項目（D1・D3・F10）
ANY_RULES = {
    "D1": ("許可の設定", "自動で判断するモード"),
    "D3": ("終了時に動くフック", "読むだけの確認役のエージェント", "終了時に動くフックの設定"),
}
ZERO_ARI = re.compile(r"(?<![0-9])0(件|回|本|行|個)(あり|が合計)")


def positive(value: str) -> bool:
    n = num(value)
    return n >= 1 if n is not None else value in ("あり", "はい")


class ConsistencyBruteForceTest(unittest.TestCase):
    def test_all_items_numbers_agree_with_verdict(self):
        checked = 0
        problems = []
        for iid, builder in reasons.ITEM_BUILDERS.items():
            for tool in ("claude_code", "codex"):
                for v, passed in gen(iid, tool):
                    r = {"measured": True, "pass": passed}
                    part = builder(tool, v, r, None)
                    s = part.sentence
                    facts = {f["label"]: f["value"] for f in part.facts}
                    checked += 1
                    if passed and NOT_MEETS_ANY(s) or (not passed and MEETS_ANY(s)):
                        problems.append((iid, tool, v, "結論", s))
                    if passed and ZERO_ARI.search(s):
                        problems.append((iid, tool, v, "0件あり", s))
                    for label, ok in RULES.items():
                        if label in ONLY_FOR and iid not in ONLY_FOR[label]:
                            continue
                        if label in facts and num(facts[label]) is not None:
                            if ok(num(facts[label])) != passed and label not in ("目安を超えたファイル",):
                                problems.append((iid, tool, v, label, facts[label], s))
                            if label == "目安を超えたファイル" and (num(facts[label]) == 0) != passed:
                                problems.append((iid, tool, v, label, facts[label], s))
                    # S2・S3（v2.5）: 系統のどれかが「止めていない」なら×、全部止めていれば○
                    if iid in ("S2", "S3") and tool == "claude_code":
                        if ("止めていない" in facts.values()) == passed:
                            problems.append((iid, tool, v, "系統", s))
                    if iid in ANY_RULES and tool == "claude_code":
                        present = [facts[label] for label in ANY_RULES[iid] if label in facts]
                        if present and any(positive(x) for x in present) != passed:
                            problems.append((iid, tool, v, "どれか", present, s))
        self.assertGreater(checked, 250)  # v2.5: F5・F8・F10 を外し、S2・S3 の系統の組み合わせを足した
        self.maxDiff = None
        self.assertEqual(problems, [], "\n".join(map(repr, problems)))


class G3ZeroCountTest(unittest.TestCase):
    def test_hook_setting_without_countable_entries_does_not_say_zero(self):
        c = {"needs_ai_confirmation": True, "stop_hook_count": 0, "scheduled_count": 0}
        part = reasons.COMBINED_BUILDERS["G3"](c, "pass", {"answer_1": True, "answer_2": True})
        self.assertNotIn("0件", part.sentence)
        self.assertIn("設定の中身をAIが2回読み", part.sentence)


def MEETS_ANY(s):
    return "満たしています" in s or "収まっています" in s


def NOT_MEETS_ANY(s):
    return "満たしていません" in s or "超えています" in s or "超えるもの" in s


if __name__ == "__main__":
    unittest.main()
