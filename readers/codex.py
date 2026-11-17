"""Codex 用の読み取り部品。読むだけ・通信なし。

Codex の会話の記録（`~/.codex/sessions/`）は、最近のものは平文の `.jsonl`、
時間が経つと `.jsonl.zst`（zstd 圧縮）になる。圧縮形式は Python 標準機能だけでは
読めないため（3.14 未満に `compression.zstd` が無い）、読めた平文の記録だけを使って
F11・D5 を判定する。F6・F9・D4 は、平文でも「自分で用意したスキル／エージェント」の
呼び出しを区別する仕組みが無いため、引き続き「測定できず」とする（SPEC 10章・13章）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import common


MAX_STARTUP_BYTES = 32 * 1024
RECENT_DAYS = 30

# `default_permissions` の組み込みプロファイル名（先頭の `:` を外した形・小文字）。
_BUILTIN_PERMISSION_PROFILES = {"read-only", "workspace", "danger-full-access"}

# S2: 許可の仕組み（permissions.<name>.filesystem）の中の、秘密ファイルらしいパスの印。
# Claude Code 側の S2 判定（readers/claude_code.py）と同じ語の一覧。

# Codex の会話の記録のファイル名（`rollout-2026-11-16T16-17-47-<id>.jsonl` 等）から
# 作られた日時を読む。圧縮済み（.jsonl.zst）でもファイル名の日時だけは読める。
_ROLLOUT_NAME_RE = re.compile(r"rollout-(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})-")

# 道具の呼び出しとして数える response_item の種類（D5・F11で使う。名前には依らない）。
_TOOL_CALL_SUBTYPES = {"function_call", "custom_tool_call", "mcp_tool_call", "local_shell_call"}


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


def _read_codex_config(codex_home: Path) -> dict:
    """`config.toml` を読む。

    `tomllib`（3.11以上）があれば、それで正しく読む（入れ子のテーブル・一行テーブルも
    そのまま辞書になる）。壊れた TOML なら `config_broken=True` を返し、呼び出す側は
    承認・許可関連の項目（S2・S3・S4・D1）をすべて「測定できず」にする（推測で埋めない）。
    `tomllib` が無い環境（3.9・3.10）は、クォートされた文字列の値だけを認める簡易読み取りに
    フォールバックする（`permissions_table` は None＝「別途 `toml_table_scalars` 等で読む」）。
    """
    text = config_toml_text(codex_home)
    if text is None:
        return {
            "present": False, "config_broken": False,
            "approval_policy": None, "sandbox_mode": None, "default_permissions": None,
            "permissions_table": None,
        }

    if common.tomllib is not None:
        parsed = common.parse_toml_strict(text)
        if parsed is None:
            return {
                "present": True, "config_broken": True,
                "approval_policy": None, "sandbox_mode": None, "default_permissions": None,
                "permissions_table": None,
            }
        approval_policy = parsed.get("approval_policy")
        sandbox_mode = parsed.get("sandbox_mode")
        default_permissions = parsed.get("default_permissions")
        permissions_table = parsed.get("permissions")
        return {
            "present": True, "config_broken": False,
            "approval_policy": approval_policy if isinstance(approval_policy, str) else None,
            "sandbox_mode": sandbox_mode if isinstance(sandbox_mode, str) else None,
            "default_permissions": default_permissions if isinstance(default_permissions, str) else None,
            "permissions_table": permissions_table if isinstance(permissions_table, dict) else {},
        }

    scalars = common.toml_top_level_scalars(text)
    return {
        "present": True, "config_broken": False,
        "approval_policy": scalars.get("approval_policy"),
        "sandbox_mode": scalars.get("sandbox_mode"),
        "default_permissions": scalars.get("default_permissions"),
        "permissions_table": None,
    }


def _normalize_permission_profile(value: Optional[str]) -> Optional[str]:
    """`default_permissions` の値から先頭の `:` だけ外す。

    大文字小文字は変えない（自分で決めた名前はテーブル名として大文字小文字が意味を持つ
    ため。組み込み名かどうかの判定は `_is_builtin_permission_name` が別途小文字で比べる）。
    """
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v.startswith(":"):
        v = v[1:]
    v = v.strip()
    return v or None


def _is_builtin_permission_name(value: Optional[str]) -> bool:
    return isinstance(value, str) and value.strip().lower() in _BUILTIN_PERMISSION_PROFILES


def _secret_file_deny_count_from_dict(filesystem_node, cats: Optional[set] = None) -> int:
    """`permissions.<name>.filesystem` の中身（辞書）を再帰的に調べる。

    `tomllib` で読んだ辞書は、公式の書き方（`":workspace_roots" = { ... }` のような
    一行テーブルや `[permissions.<name>.filesystem.":workspace_roots"]` の入れ子テーブル）
    のどちらも、ふつうの入れ子の dict になっているため、同じ再帰処理で両方拾える。
    """
    if not isinstance(filesystem_node, dict):
        return 0
    n = 0
    for key, val in filesystem_node.items():
        if isinstance(val, dict):
            n += _secret_file_deny_count_from_dict(val, cats)
            continue
        if isinstance(val, str) and val.strip().lower() == "deny":
            found = common.secret_categories_in_text(str(key))
            if found:
                n += 1
                if cats is not None:
                    cats |= found
    return n


def _secret_file_deny_count_fallback_text(codex_home: Path, profile_name: str, cats: Optional[set] = None) -> int:
    """`tomllib` が無い環境（3.9・3.10）向けの簡易読み取り。

    公式の書き方2通り（`[permissions.<name>.filesystem]` 直下の一行テーブル
    `":workspace_roots" = { ... }`、および `[permissions.<name>.filesystem.":workspace_roots"]`
    という入れ子テーブル）の両方を見る。完全な TOML パーサではないため、`tomllib` が
    使える環境（3.11以上）より取りこぼす可能性がある。
    """
    text = config_toml_text(codex_home)
    if text is None:
        return 0
    n = 0
    base_path = f"permissions.{profile_name}.filesystem"

    def count_scalar(key: str, val: str) -> int:
        if val.strip().strip('"').strip("'").lower() != "deny":
            return 0
        found = common.secret_categories_in_text(key)
        if found and cats is not None:
            cats.update(found)
        return 1 if found else 0

    direct = common.toml_table_scalars(text, base_path)
    for key, val in direct.items():
        v = val.strip()
        if v.startswith("{") and v.endswith("}"):
            for ik, iv in common.toml_inline_table_pairs(v).items():
                n += count_scalar(ik, iv)
            continue
        n += count_scalar(key, val)

    nested = common.toml_table_scalars(text, base_path + '.":workspace_roots"')
    for key, val in nested.items():
        n += count_scalar(key, val)

    return n


def secret_file_deny_rule_count(
    codex_home: Path, profile_name: Optional[str], permissions_table, cats: Optional[set] = None
) -> int:
    """S2: 自分で決めた許可の仕組み（`permissions.<name>.filesystem`）の中で、

    秘密ファイルらしいパスを `deny`（読み取り拒否）にしている設定の数。
    組み込みプロファイル（`:read-only` 等）は自分でパスを指定できないため対象外
    （呼び出す側が profile_name に None を渡す）。
    `permissions_table` が辞書（`tomllib` で読めた場合）なら、それを使う（入れ子・
    一行テーブルも正しく拾える）。None（`tomllib` が無い環境）なら簡易読み取りに回す。
    """
    if not profile_name:
        return 0
    if permissions_table is not None:
        profile = permissions_table.get(profile_name)
        filesystem = profile.get("filesystem") if isinstance(profile, dict) else None
        return _secret_file_deny_count_from_dict(filesystem, cats)
    return _secret_file_deny_count_fallback_text(codex_home, profile_name, cats)


def hooks_json_has_stop(codex_home: Path, workdir: Path) -> Optional[bool]:
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
    facts["F1"] = {"measured": True, "pass": len(local_files) > 0, "count": len(local_files)}

    startup = startup_files(workdir)
    total_bytes = sum((f.stat().st_size for f in startup if f.exists()), 0)
    facts["F2"] = {
        "measured": len(startup) > 0,
        "pass": total_bytes < MAX_STARTUP_BYTES if startup else None,
        "total_bytes": total_bytes,
        "file_count": len(startup),
        "limit_bytes": MAX_STARTUP_BYTES,
    }

    facts["F3_target_found"] = len(local_files) > 0
    facts["F4_target_found"] = len(startup) > 0
    facts["F3_target_count"] = len(local_files)
    facts["F4_target_count"] = len(startup)

    skills = own_skill_dirs(workdir, home)
    facts["F5"] = {"measured": True, "pass": len(skills) > 0, "count": len(skills)}
    ranked_by_mtime = sorted(skills, key=lambda p: _mtime_of(p), reverse=True)
    facts["F7_candidates"] = [p.name for p in ranked_by_mtime[:5]]
    facts["F7_target_count"] = len(facts["F7_candidates"])

    agents = own_agent_files(workdir, codex_home)
    facts["F8"] = {"measured": True, "pass": len(agents) > 0, "count": len(agents)}

    facts["F6"] = {"measured": False, "pass": None}
    facts["F9"] = {"measured": False, "pass": None}

    mcp_present = mcp_servers_present(codex_home)
    facts["F10"] = {"measured": True, "pass": mcp_present}

    # 会話の記録（平文の分だけ）から D5・F11・今月の使用量をまとめて集計する（LOW差し戻し:
    # 候補ファイルは1回だけ読む。_collect_codex_usage 参照）。圧縮分（.jsonl.zst）は読めないため
    # 読めた件数・読めなかった件数の両方を facts に残す（理由の文はこれを見て正確に書く）。
    codex_usage = _collect_codex_usage(codex_home, now=now, window_days=RECENT_DAYS)
    session_summary = codex_usage["session_summary"]
    read_count = session_summary["read_count"]
    unreadable_count = session_summary["unreadable_count"]
    logs_measured = read_count > 0

    facts["F11"] = {
        "measured": logs_measured,
        "pass": session_summary["mcp_used_recent"] if logs_measured else None,
        "calls_30d": session_summary.get("mcp_calls_recent", 0),
        "read_session_count": read_count,
        "unreadable_session_count": unreadable_count,
    }

    facts["D4"] = {"measured": False, "pass": None}
    facts["D5"] = {
        "measured": logs_measured,
        "pass": (session_summary["max_consecutive"] >= 20) if logs_measured else None,
        "max_consecutive": session_summary["max_consecutive"],
        "threshold": 20,
        "read_session_count": read_count,
        "unreadable_session_count": unreadable_count,
    }

    config = _read_codex_config(codex_home)
    config_broken = config["config_broken"]
    policy = config["approval_policy"]
    sandbox = config["sandbox_mode"]
    permissions_table = config["permissions_table"]
    default_permission = _normalize_permission_profile(config["default_permissions"])
    is_builtin_permission = _is_builtin_permission_name(default_permission)

    # 旧キー（sandbox_mode）があるときは、新しい許可の仕組み（default_permissions）は
    # 判定に使わない（公式の「同時に使わない」案内に合わせる。SPEC 14-1）。
    use_new_permission_signal = (not config_broken) and sandbox is None

    custom_permission_profile = (
        default_permission
        if (use_new_permission_signal and default_permission and not is_builtin_permission)
        else None
    )

    secret_cats: set = set()
    secret_rule_count = (
        0
        if config_broken
        else secret_file_deny_rule_count(codex_home, custom_permission_profile, permissions_table, secret_cats)
    )
    s2_cov = {c: (c in secret_cats) for c in common.SECRET_CATEGORY_ORDER}
    s2_measured = (not config_broken) and (custom_permission_profile is not None)
    facts["S2"] = {
        "measured": s2_measured,
        "pass": all(s2_cov.values()) if s2_measured else None,
        "rule_count": secret_rule_count,
        "covered": s2_cov,
    }

    has_approval_signal = (not config_broken) and (
        policy is not None
        or sandbox is not None
        or (use_new_permission_signal and is_builtin_permission)
    )

    is_full_access_from_permissions = (
        use_new_permission_signal and is_builtin_permission and default_permission.strip().lower() == "danger-full-access"
    )
    is_full_access = (sandbox or "").strip().lower() == "danger-full-access" or is_full_access_from_permissions
    is_never_ask = (policy or "").strip().lower() == "never"
    is_always_ask = (policy or "").strip().lower() == "untrusted"

    approval_flags = {"never_ask": is_never_ask, "full_access": is_full_access, "always_ask": is_always_ask}
    facts["S3"] = {
        "measured": has_approval_signal,
        "pass": (not is_never_ask) and (not is_full_access) if has_approval_signal else None,
        **approval_flags,
    }
    facts["S4"] = {
        "measured": has_approval_signal,
        "pass": not (is_never_ask and is_full_access) if has_approval_signal else None,
        **approval_flags,
    }
    facts["D1"] = {
        "measured": has_approval_signal,
        "pass": not is_always_ask if has_approval_signal else None,
        **approval_flags,
    }

    stop_hook = hooks_json_has_stop(codex_home, workdir)
    facts["D3"] = {
        "measured": stop_hook is not None,
        "pass": bool(stop_hook) if stop_hook is not None else None,
        "needs_ai_fallback": stop_hook is not True,
        "hook_file_found": stop_hook is not None,
        "stop_hook_count": 1 if stop_hook else 0,
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
        "recent": bool(sched_recent),
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
    facts["_own_skill_names"] = [p.name for p in skills]
    facts["_own_agent_names"] = [p.stem for p in agents]
    facts["_stop_hook_count"] = 1 if stop_hook else 0
    facts["_scheduled_def_count"] = len(autos)

    # 今月の使用量（時間・トークン。5-10）。
    facts["_usage_this_month"] = codex_usage["month_usage"]

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


# ---------------------------------------------------------------------------
# 会話の記録（D5・F11）。平文の .jsonl だけ読む。.jsonl.zst（圧縮）はファイル名の
# 日時だけ読み、本文は読まない（読めなかった件数として数える。推測で埋めない）。
# ---------------------------------------------------------------------------


def _parse_session_filename_dt(name: str) -> Optional[datetime]:
    m = _ROLLOUT_NAME_RE.search(name)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
    except ValueError:
        return None


def _session_candidate_files(codex_home: Path) -> list[Path]:
    """会話の記録らしきファイル（平文・圧縮の両方）を集める。中身は読まない。"""
    out: list[Path] = []
    sessions_dir = codex_home / "sessions"
    if sessions_dir.is_dir():
        try:
            out.extend(
                p for p in sessions_dir.rglob("*")
                if p.is_file() and (p.name.endswith(".jsonl") or p.name.endswith(".jsonl.zst"))
            )
        except OSError:
            pass
    archived_dir = codex_home / "archived_sessions"
    if archived_dir.is_dir():
        try:
            out.extend(
                p for p in archived_dir.iterdir()
                if p.is_file() and (p.name.endswith(".jsonl") or p.name.endswith(".jsonl.zst"))
            )
        except OSError:
            pass
    return out


def _parse_entry_ts(value) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        v = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _is_human_message(payload: dict) -> bool:
    """`response_item` が人（本人）の発言の行か（role が user の message）。"""
    return payload.get("type") == "message" and payload.get("role") == "user"


def scan_codex_session_file(path: Path, now: Optional[datetime], window_days: int) -> Optional[dict]:
    """1件の平文の会話の記録（.jsonl）を1行ずつ読み、D5・F11・今月の使用量の統計だけ返す。

    本文・名前は保持しない。読めなければ None（呼び出す側が「読めなかった」扱いにする）。
    今月の使用量（時間・トークン。5-10）は、会話の記録の種類を問わず全行の時刻と、
    `token_usage_record` の中の数値（`payload.usage`）を見る。
    """
    try:
        if not path.is_file():
            return None
    except OSError:
        return None

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    month_start = common.month_start_jst(now)
    consecutive = 0
    max_consecutive = 0
    mcp_used_recent = False
    mcp_calls_recent = 0
    month_timestamps: list = []
    month_tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}

    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue

                ts = _parse_entry_ts(entry.get("timestamp"))
                if ts is not None and month_start <= ts <= now:
                    month_timestamps.append(ts.timestamp())

                if entry.get("type") == "token_usage_record" and ts is not None and month_start <= ts <= now:
                    usage = entry.get("payload", {}).get("usage") if isinstance(entry.get("payload"), dict) else None
                    if isinstance(usage, dict):
                        # MEDIUM差し戻し: Codex の cached_input_tokens は input_tokens の内数
                        # （input_tokens ⊇ cached_input_tokens）。そのまま両方を別区分として足すと、
                        # 「入力」にキャッシュの読み分が二重に乗る。「入力」はキャッシュの読み分を
                        # 除いた分（新規に読んだ分）にし、4区分（入力／出力／キャッシュ読み／
                        # キャッシュ書き）を足すと total_tokens 相当に一致するようにする。
                        input_total = common.usage_num(usage, "input_tokens")
                        cache_read = common.usage_num(usage, "cached_input_tokens")
                        month_tokens["input"] += max(0, input_total - cache_read)
                        month_tokens["output"] += common.usage_num(usage, "output_tokens") + common.usage_num(
                            usage, "reasoning_output_tokens"
                        )
                        month_tokens["cache_read"] += cache_read
                        month_tokens["cache_write"] += common.usage_num(usage, "cache_write_input_tokens")

                if entry.get("type") != "response_item":
                    continue
                payload = entry.get("payload")
                if not isinstance(payload, dict):
                    continue
                if _is_human_message(payload):
                    consecutive = 0
                    continue
                if payload.get("type") not in _TOOL_CALL_SUBTYPES:
                    continue
                consecutive += 1
                if consecutive > max_consecutive:
                    max_consecutive = consecutive
                namespace = payload.get("namespace")
                is_mcp_call = (isinstance(namespace, str) and namespace.startswith("mcp__")) or (
                    payload.get("type") == "mcp_tool_call"
                )
                if is_mcp_call:
                    entry_ts = _parse_entry_ts(entry.get("timestamp"))
                    if entry_ts is not None and entry_ts >= cutoff:
                        mcp_used_recent = True
                        mcp_calls_recent += 1
    except OSError:
        return None

    return {
        "max_consecutive": max_consecutive,
        "mcp_used_recent": mcp_used_recent,
        "mcp_calls_recent": mcp_calls_recent,
        "month_timestamps": month_timestamps,
        "month_tokens": month_tokens,
    }


def _collect_codex_usage(codex_home: Path, now: Optional[datetime], window_days: int) -> dict:
    """直近 window_days 日の会話の記録の集計（D5・F11用）と、今月の使用量（時間・トークン。
    5-10）の集計を、**候補ファイルを1回ずつだけ読んで**まとめて行う（LOW差し戻し: 以前は
    別々の関数がそれぞれ全ファイルを走査しており、同じ平文ファイルを2回読んでいた）。

    2つの集計は対象期間が違う（直近30日 と 今月の開始の1日前から）。「1日前」の余裕は、
    セッションの開始がぎりぎり前月でも、中の記録が今月に入っている場合を取りこぼさないため
    （実際にどの行を数えるかは行ごとの時刻で判定するので、この余裕自体が数え方に影響しない）。
    ファイルは、どちらか一方の期間にでも入っていれば読む。
    """
    now = now or datetime.now(timezone.utc)
    cutoff_30d = now - timedelta(days=window_days)
    month_start = common.month_start_jst(now)
    cutoff_month_file = month_start - timedelta(days=1)
    broad_cutoff = min(cutoff_30d, cutoff_month_file)

    read_count_30d = 0
    unreadable_count_30d = 0
    max_consecutive = 0
    mcp_used_recent = False
    mcp_calls_recent = 0

    read_count_month = 0
    unreadable_count_month = 0
    month_timestamps: list = []
    month_tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}

    for p in _session_candidate_files(codex_home):
        dt = _parse_session_filename_dt(p.name)
        if dt is None or dt < broad_cutoff:
            continue
        in_30d = dt >= cutoff_30d
        in_month = dt >= cutoff_month_file
        if not in_30d and not in_month:
            continue

        if p.name.endswith(".jsonl.zst"):
            if in_30d:
                unreadable_count_30d += 1
            if in_month:
                unreadable_count_month += 1
            continue

        stats = scan_codex_session_file(p, now=now, window_days=window_days)
        if stats is None:
            if in_30d:
                unreadable_count_30d += 1
            if in_month:
                unreadable_count_month += 1
            continue

        if in_30d:
            read_count_30d += 1
            if stats["max_consecutive"] > max_consecutive:
                max_consecutive = stats["max_consecutive"]
            if stats["mcp_used_recent"]:
                mcp_used_recent = True
            mcp_calls_recent += stats.get("mcp_calls_recent", 0)
        if in_month:
            read_count_month += 1
            month_timestamps.extend(stats.get("month_timestamps", []))
            for k in month_tokens:
                month_tokens[k] += stats.get("month_tokens", {}).get(k, 0)

    session_summary = {
        "read_count": read_count_30d,
        "unreadable_count": unreadable_count_30d,
        "max_consecutive": max_consecutive,
        "mcp_used_recent": mcp_used_recent,
        "mcp_calls_recent": mcp_calls_recent,
    }

    # measured の意味（MEDIUM差し戻し・分かりやすく）:
    # - 今月分を1件以上読めた（read_count_month > 0）→ 実測できたので measured=True。
    # - 今月分の記録が（読めた分・読めなかった分とも）1件も無い（read==0 かつ unreadable==0）
    #   → そもそも今月は会話が無かった、という「正しいゼロ」なので measured=True。
    # - 今月分はあるが全部圧縮されていて読めない（read==0 かつ unreadable>0）→ 実態が分からない
    #   ので measured=False（0をそのまま「使っていない」と断定しない。原則2）。
    month_measured = read_count_month > 0 or unreadable_count_month == 0
    month_usage = {
        "measured": month_measured,
        "active_seconds": common.compute_active_seconds(month_timestamps),
        "tokens": month_tokens,
        "read_session_count": read_count_month,
        "unreadable_session_count": unreadable_count_month,
    }

    return {"session_summary": session_summary, "month_usage": month_usage}
