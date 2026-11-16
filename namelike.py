"""名前らしい文字列の検査（受付 jirei-box の intake/lib/names.ts と同じ決まりの写し）。

点検の結果の自由文（reason・facts・説明の一覧）に、ファイルの場所・拡張子つきの名前・
英小文字をハイフンや _ でつないだ識別子が紛れていないかを見る。日本語の名前（「仕事/見積」「見積.csv」）も止める。
reasons.py と inventory.py は、この検査に、それぞれもっと厳しい検査を足して使う。
受付の決まりが変わったら、ここと sho-san-share の sharelib/names.py を同じに直す
（共通の見本: tests/fixtures/name_like_cases.json）。
"""

from __future__ import annotations

import re
import unicodedata

# 道具の一般名として説明文に出うるファイル名（個人の名前ではない）
ALLOWED_FILE_NAMES = {"CLAUDE.md", "AGENTS.md", "SKILL.md", "README.md", "settings.json"}

_N = r"[\w-]"  # 名前に使われうる文字（日本語も含む）
_ND = r"[\w.-]"
_FILE_EXT = r"(?:md|json|jsonl|ya?ml|toml|ts|tsx|js|mjs|py|sh|txt|html|csv|sql|env)"
PATH_RE = re.compile(
    r"(?:~|[A-Za-z]:)?" + _ND + r"*(?:[/\\]" + _ND + r"+)+"  # a/b, ~/x, C:\x, 仕事/見積
    + r"|(?<!" + _ND + r")" + _N + _ND + r"*\." + _FILE_EXT + r"(?![A-Za-z0-9_])"  # foo.py, 見積.csv
)
IDENT_RE = re.compile(r"(?<![A-Za-z0-9_-])(?=[a-z0-9_-]*[a-z])[a-z0-9]+(?:[-_]+[a-z0-9]+)+(?![A-Za-z0-9_-])")
_LEADING_NON_ASCII_RE = re.compile(r"^[^\x00-\x7f]+")


def _is_allowed_file_name(m: str) -> bool:
    return m in ALLOWED_FILE_NAMES or _LEADING_NON_ASCII_RE.sub("", m) in ALLOWED_FILE_NAMES


def scan_name_like(text: str) -> dict:
    """{種類: 件数}（name_like_identifier・file_path_like）。該当なしの種類は入れない。"""
    t = unicodedata.normalize("NFKC", text)
    paths = sum(1 for m in PATH_RE.finditer(t) if not _is_allowed_file_name(m.group(0)))
    idents = len(IDENT_RE.findall(PATH_RE.sub(" ", t)))
    out = {}
    if idents:
        out["name_like_identifier"] = idents
    if paths:
        out["file_path_like"] = paths
    return out
