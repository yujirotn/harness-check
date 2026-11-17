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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inventory as inventory_mod  # noqa: E402
import reasons  # noqa: E402

RESULT_SCHEMA_VERSION = 5
# facts.json の版。項目ごとの理由に使う数（件数・行数など）が入っているのは 3 から。
# 4 から、今月の使用量（usage_this_month）とスキル・エージェントの本数（tool_counts）が入る
SUPPORTED_FACTS_VERSIONS = (5,)


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


# F6・F9・F11（使われた形跡を回数で見る項目）が、回数をどの facts のキーから取るか。
USAGE_TIER_COUNT_KEY = {"F6": "use_total", "F9": "use_total", "F11": "calls_30d"}


def _usage_tier_for_count(boundaries: list[dict], count: int) -> dict:
    """items.json の usage_tier_boundaries から、回数に応じた段階を1つ選ぶ（境目は items.json 側）。

    戻り値は `count`・`credit_num`・`credit_den`・`label` の4キーだけ（docs/RESULT_SCHEMA.md の
    `items.<ID>.usage_tier` の形と完全に一致させる。差し戻し対応: 内部計算用の小数 `credit` は
    ここに持たせず、使う側（_finalize）で `credit_num/credit_den` から都度計算する）。
    """
    for b in boundaries:
        if b.get("max_count") is None or count <= b["max_count"]:
            return {"count": count, "credit_num": b["credit_num"], "credit_den": b["credit_den"], "label": b["label"]}
    last = boundaries[-1]
    return {"count": count, "credit_num": last["credit_num"], "credit_den": last["credit_den"], "label": last["label"]}


def _usage_tier_credit(usage_tier: dict) -> float:
    """usage_tier（公開用の4キーの形）から、点数計算用の部分点を計算する。"""
    den = usage_tier.get("credit_den") or 1
    return usage_tier.get("credit_num", 0) / den


def compute_usage_tier(item_def: dict, item_facts: dict, boundaries: list[dict] | None) -> dict | None:
    """F6・F9・F11 の段階評価。複数の道具が測れたときは、回数を道具間で合計してから段階を決める

    （5-2 の「あることを見る項目」の「どれかが満たせば」という発想を、回数の合算という形で
    引き継いだもの。SPEC 5-10 参照）。測れた道具が無ければ None（点数には使わない）。
    """
    if not item_def.get("usage_tiered") or not boundaries:
        return None
    count_key = USAGE_TIER_COUNT_KEY.get(item_def["id"])
    if not count_key:
        return None
    per_tool = item_facts.get("per_tool", {})
    total = 0
    any_measured = False
    for v in per_tool.values():
        if isinstance(v, dict) and v.get("measured"):
            any_measured = True
            total += int(v.get(count_key, 0) or 0)
    if not any_measured:
        return None
    return _usage_tier_for_count(boundaries, total)


def score_item(
    item_def: dict, item_facts: dict, ai_judgments: dict, usage_tier_boundaries: list[dict] | None = None
) -> dict:
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
    usage_tier = compute_usage_tier(item_def, item_facts, usage_tier_boundaries)
    return _finalize(iid, pillar, judge, merged["measured"], merged["pass"], tool_results, usage_tier)


def _finalize(iid, pillar, judge, measured, passed, per_tool_detail, usage_tier=None) -> dict:
    if not measured:
        status = "unmeasured"
    elif passed:
        status = "pass"
    else:
        status = "fail"
    # 柱の達成率（rate）に使う部分点。段階評価がある項目はその部分点、無い項目は○＝1／×＝0（5-10）。
    if not measured:
        credit = None
    elif usage_tier is not None:
        credit = _usage_tier_credit(usage_tier)
    else:
        credit = 1.0 if passed else 0.0
    return {
        "id": iid,
        "pillar": pillar,
        "judge": judge,
        "judge_label": JUDGE_LABELS[judge],
        "status": status,
        "per_tool": per_tool_detail,
        "usage_tier": usage_tier,
        "credit": credit,
    }


def round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def compute_pillar_summary(scored_items: list[dict], pillars: dict, pillar_order: list[str]) -> dict:
    """柱ごとの集計。

    `passed_count`（満たした数）は従来通り ○ の数。`rate`（達成率）は、段階評価のある項目
    （F6・F9・F11）では部分点（`credit`）を足して計算する（SPEC 5-10）。段階評価の無い項目は
    ○＝1／×＝0 なので、全項目が段階評価の無い柱では rate は passed_count/judged_count と一致する
    （後方互換）。
    """
    summary = {}
    for pid in pillar_order:
        items_in = [s for s in scored_items if s["pillar"] == pid]
        judged = [s for s in items_in if s["status"] != "unmeasured"]
        passed = [s for s in judged if s["status"] == "pass"]
        credit_sum = sum(s["credit"] for s in judged if s["credit"] is not None)
        rate = (credit_sum / len(judged)) if judged else None
        summary[pid] = {
            "name": pillars[pid],
            "judged_count": len(judged),
            "total_count": len(items_in),
            "passed_count": len(passed),
            "rate": rate,
            # v5。判定できた数が項目数の半分以上か（16-1）。偽の柱は点数・型の名前に使わない
            "sufficient": is_sufficient(len(judged), len(items_in)),
        }
    return summary


def is_sufficient(judged: int, total: int) -> bool:
    """判定できた数が、項目数の半分以上か（16-1）。"""
    return total > 0 and judged * 2 >= total


def _usable_rates(pillar_summary: dict) -> list:
    return [p["rate"] for p in pillar_summary.values() if p["rate"] is not None and p.get("sufficient", True)]


