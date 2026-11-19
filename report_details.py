"""レポート専用の一覧とフォルダ構成。入力の名前・パス・文章は返さない。"""

from __future__ import annotations

import os
import re
from pathlib import Path

from readers import common

TOOL_LABELS = {"claude_code": "Claude Code", "codex": "Codex"}
SCOPE_LABELS = {"personal": "個人", "workspace": "書庫（作業フォルダ）", "plugins": "プラグインキャッシュ"}
KIND_LABELS = {"skills": "スキル", "agents": "エージェント"}
ROOT_LABELS = {"workspace": "作業フォルダ", **TOOL_LABELS}

# 上から3階層。ルートそのものは階層に含めない。
TREE_DEPTH = 3
TREE_FILE_LIMIT = 24
TREE_DIRECTORY_LIMIT = 12
HEADER_BYTES = 8192

# 説明の先頭を判別し、定型文だけを表示する。入力の部分文字列は出さない。
PURPOSES = (
    ("review", r"レビュー|見直し|\breview\b|\baudit\b", "成果物や設定を確認し、問題点を見つける"),
    ("mail", r"メール|\b(?:email|inbox)\b", "メールの内容を確認したり、下書きを作ったりする"),
    ("data", r"集計|表計算|\b(?:spreadsheet|csv|xlsx)\b", "表や数値を扱い、集計や分析を行う"),
    ("document", r"文書|資料|\b(?:documents?|slides?|pdf|docx)\b", "文書や資料の作成や編集を支援する"),
    ("research", r"調査|検索|\b(?:search|research)\b", "情報を探して整理する"),
    ("visual", r"画像|図解|可視化|\b(?:images?|visuali[sz]\w*|charts?)\b", "画像や図を作成したり編集したりする"),
    ("desktop", r"画面操作|\b(?:GUI|browser)\b", "アプリやブラウザの画面を操作する"),
    ("coordination", r"複数のエージェント|\b(?:worker agents|worktrees)\b", "並行する作業を管理し、結果を取りまとめる"),
    ("automation", r"自動化|\b(?:automat\w*|workflows?)\b", "繰り返し行う作業を自動化する"),
    ("development", r"実装|開発|\b(?:code|coding|testing|repository)\b", "コードの実装や検証を支援する"),
)
PURPOSE_LABELS = {key: label for key, _, label in PURPOSES}

_DESCRIPTION = re.compile(r"^description\s*:\s*(.*)$")


def _description(path: Path) -> str:
    """定義ファイルの冒頭だけを読む。本文や設定中の参照先は読まない。"""
    if path.is_symlink() or not path.is_file():
        return ""
    try:
        with path.open("rb") as fh:
            header = fh.read(HEADER_BYTES).decode("utf-8-sig", errors="replace")
    except OSError:
        return ""

    if path.suffix == ".toml":
        # 先頭にあるトップレベルの説明を対象にする。参照先は展開しない。
        scalars = common.toml_top_level_scalars(header)
        return scalars.get("description", "")

    lines = header.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in ("---", "..."):
            break
        match = _DESCRIPTION.match(line)
        if match:
            description = [match[1]]
            for continuation in lines[index + 1:]:
                if continuation and not continuation[0].isspace():
                    break
                description.append(continuation.strip())
            return " ".join(description)
    return ""


def _purpose(path: Path) -> str:
    description = _description(path)[:320]
    # 複数の用途がある場合、説明文で最初に言及した用途を使う。
    matches = []
    for key, pattern, _ in PURPOSES:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            matches.append((match.start(), key))
    return min(matches)[1] if matches else "unknown"


def _entries(directory: Path) -> list[Path]:
    if directory.is_symlink():
        return []
    try:
        return sorted(directory.iterdir())
    except OSError:
        return []


def _dirs(directory: Path) -> list[Path]:
    return [path for path in _entries(directory)
            if not path.name.startswith(".") and not path.is_symlink() and path.is_dir()]


def _skill_definitions(base: Path, shared_skills: tuple[Path, ...]):
    for entry in _entries(base):
        if entry.name.startswith("."):
            continue
        if entry.is_symlink():
            try:
                entry = entry.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if entry.parent not in shared_skills:
                continue
        yield entry / "SKILL.md"


def _definition_paths(base: Path, kind: str, tool: str, shared_skills: tuple[Path, ...]):
    if base.is_symlink():
        return
    if kind == "skills":
        candidates = _skill_definitions(base, shared_skills)
    else:
        extensions = {".md", ".toml"} if tool == "codex" else {".md"}
        candidates = [path for path in _entries(base)
                      if not path.name.startswith(".") and path.suffix.lower() in extensions]
    for path in candidates:
        if not path.is_symlink() and path.is_file():
            yield path


def _plugin_roots(tool_home: Path):
    """標準のキャッシュ階層のローカルコピーを対象とする。複数版も別々に数える。"""
    plugins = tool_home / "plugins"
    if plugins.is_symlink():
        return
    for marketplace in _dirs(plugins / "cache"):
        for plugin in _dirs(marketplace):
            yield from _dirs(plugin)


def _catalog(tool: str, tool_home: Path, workdir: Path, home: Path) -> list[dict]:
    project_config = workdir / (".claude" if tool == "claude_code" else ".codex")
    definitions = {
        "personal": {kind: [tool_home / kind] for kind in KIND_LABELS},
        "workspace": {kind: [project_config / kind] if not project_config.is_symlink() else []
                      for kind in KIND_LABELS},
        "plugins": {kind: [] for kind in KIND_LABELS},
    }
    if tool == "codex":
        for scope, root in (("personal", home), ("workspace", workdir)):
            agents_root = root / ".agents"
            if not agents_root.is_symlink():
                definitions[scope]["skills"].append(agents_root / "skills")

    for plugin in _plugin_roots(tool_home):
        for kind in KIND_LABELS:
            definitions["plugins"][kind].append(plugin / kind)

    groups = []
    for scope, bases in definitions.items():
        group = {"tool": tool, "scope": scope}
        shared_skills = ()
        if scope != "plugins":
            shared_root = (home if scope == "personal" else workdir) / ".agents"
            if not shared_root.is_symlink() and not (shared_root / "skills").is_symlink():
                shared_skills = (shared_root / "skills",)
        for kind, locations in bases.items():
            paths = dict.fromkeys(path for base in locations
                                  for path in _definition_paths(base, kind, tool, shared_skills))
            group[kind] = [_purpose(path) for path in paths]
        groups.append(group)
    return groups


def _directory_tree(directory: Path, out_dir: Path, depth: int) -> dict:
    dirs = []
    files = 0
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name == ".git" or Path(entry.path) == out_dir:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    dirs.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    files += 1
    except OSError:
        return {"unreadable": True}
    children = []
    if depth and files < TREE_FILE_LIMIT and len(dirs) <= TREE_DIRECTORY_LIMIT:
        children = [_directory_tree(path, out_dir, depth - 1) for path in sorted(dirs)]
    return {"files": files, "directories": len(dirs), "children": children}


def collect_report_details(
    workdir: Path, claude_home: Path, codex_home: Path, home: Path,
    out_dir: Path, tools_detected: dict,
) -> dict:
    groups = []
    roots = {"workspace": _directory_tree(workdir, out_dir, TREE_DEPTH)}
    for tool, tool_home in (("claude_code", claude_home), ("codex", codex_home)):
        if tools_detected.get(tool):
            groups.extend(_catalog(tool, tool_home, workdir, home))
            roots[tool] = _directory_tree(tool_home, out_dir, TREE_DEPTH)
    return {"inventory": groups, "trees": roots}
