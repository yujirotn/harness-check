#!/usr/bin/env python3
"""ハーネス点検 — facts.json と ai_judgments.json から result.json を出す。

読むだけ・通信なし。書き込みは --out で指定した出力フォルダの中だけ。
標準ライブラリだけで動く（Python 3.9 以上）。
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path


JUDGE_LABELS = {
    "machine": "機械",
    "ai": "AIの判断",
    "machine_ai": "機械＋AIの判断",
    "machine_user": "機械＋本人の回答",
}

NEXT_FIX_PILLAR_ORDER = ["safety", "foundation", "delegate", "grow"]

STRONG_THRESHOLD = 0.8
WEAK_THRESHOLD = 0.6


def _ai_answer(entry: dict | None) -> bool | None:
    """二重判定（5-6）: 2回の答えが一致したときだけ確定させる。"""
    if not isinstance(entry, dict):
        return None
    if "answer_1" in entry and "answer_2" in entry:
        a1, a2 = entry.get("answer_1"), entry.get("answer_2")
        if isinstance(a1, bool) and isinstance(a2, bool) and a1 == a2:
            return a1
        return None
    # 単発回答（本人の回答など）
    a = entry.get("answer")
    return a if isinstance(a, bool) else None


def _resolve_tool_result(iid: str, judge: str, tool: str, v: dict, ai_judgments: dict) -> dict:
    measured = bool(v.get("measured"))
    passed = v.get("pass")

    if judge == "machine":
        return {"measured": measured, "pass": passed if measured else None}

    if judge == "machine_user":
        if measured and passed is not None:
            return {"measured": True, "pass": passed}
        if v.get("needs_user_fallback"):
            ans = _ai_answer((ai_judgments.get(iid) or {}).get(tool))
            if ans is not None:
                return {"measured": True, "pass": ans}
        return {"measured": False, "pass": None}

    if judge == "machine_ai":
        if measured and not v.get("needs_ai_fallback"):
            return {"measured": True, "pass": passed}
        if v.get("needs_ai_fallback"):
            ans = _ai_answer((ai_judgments.get(iid) or {}).get(tool))
            if ans is not None:
                return {"measured": True, "pass": ans}
        return {"measured": False, "pass": None}

    return {"measured": False, "pass": None}


def _merge_tools(merge_policy: str, tool_results: dict[str, dict]) -> dict:
    """複数の道具の合わせ方（SPEC 5-2・項目ごと）。

    merge_policy == "all": 欠点がないことを見る項目。測れた道具の全部が満たして○。
    merge_policy == "any"（既定）: あることを見る項目。どれか1つが満たせば○。
    """
    measured_tools = {t: r for t, r in tool_results.items() if r["measured"]}
    if not measured_tools:
        return {"measured": False, "pass": None}
    if merge_policy == "all":
        passed = all(r["pass"] for r in measured_tools.values())
    else:
        passed = any(r["pass"] for r in measured_tools.values())
    return {"measured": True, "pass": passed}


def score_item(item_def: dict, item_facts: dict, ai_judgments: dict) -> dict:
    iid = item_def["id"]
    judge = item_def["judge"]
    pillar = item_def["pillar"]
    merge_policy = item_def.get("merge", "any")

    if "combined" in item_facts:
        c = item_facts["combined"]
        if judge == "machine":
            measured = bool(c.get("measured"))
            passed = c.get("pass") if measured else None
        elif judge == "machine_ai":
            if c.get("needs_ai_confirmation"):
                ans = _ai_answer((ai_judgments.get(iid) or {}).get("combined"))
                measured, passed = (True, ans) if ans is not None else (False, None)
            else:
                measured, passed = False, None
        else:
            measured, passed = bool(c.get("measured")), c.get("pass")
        per_tool_detail = {"combined": {"measured": measured, "pass": passed}}
        return _finalize(iid, pillar, judge, measured, passed, per_tool_detail)

    per_tool = item_facts.get("per_tool", {})

    if judge == "ai":
        tool_results = {}
        for tool, target in per_tool.items():
            if not target.get("target_found"):
                continue
            ans = _ai_answer((ai_judgments.get(iid) or {}).get(tool))
            tool_results[tool] = {"measured": ans is not None, "pass": ans}
        merged = _merge_tools(merge_policy, tool_results)
        return _finalize(iid, pillar, judge, merged["measured"], merged["pass"], tool_results)

    tool_results = {}
    for tool, v in per_tool.items():
        tool_results[tool] = _resolve_tool_result(iid, judge, tool, v, ai_judgments)
    merged = _merge_tools(merge_policy, tool_results)
    return _finalize(iid, pillar, judge, merged["measured"], merged["pass"], tool_results)


def _finalize(iid, pillar, judge, measured, passed, per_tool_detail) -> dict:
    if not measured:
        status = "unmeasured"
    elif passed:
        status = "pass"
    else:
        status = "fail"
    return {
        "id": iid,
        "pillar": pillar,
        "judge": judge,
        "judge_label": JUDGE_LABELS[judge],
        "status": status,
        "per_tool": per_tool_detail,
    }


def round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def compute_pillar_summary(scored_items: list[dict], pillars: dict, pillar_order: list[str]) -> dict:
    summary = {}
    for pid in pillar_order:
        items_in = [s for s in scored_items if s["pillar"] == pid]
        judged = [s for s in items_in if s["status"] != "unmeasured"]
        passed = [s for s in judged if s["status"] == "pass"]
        rate = (len(passed) / len(judged)) if judged else None
        summary[pid] = {
            "name": pillars[pid],
            "judged_count": len(judged),
            "total_count": len(items_in),
            "passed_count": len(passed),
            "rate": rate,
        }
    return summary


def compute_score(pillar_summary: dict) -> tuple[int | None, int]:
    rates = [p["rate"] for p in pillar_summary.values() if p["rate"] is not None]
    judged_total = sum(p["judged_count"] for p in pillar_summary.values())
    if not rates:
        return None, judged_total
    avg = sum(rates) / len(rates)
    return round_half_up(avg * 100), judged_total


def compute_type_name(pillar_summary: dict) -> str:
    strong = [p["name"] for pid, p in pillar_summary.items() if p["rate"] is not None and p["rate"] >= STRONG_THRESHOLD]
    weak = [p["name"] for pid, p in pillar_summary.items() if p["rate"] is not None and p["rate"] < WEAK_THRESHOLD]
    judged_pillars = [pid for pid, p in pillar_summary.items() if p["rate"] is not None]

    if len(judged_pillars) == 4 and len(strong) == 4:
        return "全体が揃っている型"
    if len(judged_pillars) == 4 and len(weak) == 4:
        return "これから整える型"
    if strong and weak:
        return f"{'、'.join(strong)}は強く、{'、'.join(weak)}が薄い型"
    if strong and not weak:
        return f"{'、'.join(strong)}が強い型"
    if weak and not strong:
        return f"{'、'.join(weak)}が薄い型"
    return "全体がほどほどの型"


def compute_next_fixes(scored_items: list[dict], items_def_by_id: dict, limit: int = 3) -> list[dict]:
    failing = [s for s in scored_items if s["status"] == "fail"]

    def sort_key(s):
        pillar_rank = NEXT_FIX_PILLAR_ORDER.index(s["pillar"]) if s["pillar"] in NEXT_FIX_PILLAR_ORDER else 99
        return (pillar_rank, s["id"])

    failing.sort(key=sort_key)
    out = []
    for s in failing[:limit]:
        out.append(
            {
                "id": s["id"],
                "name": items_def_by_id[s["id"]]["name"],
                "pillar": s["pillar"],
                "fix_text": items_def_by_id[s["id"]].get("fix_text", items_def_by_id[s["id"]]["name"]),
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="ハーネス点検: facts.json → result.json")
    parser.add_argument("--out", default=os.environ.get("HARNESS_CHECK_OUT", "harness-check-output"))
    args = parser.parse_args()

    out_dir = Path(args.out).expanduser().resolve()
    facts_path = out_dir / "facts.json"
    ai_path = out_dir / "ai_judgments.json"
    items_path = Path(__file__).resolve().parent / "items.json"

    with facts_path.open("r", encoding="utf-8") as fh:
        facts = json.load(fh)
    with items_path.open("r", encoding="utf-8") as fh:
        items_def = json.load(fh)

    ai_judgments: dict = {}
    if ai_path.exists():
        with ai_path.open("r", encoding="utf-8") as fh:
            ai_judgments = json.load(fh)

    items_def_by_id = {it["id"]: it for it in items_def["items"]}
    pillars = facts["pillars"]
    pillar_order = facts["pillar_order"]

    scored_items = []
    for item_def in items_def["items"]:
        iid = item_def["id"]
        item_facts = facts["items"].get(iid, {})
        scored_items.append(score_item(item_def, item_facts, ai_judgments))

    pillar_summary = compute_pillar_summary(scored_items, pillars, pillar_order)
    score, judged_total = compute_score(pillar_summary)
    type_name = compute_type_name(pillar_summary)
    next_fixes = compute_next_fixes(scored_items, items_def_by_id)

    items_result = {}
    for s in scored_items:
        items_result[s["id"]] = {
            "name": items_def_by_id[s["id"]]["name"],
            "pillar": s["pillar"],
            "judge": s["judge"],
            "judge_label": s["judge_label"],
            "status": s["status"],
        }

    result = {
        "schema_version": facts["schema_version"],
        "score": score,
        "judged_item_count": judged_total,
        "total_item_count": len(items_def["items"]),
        "type_name": type_name,
        "pillars": pillar_summary,
        "pillar_order": pillar_order,
        "items": items_result,
        "next_fixes": next_fixes,
        "reference": facts.get("reference", {}),
        "tools_detected": facts.get("tools_detected", {}),
        "window_days": facts.get("window_days", 30),
    }

    result_path = out_dir / "result.json"
    with result_path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"result.json を書きました: {result_path}")
    print(f"点数: {score} / 判定できた項目: {judged_total}/{len(items_def['items'])}")
    print(f"型: {type_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