def compute_score(pillar_summary: dict) -> tuple[int | None, int]:
    rates = _usable_rates(pillar_summary)
    judged_total = sum(p["judged_count"] for p in pillar_summary.values())
    total = sum(p["total_count"] for p in pillar_summary.values())
    if not rates or not is_sufficient(judged_total, total):
        return None, judged_total
    avg = sum(rates) / len(rates)
    return round_half_up(avg * 100), judged_total


def compute_type_name(pillar_summary: dict) -> str | None:
    judged_total = sum(p["judged_count"] for p in pillar_summary.values())
    total = sum(p["total_count"] for p in pillar_summary.values())
    if not is_sufficient(judged_total, total):
        return None
    usable = {pid: p for pid, p in pillar_summary.items() if p["rate"] is not None and p.get("sufficient", True)}
    strong = [p["name"] for p in usable.values() if p["rate"] >= STRONG_THRESHOLD]
    weak = [p["name"] for p in usable.values() if p["rate"] < WEAK_THRESHOLD]
    judged_pillars = list(usable)

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
    if facts.get("schema_version") not in SUPPORTED_FACTS_VERSIONS:
        print(
            f"facts.json の版（{facts.get('schema_version')}）がこの score.py と合いません。"
            "collect.py からやり直してください。"
        )
        return 2
    with items_path.open("r", encoding="utf-8") as fh:
        items_def = json.load(fh)

    ai_judgments: dict = {}
    if ai_path.exists():
        with ai_path.open("r", encoding="utf-8") as fh:
            ai_judgments = json.load(fh)

    items_def_by_id = {it["id"]: it for it in items_def["items"]}
    pillars = facts["pillars"]
    pillar_order = facts["pillar_order"]
    usage_tier_boundaries = items_def.get("usage_tier_boundaries")

    scored_items = []
    for item_def in items_def["items"]:
        iid = item_def["id"]
        item_facts = facts["items"].get(iid, {})
        scored_items.append(score_item(item_def, item_facts, ai_judgments, usage_tier_boundaries))

    pillar_summary = compute_pillar_summary(scored_items, pillars, pillar_order)
    score, judged_total = compute_score(pillar_summary)
    type_name = compute_type_name(pillar_summary)
    next_fixes = compute_next_fixes(scored_items, items_def_by_id)

    items_result = {}
    replaced = 0
    for s in scored_items:
        iid = s["id"]
        # 理由は決まった文の型だけで作る。ai_judgments.json の中の文（AIが書いた理由など）は使わない
        reason, reason_facts, was_replaced = reasons.build_reason_checked(
            items_def_by_id[iid], facts["items"].get(iid, {}), s, ai_judgments
        )
        replaced += int(was_replaced)
        items_result[iid] = {
            "name": items_def_by_id[iid]["name"],
            "pillar": s["pillar"],
            "judge": s["judge"],
            "judge_label": s["judge_label"],
            "status": s["status"],
            "reason": reason,
            "facts": reason_facts,
            # v4。段階評価のある項目（F6・F9・F11）だけ値を持つ。無い項目は null（5-10）
            "usage_tier": s["usage_tier"],
        }

    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "score": score,
        # v5。判定できた数が少なく、点数と型の名前を出さなかったとき真（16-1）
        "score_withheld": score is None,
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
        # v4。今月の使用量（時間・トークン）とスキル・エージェントの本数（道具ごと）。5-10
        "usage_this_month": facts.get("usage_this_month", {}),
        "tool_counts": facts.get("tool_counts", {}),
        # v5。表紙のダッシュボード（16-3）。会話の記録が無ければ null
        "daily_30d": facts.get("daily_30d"),
        "usage_breadth": facts.get("usage_breadth"),
        "autonomy": facts.get("autonomy"),
    }

    # 説明の一覧（5-9）。名前の一覧は手元用の ai_targets.json にだけある。読めなければ説明は全部置き換える
    needles = None
    targets_path = out_dir / "ai_targets.json"
    if targets_path.exists():
        with targets_path.open("r", encoding="utf-8") as fh:
            inv_targets = (json.load(fh) or {}).get("INVENTORY") or {}
        names = list(inv_targets.get("other_names") or [])
        for kind in inventory_mod.KINDS:
            names += [str(v.get("name", "")) for v in (inv_targets.get(kind) or {}).values() if isinstance(v, dict)]
        needles = inventory_mod.name_needles(names)
    inv, inv_truncated, inv_replaced = inventory_mod.build_inventory(
        facts.get("inventory"), ai_judgments.get("INVENTORY"), needles
    )
    result["inventory"] = inv
    result["reference"] = dict(result["reference"], inventory_truncated=inv_truncated,
                               inventory_summaries_replaced=inv_replaced)

    result_path = out_dir / "result.json"
    with result_path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"result.json を書きました: {result_path}")
    if score is None:
        print(f"点数: 出していません（判定できた項目が少ないため: {judged_total}/{len(items_def['items'])}）")
    else:
        print(f"点数: {score} / 判定できた項目: {judged_total}/{len(items_def['items'])}")
        print(f"型: {type_name}")
    if replaced:
        print(f"注意: 理由の文 {replaced} 件が検査に通らず、定型文に置き換えました（文の型の不具合です）。")
    total_inv = sum(len(v) for v in inv.values())
    n_rep = sum(inv_replaced.values())
    if total_inv:
        print(f"説明の一覧: {total_inv}件（うち {n_rep} 件は「{inventory_mod.FALLBACK_SUMMARY}」に置き換え）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
