"""ハーネス点検 — 道具共通の読み取りユーティリティ。

このファイルは読むだけ。通信は一切しない（urllib/requests/socket の import 禁止）。
書き込みは行わない（呼び出し側が facts.json を書く）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable, Optional


# ---------------------------------------------------------------------------
# 秘密の値（キーの形）の走査（5-5）
# ---------------------------------------------------------------------------

# 「件数と種類だけ」を返す。値そのものは呼び出し側にも返さない。
SECRET_PATTERNS: dict[str, re.Pattern] = {
    "openai_or_anthropic": re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{16,}"),
    "google_aiza": re.compile(r"(?<![A-Za-z0-9_-])AIza[A-Za-z0-9_-]{20,}"),
    "github_token": re.compile(r"(?<![A-Za-z0-9_-])gh[pousr]_[A-Za-z0-9]{20,}"),
    "slack_token": re.compile(r"(?<![A-Za-z0-9_-])xox[baprs]-[A-Za-z0-9-]{10,}"),
    "aws_access_key": re.compile(r"(?<![A-Za-z0-9_-])AKIA[0-9A-Z]{12,}"),
    "private_key_header": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}

MAX_SCAN_FILE_BYTES = 1024 * 1024  # 1MB

# 見本・プレースホルダの除外（5-5）。大文字小文字は区別しない。
_PLACEHOLDER_SUBSTRINGS = (
    "xxxx",
    "your",
    "example",
    "placeholder",
    "replace",
    "dummy",
    "changeme",
    "...",
)
_PLACEHOLDER_ANGLE_RE = re.compile(r"<[^<>]{0,60}>")
_REPEATED_CHAR_RE = re.compile(r"(.)\1{5,}")
_LOWER_HYPHEN_ONLY_RE = re.compile(r"^[a-z-]+$")
# 命名の決まり・名前の例らしい文字列（5-5）。sk-系の形にだけ使う（3回目差し戻しで範囲を限定）。
# サービスを示す先頭部分（sk-ant-, sk-proj-, sk- の順で長いものから試す）を除いた残りが
# 英小文字・数字・ハイフンだけで、ハイフンが2つ以上なら、命名の決まり・名前の例と判断する。
# Slack・GitHub・AWS・Google の形には使わない（先頭部分だけで種類が決まり、小文字・数字・
# ハイフンだけの本物のトークンがありうるため）。判定は元の文字列（小文字化前）で行う。
_SK_FAMILY_PREFIXES = ("sk-ant-", "sk-proj-", "sk-")
_NAMING_CONVENTION_RE = re.compile(r"^[a-z0-9-]+$")
_ENV_REF_RES = (
    re.compile(r"^\$\{[^}]+\}$"),
    re.compile(r"^\$[A-Za-z_][A-Za-z0-9_]*$"),
    re.compile(r"^env:", re.IGNORECASE),
)


def is_placeholder_value(value: str) -> bool:
    """見本・プレースホルダらしい値か（5-5「見本は数えない」）。"""
    low = value.lower()
    if any(s in low for s in _PLACEHOLDER_SUBSTRINGS):
        return True
    if _PLACEHOLDER_ANGLE_RE.search(value):
        return True
    if _REPEATED_CHAR_RE.search(value):
        return True
    if _LOWER_HYPHEN_ONLY_RE.match(value):
        return True
    return False


def is_naming_convention_like(value: str) -> bool:
    """sk-系の形だけに使う除外（5-5・3回目差し戻し）。

    サービスを示す先頭部分を除いた残りが、英小文字・数字・ハイフンだけで、
    ハイフンが2つ以上なら、命名の決まり・名前の例と判断する。
    sk-系以外（Slack・GitHub・AWS・Google 等）には適用しない。
    """
    for prefix in _SK_FAMILY_PREFIXES:
        if value.startswith(prefix):
            remainder = value[len(prefix):]
            return bool(_NAMING_CONVENTION_RE.match(remainder)) and remainder.count("-") >= 2
    return False


def is_env_reference(value: str) -> bool:
    """環境変数の参照（`${...}`・`$NAME`・`env:`）か。"""
    return any(p.search(value) for p in _ENV_REF_RES)


def scan_text_for_secrets(text: str) -> dict[str, int]:
    """テキストの中からキーらしき文字列を数える。見本は除く。値は返さない。"""
    counts: dict[str, int] = {}
    for kind, pattern in SECRET_PATTERNS.items():
        n = 0
        for m in pattern.finditer(text):
            matched = m.group(0)
            if is_placeholder_value(matched):
                continue
            if kind == "openai_or_anthropic" and is_naming_convention_like(matched):
                continue
            n += 1
        if n:
            counts[kind] = counts.get(kind, 0) + n
    return counts


# 設定ファイルの中の、名前でわかる秘密（5-5 第2種）。
# 値は「"..."」「'...'」（中に } , 空白を含んでよい）か、素のままの語（空白・,・} まで）のどれか。
_NAMED_SECRET_KEY_RE = re.compile(
    r"(?i)[\"']?([A-Za-z0-9_.\-]*(?:token|secret|api[_-]?key|password|authorization)[A-Za-z0-9_.\-]*)[\"']?"
    r"\s*[:=]\s*(?:\"([^\"\n]{8,})\"|'([^'\n]{8,})'|([^\s,}\n]{8,}))"
)


def scan_text_for_named_secrets(text: str) -> dict[str, int]:
    """設定ファイルの中の、項目名（token/secret/api_key/password/authorization）でわかる秘密を数える。

    値が環境変数の参照・見本なら数えない。
    """
    count = 0
    for line in text.splitlines():
        m = _NAMED_SECRET_KEY_RE.search(line)
        if not m:
            continue
        value = next((g for g in m.groups()[1:] if g is not None), None)
        if not value:
            continue
        value = value.strip()
        if not value or len(value) < 8:
            continue
        if is_env_reference(value):
            continue
        if is_placeholder_value(value):
            continue
        if is_naming_convention_like(value):
            continue
        count += 1
    if count:
        return {"named_secret": count}
    return {}


def merge_counts(*dicts: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out


def is_probably_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def read_text_capped(path: Path, max_bytes: int = MAX_SCAN_FILE_BYTES) -> Optional[str]:
    """テキストファイルを上限付きで読む。読めない・大きすぎる・バイナリなら None。"""
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size > max_bytes:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if not is_probably_text(data):
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ---------------------------------------------------------------------------
# 外部プログラムの起動（5-7）。起動する命令の形は、次の3つに固定する。
#   1. git ls-files -z
#   2. git remote（引数なし）
#   3. Chrome で、出力フォルダの中のHTMLを、出力フォルダの中のPDFに書き出す
# 入口はこの3つの専用関数だけ。任意の引数の並びを受け取る汎用の入口は外に見せない。
# プログラムの場所は、どの関数も自分で決める（呼び出す側からは渡させない）。
# スクリプト全体で、_run_subprocess だけが subprocess を呼ぶ（1か所）。
# ---------------------------------------------------------------------------

# 利用者やリポジトリの設定に書かれたプログラムが動かないようにする前置き引数（5-7）。
GIT_SAFE_PREFIX_ARGS = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]

# Chrome の実行ファイルの場所（決まった場所の一覧。部分一致ではなく、このものずばり）。
_CHROME_EXACT_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]
# PATH 上から探すときも、完全に一致する名前だけを対象にする（部分一致はしない）。
_CHROME_EXACT_NAMES = ("google-chrome", "chromium", "chromium-browser")


def git_safe_env() -> dict:
    """全体の設定・システムの設定を読ませない環境変数（5-7）。"""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }
    return env


def _run_subprocess(argv: list[str], cwd: Optional[Path], env: dict, timeout: int, binary: bool):
    """subprocess を呼ぶ唯一の箇所。外には見せない（3つの専用関数だけが呼ぶ）。"""
    try:
        proc = subprocess.run(
            list(argv),
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env),
            capture_output=True,
            text=not binary,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def git_ls_files_z(cwd: Path, timeout: int = 30) -> list[str]:
    """固定の命令1: `git ls-files -z`。日本語名も正しくデコードして返す。

    呼び出す側が渡せるのは作業フォルダ（cwd）だけ。コマンドそのものは固定で、
    引数の並びを外から渡す口は無い。
    `-z` は NUL区切り・無引用（quotePath の影響を受けない）出力になるため、
    英数字以外の名前のファイルも実在のパスとして正しく扱える（CRITICAL finding #1 の直し方）。
    """
    argv = ["git", *GIT_SAFE_PREFIX_ARGS, "ls-files", "-z"]
    raw = _run_subprocess(argv, cwd=cwd, env=git_safe_env(), timeout=timeout, binary=True)
    if not raw:
        return []
    out = []
    for p in raw.split(b"\x00"):
        if not p:
            continue
        try:
            out.append(p.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    return out


def git_has_remote(cwd: Path, timeout: int = 30) -> bool:
    """固定の命令2: `git remote`（引数なし）。リモートが1つ以上あるかを返す。

    呼び出す側が渡せるのは作業フォルダ（cwd）だけ。
    """
    argv = ["git", *GIT_SAFE_PREFIX_ARGS, "remote"]
    out = _run_subprocess(argv, cwd=cwd, env=git_safe_env(), timeout=timeout, binary=False)
    return bool(out and out.strip())


def _find_chrome() -> Optional[str]:
    """Chrome の実行ファイルを、決まった場所の一覧と完全一致の名前からだけ探す。"""
    for c in _CHROME_EXACT_PATHS:
        if Path(c).is_file():
            return c
    for name in _CHROME_EXACT_NAMES:
        found = shutil.which(name)
        if found and os.path.basename(found) == name:
            return found
    return None


def _is_within(path: Path, base: Path) -> bool:
    try:
        return path.resolve().is_relative_to(base.resolve())
    except (OSError, ValueError):
        return False


def render_pdf_with_chrome(html_path: Path, pdf_path: Path, out_dir: Path, timeout: int = 120) -> bool:
    """固定の命令3: Chrome ヘッドレスで、出力フォルダの中のHTMLをPDFに書き出す。

    呼び出す側が渡せるのは HTML・PDF の場所（out_dir の中限定）だけ。専用の設定
    フォルダ（--user-data-dir）はこの関数が out_dir の中に自分で作り、終わったら消す。
    Chrome の実行ファイルの場所は呼び出す側からは渡させない（この関数が自分で決める）。
    out_dir の外を指す html_path・pdf_path を渡すと、起動せず False を返す。

    戻り値: PDF が書き出せたら True。Chrome が見つからない・out_dir の外を指す・
    失敗した場合は False。
    """
    out_dir = out_dir.resolve()
    if not _is_within(html_path, out_dir) or not _is_within(pdf_path, out_dir):
        return False

    chrome = _find_chrome()
    if chrome is None:
        return False

    profile_dir = Path(tempfile.mkdtemp(prefix="chrome-profile-", dir=str(out_dir)))
    if not _is_within(profile_dir, out_dir):
        shutil.rmtree(profile_dir, ignore_errors=True)
        return False

    html_resolved = html_path.resolve()
    pdf_resolved = pdf_path.resolve()
    argv = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_resolved}",
        html_resolved.as_uri(),
    ]
    try:
        _run_subprocess(argv, cwd=None, env=dict(os.environ), timeout=timeout, binary=False)
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)
    return pdf_resolved.exists()


# ---------------------------------------------------------------------------
# 作業フォルダ階層探索（F1・F2・G1 など）
# ---------------------------------------------------------------------------


def find_git_root(start: Path) -> Optional[Path]:
    cur = start.resolve()
    for _ in range(64):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent
    return None


def walk_up_to_git_root(start: Path) -> list[Path]:
    """作業フォルダから Git ルートまでの各階層フォルダを返す（作業フォルダ含む）。"""
    start = start.resolve()
    root = find_git_root(start)
    chain: list[Path] = [start]
    cur = start
    if root is None:
        return chain
    while cur != root:
        cur = cur.parent
        chain.append(cur)
        if cur == root:
            break
    return chain


def count_lines(text: str) -> int:
    if text == "":
        return 0
    # 末尾の改行は1行分として数えない
    return len(text.splitlines())


def has_frontmatter_paths(text: str) -> bool:
    """YAML frontmatter に paths: キーがあるか（簡易判定）。"""
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return False
    fm = text[3:end]
    return bool(re.search(r"^\s*paths\s*:", fm, re.MULTILINE))


# ---------------------------------------------------------------------------
# ごく小さな TOML 読み取り（標準機能のみ。3.9 には tomllib が無いため自作）
# ---------------------------------------------------------------------------


def toml_top_level_scalars(text: str) -> dict[str, str]:
    """トップレベル（どのテーブルにも属さない）の key = value を雑に拾う。

    文字列値はクォートを外す。配列・テーブルは文字列化せず素通りする。
    完全な TOML パーサではない（本ツールの判定に必要な範囲のみ）。
    """
    out: dict[str, str] = {}
    in_table = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_table = True
            continue
        if in_table:
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*=\s*(.+)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        val = val.split("#", 1)[0].strip() if not val.startswith('"') else val
        if val.startswith('"') and val.endswith('"') and len(val) >= 2:
            val = val[1:-1]
        elif val.startswith(":") :
            val = val.lstrip(":").strip('"')
        out[key] = val
    return out


def toml_has_table(text: str, table_prefix: str) -> bool:
    """[table_prefix] または [table_prefix.xxx] / [[table_prefix]] があるか。"""
    pattern = re.compile(
        r"^\[\[?\s*" + re.escape(table_prefix) + r"(\.[A-Za-z0-9_.\-\"']+)?\s*\]\]?",
        re.MULTILINE,
    )
    return bool(pattern.search(text))


# ---------------------------------------------------------------------------
# 会話の記録（JSONL）の読み取り（5-3）
# ---------------------------------------------------------------------------


@dataclass
class ConversationStats:
    """1つの会話ファイル（セッション）から拾う機械判定用の統計。秘密・本文は持たない。"""

    recent_days_touched: bool = False
    used_skill_names: set[str] = field(default_factory=set)
    used_agent_names: set[str] = field(default_factory=set)
    used_mcp_tool: bool = False
    max_consecutive_tool_calls: int = 0
    distinct_agent_names_between_humans_2plus: bool = False
    # 参考の数字用（直近30日・名前ごとの使用回数）。名前は自分で定義したスキル／
    # エージェント／コネクタのものだけを数える（既知集合に含まれるものだけ）。
    skill_use_counts: dict = field(default_factory=dict)
    agent_use_counts: dict = field(default_factory=dict)
    connector_use_counts: dict = field(default_factory=dict)


def connector_name_from_tool(tool_name: str) -> Optional[str]:
    """`mcp__<server>__<tool>` からサーバー名（コネクタ名）を取り出す。"""
    if not tool_name.startswith("mcp__"):
        return None
    rest = tool_name[len("mcp__") :]
    parts = rest.split("__")
    if not parts or not parts[0]:
        return None
    return parts[0]


def _is_human_turn(entry: dict) -> bool:
    """type=='user' の行が『人の発言』扱いか（tool_result だけの行は除く）。"""
    message = entry.get("message")
    if not isinstance(message, dict):
        return True
    content = message.get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        if not content:
            return True
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                return True
        return False
    return True


def scan_claude_jsonl(
    path: Path,
    known_skill_names: Iterable[str],
    known_agent_names: Iterable[str],
    now: Optional[datetime] = None,
    window_days: int = 30,
    consecutive_threshold: int = 20,
    max_bytes: int = 200 * 1024 * 1024,
) -> Optional[ConversationStats]:
    """Claude Code の1セッション jsonl を1行ずつ読んで統計だけ返す（本文は保持しない）。"""
    try:
        if path.stat().st_size > max_bytes:
            # 走査はするが、安全のため極端に大きいファイルは丸ごと読み込まず行単位でも続行
            pass
    except OSError:
        return None

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    skill_set = set(known_skill_names)
    agent_set = set(known_agent_names)

    stats = ConversationStats()
    consecutive = 0
    agents_since_last_human: set[str] = set()
    touched_recent = False

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

                ts = entry.get("timestamp")
                entry_dt = _parse_ts(ts)
                if entry_dt is not None and entry_dt >= cutoff:
                    touched_recent = True

                etype = entry.get("type")
                if etype == "user":
                    if _is_human_turn(entry):
                        if len(agents_since_last_human) >= 2:
                            stats.distinct_agent_names_between_humans_2plus = True
                        agents_since_last_human = set()
                        consecutive = 0
                    continue

                if etype != "assistant":
                    continue

                message = entry.get("message")
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue

                had_tool_use_in_block = False
                tool_use_block_count = 0
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    had_tool_use_in_block = True
                    tool_use_block_count += 1
                    name = block.get("name")
                    if not isinstance(name, str):
                        continue
                    is_recent = entry_dt is not None and entry_dt >= cutoff
                    if name.startswith("mcp__"):
                        stats.used_mcp_tool = True
                        if is_recent:
                            conn = connector_name_from_tool(name)
                            if conn:
                                stats.connector_use_counts[conn] = stats.connector_use_counts.get(conn, 0) + 1
                    if name == "Agent":
                        inp = block.get("input")
                        subagent_type = None
                        if isinstance(inp, dict):
                            subagent_type = inp.get("subagent_type") or inp.get("name")
                        if isinstance(subagent_type, str):
                            if is_recent and subagent_type in agent_set:
                                stats.used_agent_names.add(subagent_type)
                                stats.agent_use_counts[subagent_type] = (
                                    stats.agent_use_counts.get(subagent_type, 0) + 1
                                )
                            if subagent_type in agent_set:
                                agents_since_last_human.add(subagent_type)
                    if name == "Skill":
                        inp = block.get("input")
                        skill_name = None
                        if isinstance(inp, dict):
                            skill_name = inp.get("skill")
                        if isinstance(skill_name, str) and skill_name in skill_set and is_recent:
                            stats.used_skill_names.add(skill_name)
                            stats.skill_use_counts[skill_name] = stats.skill_use_counts.get(skill_name, 0) + 1

                if had_tool_use_in_block:
                    consecutive += tool_use_block_count
                    if consecutive > stats.max_consecutive_tool_calls:
                        stats.max_consecutive_tool_calls = consecutive
                    if consecutive >= consecutive_threshold:
                        stats.recent_days_touched = stats.recent_days_touched  # no-op; kept for clarity
    except OSError:
        return None

    if len(agents_since_last_human) >= 2:
        stats.distinct_agent_names_between_humans_2plus = True

    stats.recent_days_touched = touched_recent
    return stats


def _parse_ts(value) -> Optional[datetime]:
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


def mtime_within_days(path: Path, days: int, now: Optional[datetime] = None) -> bool:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return False
    now = now or datetime.now(timezone.utc)
    return (now - mtime) <= timedelta(days=days)


def any_file_mtime_within_days(paths: Iterable[Path], days: int, now: Optional[datetime] = None) -> bool:
    return any(mtime_within_days(p, days, now=now) for p in paths if p.exists())
