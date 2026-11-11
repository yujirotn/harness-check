#!/usr/bin/env python3
"""ハーネス点検 — 事実を集めて facts.json を出す。

読むだけ・通信なし。書き込みは --out で指定した出力フォルダの中だけ。
標準ライブラリだけで動く（Python 3.9 以上）。

使い方:
    python3 collect.py --workdir . --out ./harness-check-output
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from readers import common  # noqa: E402
from readers import claude_code  # noqa: E402
from readers import codex  # noqa: E402


SCHEMA_VERSION = 2
RECENT_DAYS = 30


def detect_claude_code(workdir: Path, claude_home: Path) -> bool:
    if not claude_home.is_dir():
        return False
    if (claude_home / "settings.json").exists():
        return True
    projects = claude_home / "projects"
    if projects.is_dir():
        try:
            for proj_dir in projects.iterdir():
                if any(proj_dir.glob("*.jsonl")):
                    return True
        except OSError:
            pass
    for d in common.walk_up_to_git_root(workdir):
        if (d / "CLAUDE.md").exists() or (d / ".claude" / "CLAUDE.md").exists():
            return True
    return False


def detect_codex(workdir: Path, codex_home: Path) -> bool:
    if not codex_home.is_dir():
        return False
    if (codex_home / "config.toml").exists():
        return True
    for d in common.walk_up_to_git_root(workdir):
        if (d / "AGENTS.md").exists():
            return True
    return False


def _scan_repo_for_secrets(git_root: Path) -> dict:
    """作業フォルダのGit管理下のテキストを走査する（5-5。リンクはたどらない）。"""
    counts: dict[str, int] = {}
    scanned = 0
    skipped = 0

    tracked = common.git_ls_files_z(git_root)
    for rel in tracked:
        p = git_root / rel
        if p.is_symlink():
            continue
        try:
            if not p.is_file():
                continue
            size = p.stat().st_size
        except OSError:
            skipped += 1
            continue
        if size > common.MAX_SCAN_FILE_BYTES:
            skipped += 1
            continue
        text = common.read_text_capped(p)
        if text is None:
            skipped += 1
            continue
        scanned += 1
        counts = common.merge_counts(counts, common.scan_text_for_secrets(text))

    return {
        "counts_by_kind": counts,
        "scanned_file_count": scanned,
        "skipped_file_count": skipped,
    }


def _scan_config_files_for_secrets(config_files: list[Path]) -> dict:
    """道具の設定ファイルを走査する（キーの形＋名前でわかる秘密。5-5）。リンクはたどらない。"""
    counts: dict[str, int] = {}
    scanned = 0
    skipped = 0
    for p in config_files:
        if p.is_symlink():
            continue
        text = common.read_text_capped(p, max_bytes=5 * 1024 * 1024)
        if text is None:
            skipped += 1
            continue
        scanned += 1
        counts = common.merge_counts(
            counts,
            common.scan_text_for_secrets(text),
            common.scan_text_for_named_secrets(text),
        )
    return {
        "counts_by_kind": counts,
        "scanned_file_count": scanned,
        "skipped_file_count": skipped,
    }


def compute_s1(workdir: Path, claude_home: Path, codex_home: Path) -> dict:
    """よくある形のキーの走査（5-5）。リポジトリと設定ファイルを分けて数える。"""
    git_root = common.find_git_root(workdir)
    if git_root is not None:
        repo_result = _scan_repo_for_secrets(git_root)
    else:
        repo_result = {"counts_by_kind": {}, "scanned_file_count": 0, "skipped_file_count": 0}

    config_files = claude_code.config_files_for_secret_scan(workdir, claude_home)
    config_files += codex.config_files_for_secret_scan(codex_home)
    config_result = _scan_config_files_for_secrets(config_files)

    total = sum(repo_result["counts_by_kind"].values()) + sum(config_result["counts_by_kind"].values())
    return {
        "measured": True,
        "pass": total == 0,
        "repo": repo_result,
        "config": config_result,
    }


def compute_g1(workdir: Path, cc_facts: dict, codex_facts: dict) -> dict:
    git_root = common.find_git_root(workdir)
    if git_root is None:
        return {"measured": True, "pass": False, "reason": "not_a_git_repo"}

    has_remote = common.git_has_remote(git_root)

    tracked = set(common.git_ls_files_z(git_root))

    instruction_tracked = False
    for d in common.walk_up_to_git_root(workdir):
        for name in ("CLAUDE.md", "AGENTS.md"):
            p = d / name
            if p.exists():
                try:
                    rel = p.resolve().relative_to(git_root.resolve())
                except ValueError:
                    continue
                if str(rel) in tracked:
                    instruction_tracked = True
        p2 = d / ".claude" / "CLAUDE.md"
        if p2.exists():
            try:
                rel2 = p2.resolve().relative_to(git_root.resolve())
            except ValueError:
                rel2 = None
            if rel2 is not None and str(rel2) in tracked:
                instruction_tracked = True

    return {
        "measured": True,
        "pass": has_remote and instruction_tracked,
        "has_remote": has_remote,
        "instruction_tracked": instruction_tracked,
    }


def compute_g2(cc_facts: dict, codex_facts: dict) -> dict:
    global_has_content = cc_facts.get("_global_instruction_has_content") or codex_facts.get(
        "_global_instruction_has_content"
    )
    local_has_content = cc_facts.get("_local_instruction_has_content") or codex_facts.get(
        "_local_instruction_has_content"
    )
    has_override = cc_facts.get("_has_local_override") or False
    passed = bool((global_has_content and local_has_content) or has_override)
    measured = bool(
        cc_facts.get("_global_instruction_has_content") is not None
        or codex_facts.get("_global_instruction_has_content") is not None
    )
    return {"measured": True if measured else False, "pass": passed}


def compute_g3(cc_facts: dict, codex_facts: dict) -> dict:
    candidate_found = bool(
        cc_facts.get("_has_stop_hook")
        or cc_facts.get("_has_scheduled_defs")
        or codex_facts.get("_has_stop_hook")
        or codex_facts.get("_has_scheduled_defs")
    )
    return {
        "measured": candidate_found,
        "pass": None,  # AI が確認するまで確定しない
        "needs_ai_confirmation": candidate_found,
    }


def build_items(
    workdir: Path,
    cc_detected: bool,
    codex_detected: bool,
    cc_facts: dict,
    codex_facts: dict,
    items_def: dict,
    s1: dict,
    g1: dict,
    g2: dict,
    g3: dict,
) -> dict:
    per_tool_item_ids = {
        "F1",
        "F2",
        "F5",
        "F6",
        "F8",
        "F9",
        "F10",
        "F11",
        "S2",
        "S3",
        "S4",
        "D1",
        "D2",
        "D3",
        "D4",
        "D5",
    }
    ai_item_ids = {"F3", "F4", "F7"}
    combined_item_ids = {"S1": s1, "G1": g1, "G2": g2, "G3": g3}

    items_out: dict = {}
    for item in items_def["items"]:
        iid = item["id"]
        judge = item["judge"]
        entry: dict = {"judge": judge}
        if "ai_question" in item:
            entry["ai_question"] = item["ai_question"]
        if "user_question" in item:
            entry["user_question"] = item["user_question"]

        if iid in combined_item_ids:
            entry["combined"] = combined_item_ids[iid]
            if iid == "G3":
                entry["needs_ai"] = combined_item_ids[iid].get("needs_ai_confirmation", False)
            items_out[iid] = entry
            continue

        if iid in per_tool_item_ids:
            per_tool = {}
            if cc_detected and iid in cc_facts:
                per_tool["claude_code"] = cc_facts[iid]
            if codex_detected and iid in codex_facts:
                per_tool["codex"] = codex_facts[iid]
            entry["per_tool"] = per_tool
            if iid == "D2":
                entry["needs_user"] = any(
                    v.get("needs_user_fallback") for v in per_tool.values() if isinstance(v, dict)
                )
            if iid == "D3":
                entry["needs_ai"] = any(
                    v.get("needs_ai_fallback") for v in per_tool.values() if isinstance(v, dict)
                )
            items_out[iid] = entry
            continue

        if iid in ai_item_ids:
            # 注意: 名前（スキル名等）は facts.json には入れない（原則8）。
            # AIが読むべき実ファイルは ai_targets.json の側に別途書き出す。
            per_tool_targets = {}
            if cc_detected:
                per_tool_targets["claude_code"] = {
                    "target_found": bool(cc_facts.get(f"{iid}_target_found"))
                    if iid != "F7"
                    else bool(cc_facts.get("F7_candidates"))
                }
            if codex_detected:
                per_tool_targets["codex"] = {
                    "target_found": bool(codex_facts.get(f"{iid}_target_found"))
                    if iid != "F7"
                    else bool(codex_facts.get("F7_candidates"))
                }
            entry["per_tool"] = per_tool_targets
            entry["needs_ai"] = any(v.get("target_found") for v in per_tool_targets.values())
            items_out[iid] = entry
            continue

    return items_out


def build_reference(cc_facts: dict, codex_facts: dict, s1: dict, show_names: bool) -> dict:
    skill_counts = cc_facts.get("_skill_use_counts", {})
    agent_counts = cc_facts.get("_agent_use_counts", {})
    connector_counts = cc_facts.get("_connector_use_counts", {})

    reference = {
        "names_included": show_names,
        "skills": {
            "own_count": _safe_get(cc_facts, "F5", "count", default=0),
            "used_recent_count": _safe_get(cc_facts, "F6", "count", default=0),
            "usage_counts": sorted(skill_counts.values(), reverse=True),
        },
        "agents": {
            "own_count": _safe_get(cc_facts, "F8", "count", default=0),
            "used_recent_count": _safe_get(cc_facts, "F9", "count", default=0),
            "usage_counts": sorted(agent_counts.values(), reverse=True),
        },
        "connectors": {
            "count": len(connector_counts),
            "calls_30d": sum(connector_counts.values()),
        },
        "max_consecutive_tool_calls": {
            "claude_code": _safe_get(cc_facts, "D5", "max_consecutive", default=0),
        },
        "startup_instructions": {
            "claude_code_total_lines": _safe_get(cc_facts, "F2", "total_lines", default=0),
            "claude_code_file_count": _safe_get(cc_facts, "F2", "file_count", default=0),
            "codex_total_bytes": _safe_get(codex_facts, "F2", "total_bytes", default=0),
            "codex_file_count": _safe_get(codex_facts, "F2", "file_count", default=0),
        },
        "secret_scan": {
            "repo": s1.get("repo", {}),
            "config": s1.get("config", {}),
        },
    }
    if show_names:
        reference["named"] = {
            "skills": skill_counts,
            "agents": agent_counts,
            "connectors": connector_counts,
        }
    return reference


def _safe_get(d: dict, key: str, subkey: str, default=0):
    v = d.get(key)
    if isinstance(v, dict):
        return v.get(subkey, default)
    return default


def build_ai_targets(
    workdir: Path,
    claude_home: Path,
    codex_home: Path,
    home: Path,
    cc_detected: bool,
    codex_detected: bool,
    items_out: dict,
    cc_facts: dict,
    codex_facts: dict,
) -> dict:
    """AIが読むべきファイルの一覧（5-6）。手元用。result.json にも facts.json にも入れない。"""
    targets: dict = {}

    def as_str_list(paths) -> list[str]:
        return [str(p) for p in paths]

    if items_out.get("F3", {}).get("needs_ai"):
        t = {}
        if cc_detected:
            t["claude_code"] = as_str_list(claude_code.local_instruction_files(workdir))
        if codex_detected:
            t["codex"] = as_str_list(codex.local_instruction_files(workdir))
        targets["F3"] = t

    if items_out.get("F4", {}).get("needs_ai"):
        t = {}
        if cc_detected:
            t["claude_code"] = as_str_list(claude_code.startup_files(workdir, claude_home))
        if codex_detected:
            t["codex"] = as_str_list(codex.startup_files(workdir))
        targets["F4"] = t

    if items_out.get("F7", {}).get("needs_ai"):
        t = {}
        if cc_detected:
            names = set(cc_facts.get("F7_candidates", []))
            t["claude_code"] = as_str_list(
                p / "SKILL.md" for p in claude_code.own_skill_dirs(workdir, claude_home) if p.name in names
            )
        if codex_detected:
            names = set(codex_facts.get("F7_candidates", []))
            t["codex"] = as_str_list(
                p / "SKILL.md" for p in codex.own_skill_dirs(workdir, home) if p.name in names
            )
        targets["F7"] = t

    if items_out.get("G3", {}).get("needs_ai"):
        t = {"combined": []}
        if cc_detected:
            t["combined"].extend(as_str_list(claude_code.settings_files(workdir, claude_home)))
            t["combined"].extend(as_str_list(claude_code.scheduled_task_dirs(claude_home)))
        if codex_detected:
            t["combined"].append(str(codex_home / "hooks.json"))
            t["combined"].extend(as_str_list(codex.automations_dirs(codex_home)))
        targets["G3"] = t

    if items_out.get("D3", {}).get("needs_ai"):
        t = {}
        if cc_detected and items_out["D3"]["per_tool"].get("claude_code", {}).get("needs_ai_fallback"):
            t["claude_code"] = as_str_list(claude_code.local_instruction_files(workdir))
        if codex_detected and items_out["D3"]["per_tool"].get("codex", {}).get("needs_ai_fallback"):
            t["codex"] = as_str_list(codex.local_instruction_files(workdir))
        targets["D3"] = t

    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description="ハーネス点検: 事実を集めて facts.json を出す")
    parser.add_argument("--workdir", default=os.environ.get("HARNESS_CHECK_WORKDIR", "."))
    parser.add_argument("--out", default=os.environ.get("HARNESS_CHECK_OUT", "harness-check-output"))
    parser.add_argument(
        "--claude-home",
        default=os.environ.get("HARNESS_CHECK_CLAUDE_HOME", str(Path.home() / ".claude")),
    )
    parser.add_argument(
        "--codex-home",
        default=os.environ.get("HARNESS_CHECK_CODEX_HOME", str(Path.home() / ".codex")),
    )
    parser.add_argument(
        "--home",
        default=os.environ.get("HARNESS_CHECK_HOME", str(Path.home())),
    )
    parser.add_argument(
        "--now",
        default=os.environ.get("HARNESS_CHECK_NOW"),
        help="30日判定の基準時刻（ISO8601）。テスト用。省略時は現在時刻。",
    )
    parser.add_argument(
        "--show-names",
        action="store_true",
        help="スキル・エージェント・コネクタの名前をレポートに出す（既定では出さない）。",
    )
    args = parser.parse_args()

    workdir = Path(args.workdir).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    claude_home = Path(args.claude_home).expanduser().resolve()
    codex_home = Path(args.codex_home).expanduser().resolve()
    home = Path(args.home).expanduser().resolve()

    if args.now:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)

    out_dir.mkdir(parents=True, exist_ok=True)

    cc_detected = detect_claude_code(workdir, claude_home)
    codex_detected = detect_codex(workdir, codex_home)

    cc_facts = claude_code.collect_facts(workdir, claude_home, now=now) if cc_detected else {}
    codex_facts = codex.collect_facts(workdir, codex_home, home, now=now) if codex_detected else {}

    s1 = compute_s1(workdir, claude_home, codex_home)
    g1 = compute_g1(workdir, cc_facts, codex_facts)
    g2 = compute_g2(cc_facts, codex_facts)
    g3 = compute_g3(cc_facts, codex_facts)

    items_path = Path(__file__).resolve().parent / "items.json"
    with items_path.open("r", encoding="utf-8") as fh:
        items_def = json.load(fh)

    items_out = build_items(
        workdir, cc_detected, codex_detected, cc_facts, codex_facts, items_def, s1, g1, g2, g3
    )
    reference = build_reference(cc_facts, codex_facts, s1, show_names=args.show_names)

    facts = {
        "schema_version": SCHEMA_VERSION,
        "window_days": RECENT_DAYS,
        "tools_detected": {"claude_code": cc_detected, "codex": codex_detected},
        "pillars": items_def["pillars"],
        "pillar_order": items_def["pillar_order"],
        "items": items_out,
        "reference": reference,
    }

    ai_targets = build_ai_targets(
        workdir, claude_home, codex_home, home, cc_detected, codex_detected, items_out, cc_facts, codex_facts
    )
    ai_targets_path = out_dir / "ai_targets.json"
    with ai_targets_path.open("w", encoding="utf-8") as fh:
        json.dump(ai_targets, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    facts_path = out_dir / "facts.json"
    with facts_path.open("w", encoding="utf-8") as fh:
        json.dump(facts, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"facts.json を書きました: {facts_path}")
    print(f"検出した道具: Claude Code={cc_detected} / Codex={codex_detected}")
    needs_ai = [iid for iid, v in items_out.items() if v.get("needs_ai")]
    needs_user = [iid for iid, v in items_out.items() if v.get("needs_user")]
    if needs_ai:
        print(f"AIの判断が必要な項目: {', '.join(sorted(needs_ai))}")
    if needs_user:
        print(f"本人への確認が必要な項目: {', '.join(sorted(needs_user))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
