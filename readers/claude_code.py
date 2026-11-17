"""Claude Code 用の読み取り部品。読むだけ・通信なし。

集めるのは「ある／ない」「件数」「直近30日に動いたか」などの事実だけ。
本文・フォルダ名・秘密の値は、この中でも外に持ち出さない（facts.json に積まない）。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from . import common


MAX_STARTUP_LINES = 200
RECENT_DAYS = 30
CONSECUTIVE_THRESHOLD = 20


def global_instruction_file(claude_home: Path) -> Optional[Path]:
    p = claude_home / "CLAUDE.md"
    return p if p.exists() and p.is_file() else None


def global_instruction_local_override(claude_home: Path) -> Optional[Path]:
    p = claude_home / "CLAUDE.local.md"
    return p if p.exists() and p.is_file() else None


def local_instruction_files(workdir: Path) -> list[Path]:
    """作業フォルダから Git ルートまでの各階層で CLAUDE.md / .claude/CLAUDE.md を探す。"""
    found: list[Path] = []
    for d in common.walk_up_to_git_root(workdir):
        for candidate in (d / "CLAUDE.md", d / ".claude" / "CLAUDE.md"):
            if candidate.exists() and candidate.is_file():
                found.append(candidate)
    return found


def local_instruction_local_override(workdir: Path) -> list[Path]:
    found = []
    for d in common.walk_up_to_git_root(workdir):
        p = d / "CLAUDE.local.md"
        if p.exists() and p.is_file():
            found.append(p)
    return found


def _rules_files_in_dir(rules_dir: Path) -> list[Path]:
    """paths frontmatter の無い rules/*.md（常に読まれるもの）を1フォルダ分集める。

    rules_dir がリンクでも、リンク先を読む（glob はリンクを素通りする）。
    """
    out: list[Path] = []
    if not rules_dir.is_dir():
        return out
    for f in sorted(rules_dir.glob("*.md")):
        text = common.read_text_capped(f)
        if text is None:
            continue
        if common.has_frontmatter_paths(text):
            continue
        out.append(f)
    return out


def _rules_files(workdir: Path) -> list[Path]:
    """作業フォルダ用の .claude/rules/*.md（paths 指定の無いもの）を集める。"""
    out: list[Path] = []
    for d in common.walk_up_to_git_root(workdir):
        out.extend(_rules_files_in_dir(d / ".claude" / "rules"))
    return out


def _global_rules_files(claude_home: Path) -> list[Path]:
    """全体用の ~/.claude/rules/*.md（paths 指定の無いもの）を集める（F2・F4 の対象）。"""
    return _rules_files_in_dir(claude_home / "rules")


def _at_imports(files: list[Path]) -> list[Path]:
    """CLAUDE.md 内の `@path` 形式の読み込み指定を1階層だけ解決する。"""
    out: list[Path] = []
    for f in files:
        text = common.read_text_capped(f)
        if text is None:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("@"):
                continue
            rel = line[1:].strip()
            if not rel:
                continue
            candidate = (f.parent / rel).resolve()
            if candidate.exists() and candidate.is_file():
                out.append(candidate)
    return out


def startup_files(workdir: Path, claude_home: Path) -> list[Path]:
    """起動時に読まれる指示ファイル一式（F2・F4 の対象）。重複は除く。"""
    files: list[Path] = []
    g = global_instruction_file(claude_home)
    if g:
        files.append(g)
    files.extend(global_instruction_local_override(claude_home) and [global_instruction_local_override(claude_home)] or [])
    files.extend(local_instruction_files(workdir))
    files.extend(local_instruction_local_override(workdir))
    files.extend(_rules_files(workdir))
    files.extend(_global_rules_files(claude_home))
    files.extend(_at_imports(files))
    seen = set()
    uniq: list[Path] = []
    for f in files:
        rp = f.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        uniq.append(f)
    return uniq


def own_skill_dirs(workdir: Path, claude_home: Path) -> list[Path]:
    """自分で用意したスキル（プラグイン同梱を除く）のディレクトリ一覧。"""
    out: list[Path] = []
    for base in (claude_home / "skills", workdir / ".claude" / "skills"):
        if not base.is_dir():
            continue
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            if (entry / "SKILL.md").is_file():
                out.append(entry)
    return out


def own_agent_files(workdir: Path, claude_home: Path) -> list[Path]:
    out: list[Path] = []
    for base in (claude_home / "agents", workdir / ".claude" / "agents"):
        if not base.is_dir():
            continue
        try:
            entries = sorted(base.glob("*.md"))
        except OSError:
            continue
        out.extend(entries)
    return out


def mcp_config_present(workdir: Path, claude_home: Path) -> bool:
    return mcp_server_count(workdir, claude_home) > 0


def mcp_server_count(workdir: Path, claude_home: Path) -> int:
    """設定に書かれた外部接続（MCPサーバー）の数。"""
    return len(mcp_server_names(workdir, claude_home))


def mcp_server_names(workdir: Path, claude_home: Path) -> list[str]:
    """設定に書かれた外部接続（MCPサーバー）の名前。--show-names のときだけ外に出す。"""
    names: set[str] = set()
    candidates = [claude_home / ".mcp.json"]
    for d in common.walk_up_to_git_root(workdir):
        candidates.append(d / ".mcp.json")
    for c in candidates:
        text = common.read_text_capped(c, max_bytes=5 * 1024 * 1024)
        if text is None:
            continue
        try:
            import json

            data = json.loads(text)
        except Exception:
            continue
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        if isinstance(servers, dict):
            names |= {str(k) for k in servers}
    return sorted(names)


def _load_settings_json(path: Path) -> Optional[dict]:
    text = common.read_text_capped(path, max_bytes=5 * 1024 * 1024)
    if text is None:
        return None
    try:
        import json

        data = json.loads(text)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def settings_files(workdir: Path, claude_home: Path) -> list[Path]:
    candidates = [claude_home / "settings.json", claude_home / "settings.local.json"]
    for d in common.walk_up_to_git_root(workdir):
        candidates.append(d / ".claude" / "settings.json")
        candidates.append(d / ".claude" / "settings.local.json")
    return [c for c in candidates if c.exists()]


def _merged_permissions(workdir: Path, claude_home: Path) -> dict:
    allow: list[str] = []
    deny: list[str] = []
    ask: list[str] = []
    default_mode: Optional[str] = None
    hooks: dict = {}
    pre_tool_commands: list[str] = []
    for f in settings_files(workdir, claude_home):
        data = _load_settings_json(f)
        if not data:
            continue
        perms = data.get("permissions")
        if isinstance(perms, dict):
            allow.extend(x for x in perms.get("allow", []) if isinstance(x, str))
            deny.extend(x for x in perms.get("deny", []) if isinstance(x, str))
            ask.extend(x for x in perms.get("ask", []) if isinstance(x, str))
            if isinstance(perms.get("defaultMode"), str):
                default_mode = perms["defaultMode"]
        h = data.get("hooks")
        if isinstance(h, dict):
            for k, v in h.items():
                hooks[k] = hooks.get(k, 0) + (len(v) if isinstance(v, list) else 1)
            pre_tool_commands.extend(_hook_commands(h.get("PreToolUse")))
    return {
        "allow": allow,
        "deny": deny,
        "ask": ask,
        "default_mode": default_mode,
        "hooks": hooks,
        "pre_tool_commands": pre_tool_commands,
    }


def _hook_commands(entries) -> list[str]:
    """hooks.PreToolUse の命令の文字列を集める（実行はしない。16-2）。"""
    out: list[str] = []
    if not isinstance(entries, list):
        return out
    for e in entries:
        if not isinstance(e, dict):
            continue
        for h in e.get("hooks") or []:
            if isinstance(h, dict) and isinstance(h.get("command"), str):
                out.append(h["command"])
    return out


def _hook_texts(commands: list[str], workdir: Path) -> list[str]:
    """フックの命令の文字列と、命令が指している実在のファイルの中身（16-2）。

    ファイルは読むだけ。`~`・`$HOME`・`$CLAUDE_PROJECT_DIR` を展開して、実在するものだけを読む。
    中身は系統の語を探すのにだけ使い、外には出さない。
    """
    import os
    import shlex

    project_dir = common.find_git_root(workdir) or workdir
    home = str(Path.home())
    texts: list[str] = []
    for cmd in commands:
        texts.append(cmd)
        expanded = (
            cmd.replace("${CLAUDE_PROJECT_DIR}", str(project_dir))
            .replace("$CLAUDE_PROJECT_DIR", str(project_dir))
            .replace("${HOME}", home)
            .replace("$HOME", home)
        )
        try:
            tokens = shlex.split(expanded)
        except ValueError:
            tokens = expanded.split()
        for tok in tokens:
            tok = tok.strip("\"'")
            if not tok or len(tok) > 1024:
                continue
            cand = Path(os.path.expanduser(tok))
            try:
                if cand.is_absolute() and cand.is_file():
                    t = common.read_text_capped(cand, max_bytes=1024 * 1024)
                    if t:
                        texts.append(t)
            except OSError:
                continue
    return texts


import re as _re

SECRET_CATEGORIES = common.SECRET_CATEGORIES

# S3 の系統（16-2）。正規表現（小文字の文字列に当てる）
DESTRUCTIVE_CATEGORIES: dict[str, tuple] = {
    "delete": (r"(?<![a-z0-9_-])rm(?![a-z0-9_])", r"\brmdir\b", r"\bunlink\b", r"git clean", r"\bdelete\b"),
    "force": (r"--force", r"push -f\b", r"reset --hard", r"--hard\b", r"git push"),
    "outward": (
        r"git push", r"\bpublish\b", r"\bdeploy\b", r"\bcurl\b", r"\bwget\b", r"\bscp\b",
        r"\brsync\b", r"gh pr\b", r"gh release\b", r"\bvercel\b",
    ),
}
DESTRUCTIVE_CATEGORY_ORDER = ("delete", "force", "outward")
SECRET_CATEGORY_ORDER = common.SECRET_CATEGORY_ORDER


def _is_read_rule(low: str) -> bool:
    return "read(" in low or "read " in low


secret_categories_in_text = common.secret_categories_in_text


def destructive_categories_in_text(text: str) -> set[str]:
    low = text.lower()
    return {c for c, pats in DESTRUCTIVE_CATEGORIES.items() if any(_re.search(p, low) for p in pats)}


def secret_file_rule_count(perms: dict) -> int:
    """禁止か承認の設定のうち、秘密ファイルの読み取りを止める行の数。"""
    return sum(
        1 for rule in perms.get("deny", []) + perms.get("ask", [])
        if _is_read_rule(rule.lower()) and secret_categories_in_text(rule)
    )


def destructive_rule_count(perms: dict) -> int:
    """禁止か承認の設定のうち、消す・強制上書き・外へ出すを対象にした行の数。"""
    return sum(1 for rule in perms.get("deny", []) + perms.get("ask", []) if destructive_categories_in_text(rule))


def secret_coverage(perms: dict, hook_texts: list[str]) -> dict:
    """S2: 系統ごとに、設定の行かフックで止めているか（16-2）。"""
    from_rules: set[str] = set()
    for rule in perms.get("deny", []) + perms.get("ask", []):
        if _is_read_rule(rule.lower()):
            from_rules |= secret_categories_in_text(rule)
    from_hooks: set[str] = set()
    for t in hook_texts:
        from_hooks |= secret_categories_in_text(t)
    return {c: (c in from_rules or c in from_hooks) for c in SECRET_CATEGORY_ORDER}


def destructive_coverage(perms: dict, hook_texts: list[str]) -> dict:
    """S3: 系統ごとに、設定の行かフックで止めているか（16-2）。"""
    covered: set[str] = set()
    for rule in perms.get("deny", []) + perms.get("ask", []):
        covered |= destructive_categories_in_text(rule)
    for t in hook_texts:
        covered |= destructive_categories_in_text(t)
    return {c: (c in covered) for c in DESTRUCTIVE_CATEGORY_ORDER}


def deny_or_ask_blocks_secret_files(perms: dict) -> bool:
    return all(secret_coverage(perms, []).values())


def deny_or_ask_blocks_destructive_ops(perms: dict) -> bool:
    return all(destructive_coverage(perms, []).values())


BYPASS_ALL_MODES = {"bypasspermissions", "yolo", "dangerously-skip-permissions"}


def default_mode_is_bypass_all(perms: dict) -> bool:
    mode = perms.get("default_mode")
    if not isinstance(mode, str):
        return False
    return mode.strip().lower() in BYPASS_ALL_MODES


AUTO_JUDGING_MODES = {"auto", "acceptedits", "accept-edits"}


def default_mode_is_auto_judging(perms: dict) -> bool:
    mode = perms.get("default_mode")
    if not isinstance(mode, str):
        return False
    return mode.strip().lower() in AUTO_JUDGING_MODES


_STOP_HOOK_EVENTS = ("Stop", "SubagentStop", "SessionEnd")


def stop_hook_count(perms: dict) -> int:
    hooks = perms.get("hooks", {})
    return sum(hooks.get(k, 0) for k in _STOP_HOOK_EVENTS)


def has_stop_hook(perms: dict) -> bool:
    hooks = perms.get("hooks", {})
    return any(k in hooks for k in _STOP_HOOK_EVENTS)


def readonly_review_agents(workdir: Path, claude_home: Path) -> list[Path]:
    """Edit/Write 系ツールを tools に含まないエージェント定義（確認役）。"""
    out = []
    for f in own_agent_files(workdir, claude_home):
        text = common.read_text_capped(f)
        if text is None:
            continue
        head = text[:2000]
        if "tools:" not in head:
            continue
        import re

        m = re.search(r"tools:\s*(.+)", head)
        if not m:
            continue
        tools_line = m.group(1).lower()
        if "all tools" in tools_line or "all" == tools_line.strip():
            continue
        if "edit" in tools_line or "write" in tools_line:
            continue
        out.append(f)
    return out


def scheduled_task_dirs(claude_home: Path) -> list[Path]:
    base = claude_home / "scheduled-tasks"
    if not base.is_dir():
        return []
    try:
        return [p for p in base.iterdir() if p.is_dir()]
    except OSError:
        return []


def config_files_for_secret_scan(workdir: Path, claude_home: Path) -> list[Path]:
    files = list(settings_files(workdir, claude_home))
    for extra in (claude_home / ".mcp.json",):
        if extra.exists():
            files.append(extra)
    for d in common.walk_up_to_git_root(workdir):
        p = d / ".mcp.json"
        if p.exists():
            files.append(p)
    return files


def _all_session_jsonl(claude_home: Path) -> list[Path]:
    projects = claude_home / "projects"
    if not projects.is_dir():
        return []
    out = []
    try:
        for proj_dir in projects.iterdir():
            if not proj_dir.is_dir():
                continue
            for f in proj_dir.glob("*.jsonl"):
                out.append(f)
    except OSError:
        return out
    return out


def collect_facts(workdir: Path, claude_home: Path, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now()
    facts: dict = {}

    local_files = local_instruction_files(workdir)
    facts["F1"] = {"measured": True, "pass": len(local_files) > 0, "count": len(local_files)}

    startup = startup_files(workdir, claude_home)
    line_counts = [common.count_lines(common.read_text_capped(f) or "") for f in startup]
    facts["F2"] = {
        "measured": len(startup) > 0,
        "pass": all(n < MAX_STARTUP_LINES for n in line_counts) if startup else None,
        "total_lines": sum(line_counts),
        "file_count": len(startup),
        "max_lines": max(line_counts, default=0),
        "over_count": sum(1 for n in line_counts if n >= MAX_STARTUP_LINES),
        "limit_lines": MAX_STARTUP_LINES,
    }

    facts["F3_target_found"] = len(local_files) > 0
    facts["F4_target_found"] = len(startup) > 0
    facts["F3_target_count"] = len(local_files)
    facts["F4_target_count"] = len(startup)

    skills = own_skill_dirs(workdir, claude_home)
    facts["F5"] = {"measured": True, "pass": len(skills) > 0, "count": len(skills)}

    agents = own_agent_files(workdir, claude_home)
    facts["F8"] = {"measured": True, "pass": len(agents) > 0, "count": len(agents)}

    skill_names = {p.name for p in skills}
    agent_names = {p.stem for p in agents}

    sessions = _all_session_jsonl(claude_home)
    facts["_session_count"] = len(sessions)

    used_skills: set[str] = set()
    used_agents: set[str] = set()
    used_mcp_recent = False
    used_mcp_ever = False
    max_consecutive = 0
    any_two_agents_between_humans = False
    d4_hit_sessions = 0
    skill_counts: dict[str, int] = {}
    agent_counts: dict[str, int] = {}
    connector_counts: dict[str, int] = {}
    month_timestamps: list[float] = []
    recent_timestamps: list[float] = []
    recent_session_days: list[float] = []
    tool_calls_recent = 0
    sessions_20plus = 0
    month_tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    # 今月のトークンの重複排除（HIGH差し戻し）: 同じ message.id の行が、同一ファイル内・ファイルを
    # またいだ先の両方で重複することがある。全セッションで1つの集合を共有し、message.id ごとに
    # 1回だけ数える（実測で重複排除前の約2.16倍に膨らんでいた）。
    seen_message_ids: set = set()

    for f in sessions:
        stats = common.scan_claude_jsonl(
            f,
            known_skill_names=skill_names,
            known_agent_names=agent_names,
            seen_message_ids=seen_message_ids,
            now=now if now.tzinfo else now.astimezone(),
            window_days=RECENT_DAYS,
            consecutive_threshold=CONSECUTIVE_THRESHOLD,
        )
        if stats is None:
            continue
        used_skills |= stats.used_skill_names
        used_agents |= stats.used_agent_names
        for k, v in stats.skill_use_counts.items():
            skill_counts[k] = skill_counts.get(k, 0) + v
        for k, v in stats.agent_use_counts.items():
            agent_counts[k] = agent_counts.get(k, 0) + v
        for k, v in stats.connector_use_counts.items():
            connector_counts[k] = connector_counts.get(k, 0) + v
        if stats.used_mcp_tool:
            used_mcp_ever = True
            if stats.recent_days_touched:
                used_mcp_recent = True
        if stats.recent_days_touched and stats.max_consecutive_tool_calls > max_consecutive:
            max_consecutive = stats.max_consecutive_tool_calls
        if stats.distinct_agent_names_between_humans_2plus:
            any_two_agents_between_humans = True
            d4_hit_sessions += 1
        month_timestamps.extend(stats.month_timestamps)
        recent_timestamps.extend(stats.recent_timestamps)
        if stats.recent_timestamps:
            recent_session_days.append(min(stats.recent_timestamps))
        tool_calls_recent += stats.recent_tool_calls
        if stats.recent_timestamps and stats.max_consecutive_tool_calls >= CONSECUTIVE_THRESHOLD:
            sessions_20plus += 1
        for k in month_tokens:
            month_tokens[k] += stats.month_tokens.get(k, 0)

    facts["F6"] = {
        "measured": len(sessions) > 0,
        "pass": len(used_skills) > 0,
        "count": len(used_skills),
        "own_count": len(skills),
        "use_total": sum(skill_counts.values()),
        "session_count": len(sessions),
    }

    if skill_counts:
        ranked = sorted(skill_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        f7_candidates = [name for name, _ in ranked[:5]]
    else:
        ranked_by_mtime = sorted(
            skills, key=lambda p: _mtime_of(p), reverse=True
        )
        f7_candidates = [p.name for p in ranked_by_mtime[:5]]
    facts["F7_candidates"] = f7_candidates
    facts["F7_target_count"] = len(f7_candidates)

    facts["F9"] = {
        "measured": len(sessions) > 0,
        "pass": len(used_agents) > 0,
        "count": len(used_agents),
        "own_count": len(agents),
        "use_total": sum(agent_counts.values()),
        "session_count": len(sessions),
    }

    facts["_skill_use_counts"] = skill_counts
    facts["_agent_use_counts"] = agent_counts
    facts["_connector_use_counts"] = connector_counts

    mcp_count = mcp_server_count(workdir, claude_home)
    facts["F10"] = {
        "measured": True,
        "pass": bool(mcp_count > 0 or used_mcp_ever),
        "config_count": mcp_count,
        "used_in_records": used_mcp_ever,
    }
    facts["F11"] = {
        "measured": len(sessions) > 0,
        "pass": used_mcp_recent,
        "calls_30d": sum(connector_counts.values()),
        "session_count": len(sessions),
    }

    facts["D4"] = {
        "measured": facts["F8"]["pass"] and len(sessions) > 0,
        "pass": any_two_agents_between_humans,
        "hit_count": d4_hit_sessions,
        "own_count": len(agents),
        "session_count": len(sessions),
    }
    facts["D5"] = {
        "measured": len(sessions) > 0,
        "pass": max_consecutive >= CONSECUTIVE_THRESHOLD,
        "max_consecutive": max_consecutive,
        "threshold": CONSECUTIVE_THRESHOLD,
        "session_count": len(sessions),
    }

    perms = _merged_permissions(workdir, claude_home)
    secret_rules = secret_file_rule_count(perms)
    destructive_rules = destructive_rule_count(perms)
    hook_cmds = perms.get("pre_tool_commands", [])
    hook_texts = _hook_texts(hook_cmds, workdir)
    s2_cov = secret_coverage(perms, hook_texts)
    s3_cov = destructive_coverage(perms, hook_texts)
    facts["S2"] = {
        "measured": True,
        "pass": all(s2_cov.values()),
        "rule_count": secret_rules,
        "hook_count": len(hook_cmds),
        "covered": s2_cov,
    }
    facts["S3"] = {
        "measured": True,
        "pass": all(s3_cov.values()),
        "rule_count": destructive_rules,
        "hook_count": len(hook_cmds),
        "covered": s3_cov,
    }
    has_settings = len(settings_files(workdir, claude_home)) > 0
    facts["S4"] = {
        "measured": has_settings,
        "pass": (not default_mode_is_bypass_all(perms)) if has_settings else None,
        "mode_set": isinstance(perms.get("default_mode"), str),
    }
    allow_count = len(perms.get("allow", []))
    auto_mode = default_mode_is_auto_judging(perms)
    facts["D1"] = {
        "measured": True,
        "pass": allow_count > 0 or auto_mode,
        "allow_count": allow_count,
        "auto_mode": auto_mode,
    }

    stop_hook = has_stop_hook(perms)
    readonly_agents = readonly_review_agents(workdir, claude_home)
    facts["D3"] = {
        "measured": True,
        "pass": stop_hook or len(readonly_agents) > 0,
        "needs_ai_fallback": not (stop_hook or len(readonly_agents) > 0),
        "stop_hook_count": stop_hook_count(perms),
        "readonly_agent_count": len(readonly_agents),
    }

    sched_dirs = scheduled_task_dirs(claude_home)
    sched_recent = common.any_file_mtime_within_days(
        [p for d in sched_dirs for p in _safe_rglob(d)], RECENT_DAYS, now=_as_aware(now)
    )
    facts["D2"] = {
        "measured": len(sched_dirs) > 0 and sched_recent,
        "pass": True if (sched_dirs and sched_recent) else None,
        "needs_user_fallback": len(sched_dirs) > 0 and not sched_recent,
        "definition_count": len(sched_dirs),
        "recent": bool(sched_recent),
    }

    facts["_global_instruction_has_content"] = bool(
        global_instruction_file(claude_home)
        and (common.read_text_capped(global_instruction_file(claude_home)) or "").strip()
    )
    facts["_local_instruction_has_content"] = any(
        (common.read_text_capped(f) or "").strip() for f in local_files
    )
    facts["_has_local_override"] = bool(
        global_instruction_local_override(claude_home) or local_instruction_local_override(workdir)
    )
    # 名前の一覧（--show-names のときだけ collect.py が使う。facts.json の既定の出力には入れない）
    facts["_own_skill_names"] = [p.name for p in skills]
    facts["_own_agent_names"] = [p.stem for p in agents]
    facts["_mcp_server_names"] = mcp_server_names(workdir, claude_home)
    facts["_has_stop_hook"] = stop_hook
    facts["_has_scheduled_defs"] = len(sched_dirs) > 0
    facts["_stop_hook_count"] = stop_hook_count(perms)
    facts["_scheduled_def_count"] = len(sched_dirs)

    # 今月の使用量（時間・トークン。5-10）。道具の検出自体は collect.py 側（detect_claude_code）で
    # 判定済みなので、ここでは「セッションが1件以上読めたか」を measured の根拠にする。
    facts["_usage_this_month"] = {
        "measured": True,
        "active_seconds": common.compute_active_seconds(month_timestamps),
        "tokens": month_tokens,
    }

    # 表紙のダッシュボード（16-3）。数だけ。名前・本文は持たない
    mcp_names = set(mcp_server_names(workdir, claude_home))
    facts["_dashboard"] = {
        "measured": len(sessions) > 0,
        "daily_30d": common.daily_activity_jst(recent_timestamps, recent_session_days, now=(now if now.tzinfo else now.astimezone()), days=RECENT_DAYS),
        "breadth": {
            "skills": {"own": len(skills), "used": len(used_skills)},
            "agents": {"own": len(agents), "used": len(used_agents)},
            # 設定（.mcp.json）にあるものと、記録で呼ばれたもの（claude.ai 側・プラグイン同梱を含む）を合わせる
            "connectors": {"own": len(mcp_names | set(connector_counts)), "used": len(set(connector_counts))},
        },
        "autonomy": {
            "tool_calls_30d": tool_calls_recent,
            "max_consecutive": max_consecutive,
            "sessions_20plus": sessions_20plus,
            "agent_relay_sessions": d4_hit_sessions,
        },
    }

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


def _as_aware(dt: datetime) -> datetime:
    from datetime import timezone

    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
