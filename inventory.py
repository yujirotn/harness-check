"""ハーネス点検 — スキル・エージェント・コネクタの「説明の一覧」（result.json の inventory）。

名前は出さない。出すのは、AIが書いた「何をするものか」の1文（summary）と、使われた回数だけ。
AIの書いた1文は、手元にある名前の一覧と突き合わせ、名前・場所・識別子らしい語などが
1つでも当たれば捨てて、決まった文（FALLBACK_SUMMARY）に置き換える。

日本語の社名・人名は機械では見つけきれない。その分は、送るスキルの下見で
説明の一覧を本人に全部見せて同意を取ることで補う（docs/SPEC.md 5-9）。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

KINDS = ("skills", "agents", "connectors")
CATEGORIES = ("集計", "資料", "メール", "相談", "調べもの", "自動化", "その他")
DEFAULT_CATEGORY = "その他"
FALLBACK_SUMMARY = "（説明を作れませんでした）"
MAX_ROWS = 300
MAX_SUMMARY_CHARS = 80

# 説明に出てよい英字の語（一般の呼び名だけ）。これ以外の英字の並びは、名前らしいものとして止める
ALLOWED_ASCII_WORDS = {"AI", "PDF", "CSV", "HTML", "Web", "SNS", "PC", "3D"}

_FILE_EXT = r"(?:md|json|jsonl|ya?ml|toml|ts|tsx|js|mjs|py|sh|txt|html|csv|sql|env)"
_CHECKS = [
    ("file_path_like", re.compile(r"(?:~|[A-Za-z]:)?[\w.-]*(?:[/\\][\w.-]+)+", re.ASCII)),
    ("file_path_like", re.compile(r"(?<![\w.-])[\w-]*\." + _FILE_EXT + r"(?!\w)", re.ASCII)),
    ("name_like_identifier",
     re.compile(r"(?<![A-Za-z0-9_-])(?=[a-z0-9_-]*[a-z])[a-z0-9]+(?:[-_]+[a-z0-9]+)+(?![A-Za-z0-9_-])")),
    ("camel_case", re.compile(r"[a-z][A-Z]|[A-Z]{2,}[a-z]")),
    ("path_char", re.compile(r"[/\\~]")),
    ("url", re.compile(r"(?i)(?:[a-z][a-z0-9+.-]*://|www\.)")),
    ("email", re.compile(r"@")),
    ("joined_identifier", re.compile(r"[A-Za-z0-9][-_.:][A-Za-z0-9]")),
    ("long_digits", re.compile(r"[0-9][0-9-]{6,}[0-9]")),
    ("markup", re.compile(r"[<>`{}\[\]|$#*=]")),
]
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*")
_SPLIT_RE = re.compile(r"[\s\-_./\\・:@()（）\[\]]+")
_DROP_FOR_COMPARE_RE = re.compile(r"[\s\-_./\\・]+")

# 名前との突き合わせで、短すぎて普通の言葉と区別できないものは使わない
MIN_NEEDLE_CHARS_NON_ASCII = 3
MIN_NEEDLE_CHARS_ASCII = 3


def normalize_for_compare(text: str) -> str:
    """大文字小文字・全角半角・ハイフンや空白の違いをならす。"""
    return _DROP_FOR_COMPARE_RE.sub("", unicodedata.normalize("NFKC", text).lower())


def _is_ascii(s: str) -> bool:
    return all(ord(c) < 128 for c in s)


def name_needles(names: Iterable[str]) -> set[str]:
    """突き合わせに使う文字列: 名前そのものと、その主な部分（区切りで割ったもの）。

    短すぎるもの（日本語2文字以下・英数字2文字以下）と、説明に出てよい一般語は使わない。
    英字の名前は、そもそも説明の英字が一般語に限られているので、名前の部分が漏れても止まる。
    """
    allowed = {w.lower() for w in ALLOWED_ASCII_WORDS}
    out: set[str] = set()
    for raw in names:
        if not isinstance(raw, str) or not raw:
            continue
        candidates = [raw] + [p for p in _SPLIT_RE.split(raw) if p]
        for c in candidates:
            n = normalize_for_compare(c)
            if not n or n in allowed:
                continue
            limit = MIN_NEEDLE_CHARS_ASCII if _is_ascii(n) else MIN_NEEDLE_CHARS_NON_ASCII
            if len(n) >= limit:
                out.add(n)
    return out


def check_summary(text, needles: set[str]) -> list[str]:
    """説明の1文に当たったものの種類。無ければ空。"""
    if not isinstance(text, str):
        return ["not_text"]
    found: list[str] = []
    if not (1 <= len(text) <= MAX_SUMMARY_CHARS):
        found.append("length")
    if any(unicodedata.category(c) in ("Cc", "Cf") for c in text):
        found.append("control")
    t = unicodedata.normalize("NFKC", text)
    for kind, rx in _CHECKS:
        if rx.search(t) and kind not in found:
            found.append(kind)
    if any(w not in ALLOWED_ASCII_WORDS for w in _ASCII_WORD_RE.findall(t)):
        found.append("ascii_word")
    flat = normalize_for_compare(text)
    if any(n in flat for n in needles):
        found.append("name_match")
    return found


def _ai_entry(ai_inventory, kind: str, iid: str) -> dict:
    if not isinstance(ai_inventory, dict):
        return {}
    by_kind = ai_inventory.get(kind)
    if not isinstance(by_kind, dict):
        return {}
    e = by_kind.get(iid)
    return e if isinstance(e, dict) else {}


def build_inventory(skeleton: Optional[dict], ai_inventory, needles: Optional[set]) -> tuple[dict, dict, dict]:
    """facts.json の inventory（id と回数だけ）と、AIの書いた説明から、result.json の inventory を作る。

    needles が None（名前の一覧が読めない）のときは、どの説明も確かめられないので全部置き換える。
    戻り値: (inventory, 切った数, 置き換えた数)
    """
    inventory: dict = {}
    truncated: dict = {}
    replaced: dict = {}
    skeleton = skeleton if isinstance(skeleton, dict) else {}
    for kind in KINDS:
        rows = []
        n_replaced = 0
        for entry in skeleton.get(kind) or []:
            if not isinstance(entry, dict):
                continue
            used = entry.get("used_30d")
            used = used if isinstance(used, int) and not isinstance(used, bool) and used >= 0 else None
            ai = _ai_entry(ai_inventory, kind, str(entry.get("id")))
            summary = ai.get("summary")
            if needles is None or check_summary(summary, needles):
                summary = FALLBACK_SUMMARY
                n_replaced += 1
            row = {"summary": summary}
            if kind == "skills":
                cat = ai.get("category")
                row["category"] = cat if cat in CATEGORIES and summary != FALLBACK_SUMMARY else DEFAULT_CATEGORY
            row["used_30d"] = used
            rows.append(row)
        # 並び: 使われた回数の多い順（null は最後）→ 説明の文字順。名前の順は使わない
        rows.sort(key=lambda r: (-(r["used_30d"] if r["used_30d"] is not None else -1), r["summary"],
                                 r.get("category", "")))
        inventory[kind] = rows[:MAX_ROWS]
        truncated[kind] = max(0, len(rows) - MAX_ROWS)
        replaced[kind] = n_replaced
    return inventory, truncated, replaced
