"""Codex 用の読み取り部品。読むだけ・通信なし。

Codex の会話の記録は圧縮されていて標準機能で読めないため、使用実績が要る項目
（F6・F9・F11・D4・D5）と S2 は「測定できず」として扱う（SPEC 10章）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import common


MAX_STARTUP_BYTES = 32 * 1024
RECENT_DAYS = 30


def global_instruction_file(codex_home: Path) -> Optional[Path]:
    p = codex_home / "AGENTS.md"
    return p if p.exists() and p.is_file() else None


def local_instruction_files(workdir: Path) -> list[Path]:
    """作業フォルダから Git ルートまでの各階層で AGENTS.md を探す（公式の歩き方）。"""
    found: list[Path] = []
    for d in common.walk_up_to_git_root(workdir):
        p = d / "AGENTS.md"
        if p.exists() and p.is_file():
            found.append(p)
    return found


def startup_files(workdir: Path) -> list[Path]:
    return local_instruction_files(workdir)


def own_skill_dirs(workdir: Path, home: Path) -> list[Path]:
    out: list[Path] = []
    for base in (home / ".agents" / "skills", workdir / ".agents" / "skills"):
        if not base.is_dir():
            continue
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                out.append(entry)
    return out


def own_agent_files(workdir: Path, codex_home: Path) -> list[Path]:
    out: list[Path] = []
    for base in (codex_home / "agents", workdir / ".codex" / "agents"):
        if not base.is_dir():
            continue
        try:
            out.extend(sorted(base.glob("*.md")))
        except OSError:
            continue
    return out


def config_toml_text(codex_home: Path) -> Optional[str]:
    return common.read_text_capped(codex_home / "config.toml", max_bytes=5 * 1024 * 1024)


def mcp_servers_present(codex_home: Path) -> bool:
    text = config_toml_text(codex_home)
    if text is None:
        return False
    return common.toml_has_table(text, "mcp_servers")


def _approval_and_sandbox(codex_home: Path) -> dict:
    text = config_toml_text(codex_home)
    if text is None:
        return {"approval_policy": None, "sandbox_mode": None}
    scalars = common.toml_top_level_scalars(text)
    return {
        "approval_policy": scalars.get("approval_policy"),
        "sandbox_mode": scalars.get("sandbox_mode"),
    }


def hooks_json_has_stop(codex_home: Path, workdir: Path) -> Optional[bool]:
    import json

    for base in (codex_home, workdir / ".codex"):
        p = base / "hooks.json"
        text = common.read_text_capped(p, max_bytes=2 * 1024 * 1024)
        if text is None:
            continue
        low = text.lower()
        if '"stop"' in low or '"session_end"' in low or '"subagent_stop"' in low:
            return True
        try:
            json.loads(text)
            return False
        except Exception:
            continue
    return None


def automations_dirs(codex_home: Path) -> list[Path]:
    base = codex_home / "automations"
    if not base.is_dir():
        return []
    try:
        return [p for p in base.iterdir()]
    except OSError:
        return []


def config_files_for_secret_scan(codex_home: Path) -> list[Path]:
    files = []
    p = codex_home / "config.toml"
    if p.exists():
        files.append(p)
    return files


def collect_facts(workdir: Path, codex_home: Path, home: Path, now=None) -> dict:
    facts: dict = {}

    local_files = local_instruction_files(workdir)
    facts["F1"] = {"measured": True, "pass": len(local_files) > 0}

    startup = startup_files(workdir)
    total_bytes = sum((f.stat().st_size for f in startup if f.exists()), 0)
    facts["F2"] = {
        "measured": len(startup) > 0,
        "pass": total_bytes < MAX_STARTUP_BYTES if startup else None,
        "total_bytes": total_bytes,
        "file_count": len(startup),
    }

    facts["F3_target_found"] = len(local_files) > 0
    facts["F4_target_found"] = len(startup) > 0

    skills = own_skill_dirs(workdir, home)
    facts["F5"] = {"measured": True, "pass": len(skills) > 0, "count": len(skills)}
    ranked_by_mtime = sorted(skills, key=lambda p: _mtime_of(p), reverse=True)
    facts["F7_candidates"] = [p.name for p in ranked_by_mtime[:5]]

    agents = own_agent_files(workdir, codex_home)
    facts["F8"] = {"measured": True, "pass": len(agents) > 0, "count": len(agents)}

    facts["F6"] = {"measured": False, "pass": None}
    facts["F9"] = {"measured": False, "pass": None}

    mcp_present = mcp_servers_present(codex_home)
    facts["F10"] = {"measured": True, "pass": mcp_present}
    facts["F11"] = {"measured": False, "pass": None}

    facts["D4"] = {"measured": False, "pass": None}
    facts["D5"] = {"measured": False, "pass": None}

    facts["S2"] = {"measured": False, "pass": None}

    approval = _approval_and_sandbox(codex_home)
    policy = approval["approval_policy"]
    sandbox = approval["sandbox_mode"]
    has_approval_signal = policy is not None or sandbox is not None

    is_full_access = (sandbox or "").strip().lower() == "danger-full-access"
    is_never_ask = (policy or "").strip().lower() == "never"
    is_always_ask = (policy or "").strip().lower() == "untrusted"

    facts["S3"] = {
        "measured": has_approval_signal,
        "pass": (not is_never_ask) and (not is_full_access) if has_approval_signal else None,
    }
    facts["S4"] = {
        "measured": has_approval_signal,
        "pass": not (is_never_ask and is_full_access) if has_approval_signal else None,
    }
    facts["D1"] = {
        "measured": has_approval_signal,
        "pass": not is_always_ask if has_approval_signal else None,
    }

    stop_hook = hooks_json_has_stop(codex_home, workdir)
    facts["D3"] = {
        "measured": stop_hook is not None,
        "pass": bool(stop_hook) if stop_hook is not None else None,
        "needs_ai_fallback": stop_hook is not True,
    }

    autos = automations_dirs(codex_home)
    sched_recent = common.any_file_mtime_within_days(
        [p for d in autos for p in _safe_rglob(d)], RECENT_DAYS, now=now
    )
    facts["D2"] = {
        "measured": len(autos) > 0 and sched_recent,
        "pass": True if (autos and sched_recent) else None,
        "needs_user_fallback": len(autos) > 0 and not sched_recent,
        "definition_count": len(autos),
    }

    facts["_global_instruction_has_content"] = bool(
        global_instruction_file(codex_home)
        and (common.read_text_capped(global_instruction_file(codex_home)) or "").strip()
    )
    facts["_local_instruction_has_content"] = any(
        (common.read_text_capped(f) or "").strip() for f in local_files
    )
    facts["_has_stop_hook"] = bool(stop_hook)
    facts["_has_scheduled_defs"] = len(autos) > 0

    return facts


def _mtime_of(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _safe_rglob(d: Path):
    try:
        return list(d.rglob("*"))
    except OSError:
        return []
