"""ハーネス点検 — 項目ごとの「なぜそう判定したか」（result.json schema_version 3 の reason・facts）。

決まった文の型に、整数と「あり／なし」などの決まった語だけを差し込んで作る。
名前・パス・本文・AIが書いた文は一切差し込まない（差し込める値が無い作りにしてある）。
仕上がった文は find_forbidden で検査し、当たったら項目ごとの定型文に置き換える（二重の守り）。

文の型の一覧はこのファイルの ITEM_BUILDERS（項目ID → 組み立て関数）。
reason は「今の状態」と「基準との比べ」だけを書く。良い・悪いの意味づけは書かない。
"""

from __future__ import annotations

import re
import unicodedata

from namelike import scan_name_like
from typing import Callable, Optional

MAX_REASON_CHARS = 300
MAX_FACTS = 6
MAX_LABEL_CHARS = 40
MAX_VALUE_CHARS = 60

TOOL_LABELS = {"claude_code": "Claude Code", "codex": "Codex"}
TOOL_ORDER = ("claude_code", "codex")

# ---------------------------------------------------------------------------
# 禁止のものの検査
# ---------------------------------------------------------------------------

# 文に出てよい英字の語（道具の呼び名だけ）。これ以外の英字の並びは、名前らしいものとして止める
ALLOWED_ASCII_WORDS = {"Claude", "Code", "Codex", "Git", "AI"}

_CHECKS = [
    # 受付と同じ検査（namelike）に加えて、それより広く止めるもの
    ("path_char", re.compile(r"[/\\~]")),
    ("url", re.compile(r"(?i)(?:[a-z][a-z0-9+.-]*://|www\.)")),
    ("email", re.compile(r"@")),
    ("joined_identifier", re.compile(r"[A-Za-z0-9][-_.:][A-Za-z0-9]")),
    ("long_digits", re.compile(r"[0-9][0-9-]{8,}[0-9]")),
    ("markup", re.compile(r"[<>`{}\[\]|$#]")),
]
_ASCII_WORD_RE = re.compile(r"[A-Za-z]+")


def find_forbidden(text: str) -> list[str]:
    """禁止のもの（パス・拡張子つきの名前・URL・メール・英数字の識別子など）の種類を返す。無ければ空。"""
    t = unicodedata.normalize("NFKC", text)
    found = sorted(scan_name_like(text))  # 受付と同じ検査（日本語のパス・拡張子つきの名前も止める）
    for kind, rx in _CHECKS:
        if rx.search(t) and kind not in found:
            found.append(kind)
    if any(w not in ALLOWED_ASCII_WORDS for w in _ASCII_WORD_RE.findall(t)):
        found.append("ascii_word")
    if any(unicodedata.category(c) in ("Cc", "Cf") for c in t):
        found.append("control")
    return found


_FALLBACK = {
    "pass": "この項目は基準を満たしています。",
    "fail": "この項目は基準を満たしていません。",
    "unmeasured": "この項目は判定できませんでした。",
}


def _facts_ok(facts) -> bool:
    if not isinstance(facts, list) or len(facts) > MAX_FACTS:
        return False
    for f in facts:
        if not isinstance(f, dict) or set(f) != {"label", "value"}:
            return False
        label, value = f["label"], f["value"]
        if not (isinstance(label, str) and 1 <= len(label) <= MAX_LABEL_CHARS):
            return False
        if not (isinstance(value, str) and 1 <= len(value) <= MAX_VALUE_CHARS):
            return False
        if find_forbidden(label) or find_forbidden(value):
            return False
    return True


def sanitize(iid: str, status: str, reason, facts) -> tuple[str, list, bool]:
    """検査に通らなければ、定型文と空の facts に置き換える。戻り値の3つ目は置き換えたかどうか。"""
    reason_ok = isinstance(reason, str) and 1 <= len(reason) <= MAX_REASON_CHARS and not find_forbidden(reason)
    if reason_ok and _facts_ok(facts):
        return reason, list(facts), False
    return _FALLBACK.get(status, _FALLBACK["unmeasured"]), [], True


# ---------------------------------------------------------------------------
# 文の部品
# ---------------------------------------------------------------------------

MEETS = "という基準を満たしています"
NOT_MEETS = "という基準を満たしていません"
CANNOT = "判定できませんでした"
CODEX_LOG_UNREADABLE = "会話の記録が標準の機能で読めない形のため、" + CANNOT
NO_TOOL = "Claude CodeもCodexも見つからなかったため、" + CANNOT


def F(label: str, value) -> dict:
    return {"label": label, "value": str(value)}


def yn(b) -> str:
    return "あり" if b else "なし"


def _n(v, key: str) -> int:
    x = v.get(key, 0) if isinstance(v, dict) else 0
    return int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else 0


class Part:
    """1つの道具（または道具共通）ぶんの1文と facts。"""

    def __init__(self, sentence: str, facts: Optional[list] = None):
        self.sentence = sentence
        self.facts = facts or []


def _ai_state(entry) -> tuple[str, int]:
    """AIの二重判定の状態: yes / no / split / missing と、根拠の行の数。文は使わない。"""
    if not isinstance(entry, dict):
        return "missing", 0
    a1, a2 = entry.get("answer_1"), entry.get("answer_2")
    lines = entry.get("evidence_lines")
    n_lines = len(lines) if isinstance(lines, list) else 0
    if not (isinstance(a1, bool) and isinstance(a2, bool)):
        return "missing", 0
    if a1 != a2:
        return "split", n_lines
    return ("yes" if a1 else "no"), n_lines


def _ai_facts(state: str, n_lines: int) -> list:
    answer = {"yes": "2回とも、はい", "no": "2回とも、いいえ", "split": "1回目と2回目で違う答え", "missing": "記録なし"}
    out = [F("AIの判定", answer[state])]
    if state in ("yes", "no") and n_lines > 0:
        out.append(F("根拠にした行", f"{n_lines}か所"))
    return out


def _ai_unmeasured(state: str) -> str:
    if state == "split":
        return "AIが2回読んだ答えが食い違ったため、" + CANNOT + "（食い違ったときは判定しない決まりです）"
    return "AIの判定が記録されていなかったため、" + CANNOT


# ---------------------------------------------------------------------------
# 項目ごとの文の型（道具ごと）。引数: v＝その道具の facts、r＝その道具の判定、ai＝AIの答え
# ---------------------------------------------------------------------------


def _f1(tool, v, r, ai):
    n = _n(v, "count")
    crit = F("基準", "1件以上")
    if r["pass"]:
        return Part(f"作業フォルダからGitの一番上のフォルダまでに指示書が{n}件あり、1件以上{MEETS}", [F("指示書の数", f"{n}件"), crit])
    return Part(f"作業フォルダからGitの一番上のフォルダまでに指示書が見つからず、1件以上{NOT_MEETS}", [F("指示書の数", "0件"), crit])


def _f2(tool, v, r, ai):
    files = _n(v, "file_count")
    if not r["measured"]:
        return Part("毎回読まれる指示ファイルが見つからなかったため、" + CANNOT, [F("指示ファイルの数", "0件")])
    if tool == "codex":
        total, limit = _n(v, "total_bytes"), _n(v, "limit_bytes") or 32768
        facts = [F("読まれる指示書の数", f"{files}件"), F("合計の大きさ", f"{total}バイト"), F("目安", f"合計{limit}バイト未満")]
        if r["pass"]:
            return Part(f"読まれる指示書が{files}件で合計{total}バイトあり、合計{limit}バイト未満という目安に収まっています", facts)
        return Part(f"読まれる指示書が{files}件で合計{total}バイトあり、合計{limit}バイト未満という目安を超えています", facts)
    mx, over, limit = _n(v, "max_lines"), _n(v, "over_count"), _n(v, "limit_lines") or 200
    facts = [F("指示ファイルの数", f"{files}件"), F("いちばん長い指示ファイル", f"{mx}行"),
             F("目安を超えたファイル", f"{over}件"), F("目安", f"{limit}行未満")]
    if r["pass"]:
        return Part(f"毎回読まれる指示ファイルが{files}件あり、いちばん長いものは{mx}行で、どれも{limit}行未満という目安に収まっています", facts)
    return Part(f"毎回読まれる指示ファイルが{files}件あり、いちばん長いものは{mx}行で、{limit}行未満という目安を超えるものが{over}件あります", facts)


def _ai_item(target_word: str, none_text: str, yes_text: str, no_text: str):
    """F3・F4・F7（AIだけが判定する項目）の文の型。"""

    def build(tool, v, r, ai):
        n = _n(v, "target_count")
        if not v.get("target_found"):
            return Part(none_text + "ため、" + CANNOT, [F("AIが読む対象", "0件")])
        state, n_lines = _ai_state(ai)
        facts = [F("AIが読んだ数", f"{n}件")] + _ai_facts(state, n_lines)
        if state == "yes":
            return Part(f"{target_word}{n}件をAIが2回読み、2回とも、{yes_text}と判定しました", facts)
        if state == "no":
            return Part(f"{target_word}{n}件をAIが2回読み、2回とも、{no_text}と判定しました", facts)
        return Part(_ai_unmeasured(state), facts)

    return build


_f3 = _ai_item("作業フォルダの指示書", "作業フォルダの指示書が見つからなかった",
               "指示が具体的で、守れたか確かめられる書き方になっている",
               "具体的で守れたか確かめられる書き方にはなっていない")
_f4 = _ai_item("起動時に読まれる指示ファイル", "起動時に読まれる指示ファイルが見つからなかった",
               "互いに矛盾する指示は無い", "互いに矛盾する指示がある")
_f7 = _ai_item("自分で用意したスキルの説明文", "自分で用意したスキルが無い",
               "どれにも「何をするか」と「いつ使うか」が書かれている",
               "「何をするか」か「いつ使うか」が欠けているものがある")


def _own_count(word: str, unit: str):
    def build(tool, v, r, ai):
        n = _n(v, "count")
        crit = F("基準", f"1{unit}以上")
        if r["pass"]:
            return Part(f"{word}が{n}{unit}あり、1{unit}以上{MEETS}", [F(f"{word}の数", f"{n}{unit}"), crit])
        return Part(f"{word}が見つからず、1{unit}以上{NOT_MEETS}", [F(f"{word}の数", f"0{unit}"), crit])

    return build


_f5 = _own_count("自分で用意したスキル", "本")
_f8 = _own_count("自分で定義したエージェント", "件")


def _usage(word: str, unit: str, verb: str):
    """F6・F9（直近30日に使われたか）。"""

    def build(tool, v, r, ai):
        if tool == "codex":
            return Part(CODEX_LOG_UNREADABLE)
        own, used, total, sessions = _n(v, "own_count"), _n(v, "count"), _n(v, "use_total"), _n(v, "session_count")
        crit = F("基準", "直近30日に1回以上")
        if not r["measured"]:
            if own == 0:
                return Part(f"{word}が無いため、" + CANNOT, [F(f"{word}の数", f"0{unit}")])
            return Part("会話の記録が見つからなかったため、" + CANNOT, [F("会話の記録", "0件")])
        facts = [F(f"{word}の数", f"{own}{unit}"), F(f"直近30日に{verb}数", f"{used}{unit}"),
                 F("直近30日の回数の合計", f"{total}回"), crit]
        if r["pass"]:
            return Part(f"直近30日に、{word}{own}{unit}のうち{used}{unit}が合計{total}回{verb[:-1]}、1回以上{MEETS}", facts)
        return Part(f"直近30日に、{word}{own}{unit}が{verb}記録は0回で、1回以上{NOT_MEETS}", facts)

    return build


_f6 = _usage("自分で用意したスキル", "本", "使われた")
_f9 = _usage("自分で定義したエージェント", "件", "使われた")


def _f10(tool, v, r, ai):
    crit = F("基準", "1つ以上")
    if tool == "codex":
        if r["pass"]:
            return Part(f"設定ファイルにコネクタの定義があり、1つ以上{MEETS}", [F("コネクタの定義", "あり"), crit])
        return Part(f"設定ファイルにコネクタの定義が無く、1つ以上{NOT_MEETS}", [F("コネクタの定義", "なし"), crit])
    n, used = _n(v, "config_count"), bool(v.get("used_in_records"))
    facts = [F("設定にあるコネクタの数", f"{n}個"), F("会話の記録での呼び出し", yn(used)), crit]
    if r["pass"] and n > 0:
        return Part(f"設定にコネクタが{n}個あり、1つ以上{MEETS}", facts)
    if r["pass"]:
        return Part(f"設定にはコネクタがありませんが、会話の記録にコネクタの呼び出しがあり、1つ以上{MEETS}", facts)
    return Part(f"設定にもコネクタが無く、会話の記録にもコネクタの呼び出しが無いため、1つ以上{NOT_MEETS}", facts)


def _f11(tool, v, r, ai):
    if tool == "codex":
        return Part(CODEX_LOG_UNREADABLE)
    calls, sessions = _n(v, "calls_30d"), _n(v, "session_count")
    if not r["measured"]:
        return Part("会話の記録が見つからなかったため、" + CANNOT, [F("会話の記録", "0件")])
    crit = F("基準", "直近30日に1回以上")
    if r["pass"] and calls > 0:
        return Part(f"直近30日に、コネクタの呼び出しが{calls}回あり、1回以上{MEETS}", [F("直近30日の呼び出し", f"{calls}回"), crit])
    if r["pass"]:
        # 判定は「直近30日に動いた会話にコネクタの呼び出しがある」。回数（日付つきで数えたもの）は0のことがある。
        # 文と数字が食い違わないよう、このときは回数を出さない
        return Part(f"直近30日に動いた会話の中で、コネクタが使われた記録があり（回数は数えられませんでした）、1回以上{MEETS}",
                    [F("直近30日に動いた会話での使用", "あり"), crit])
    return Part(f"直近30日に、コネクタの呼び出しは0回で、1回以上{NOT_MEETS}", [F("直近30日の呼び出し", f"{calls}回"), crit])


def _rule_count(what: str):
    """S2・S3（Claude Code）: 禁止か承認の設定の行数。"""

    def build(tool, v, r, ai):
        n = _n(v, "rule_count")
        facts = [F("該当する設定", f"{n}行"), F("基準", "1行以上")]
        if r["pass"]:
            return Part(f"禁止か承認の設定に、{what}行が{n}行あり、1行以上{MEETS}", facts)
        return Part(f"禁止か承認の設定に、{what}行が無く、1行以上{NOT_MEETS}", facts)

    return build


_s2_cc = _rule_count("秘密ファイルの読み取りを止める")
_s3_cc = _rule_count("削除・強制上書き・送信・公開のどれかを対象にした")


def _s2(tool, v, r, ai):
    if tool == "codex":
        return Part("この項目を設定から確かめる方法が無いため、" + CANNOT)
    return _s2_cc(tool, v, r, ai)


def _codex_flags(v) -> list:
    return [F("承認の方式が「確認しない」", "はい" if v.get("never_ask") else "いいえ"),
            F("制限なしの実行モード", "はい" if v.get("full_access") else "いいえ")]


CODEX_NO_SIGNAL = "設定ファイルに承認の方式も実行モードも書かれていないため、" + CANNOT


def _s3(tool, v, r, ai):
    if tool != "codex":
        return _s3_cc(tool, v, r, ai)
    if not r["measured"]:
        return Part(CODEX_NO_SIGNAL)
    facts = _codex_flags(v) + [F("基準", "どちらも、いいえ")]
    if r["pass"]:
        return Part(f"承認の方式は「確認しない」ではなく、制限なしの実行モードでもないため、基準を満たしています", facts)
    if v.get("never_ask") and v.get("full_access"):
        which = "承認の方式が「確認しない」で、実行モードも制限なし"
    elif v.get("never_ask"):
        which = "承認の方式が「確認しない」"
    else:
        which = "実行モードが制限なし"
    return Part(f"{which}になっているため、どちらにも当てはまらないという基準を満たしていません", facts)


def _s4(tool, v, r, ai):
    if tool == "codex":
        if not r["measured"]:
            return Part(CODEX_NO_SIGNAL)
        facts = _codex_flags(v) + [F("基準", "両方が、はいではない")]
        if r["pass"]:
            return Part("「確認しない」と「制限なし」の組み合わせにはなっておらず、基準を満たしています", facts)
        return Part("「確認しない」と「制限なし」の組み合わせになっていて、基準を満たしていません", facts)
    mode_set = bool(v.get("mode_set"))
    facts = [F("既定のモードの指定", yn(mode_set)), F("確認をすべて省くモード", "はい" if not r["pass"] else "いいえ"),
             F("基準", "確認をすべて省くモードではない")]
    if r["pass"] and not mode_set:
        return Part("既定のモードの指定は無く、確認をすべて省くモードではないため、基準を満たしています", facts)
    if r["pass"]:
        return Part("既定のモードは確認をすべて省くモードではなく、基準を満たしています", facts)
    return Part("既定のモードが確認をすべて省くモードになっていて、基準を満たしていません", facts)


def _d1(tool, v, r, ai):
    if tool == "codex":
        if not r["measured"]:
            return Part(CODEX_NO_SIGNAL)
        facts = [F("承認の方式が毎回確認する方式", "はい" if v.get("always_ask") else "いいえ"),
                 F("基準", "毎回確認する方式ではない")]
        if r["pass"]:
            return Part("承認の方式は毎回確認する方式ではなく、基準を満たしています", facts)
        return Part("承認の方式が毎回確認する方式になっていて、基準を満たしていません", facts)
    n, auto = _n(v, "allow_count"), bool(v.get("auto_mode"))
    facts = [F("許可の設定", f"{n}行"), F("自動で判断するモード", "はい" if auto else "いいえ"),
             F("基準", "許可の設定が1行以上か、自動で判断するモード")]
    if r["pass"] and n > 0:
        return Part(f"確認なしで通す許可の設定が{n}行あり、1行以上{MEETS}", facts)
    if r["pass"]:
        return Part("許可の設定はありませんが、既定のモードが自動で判断するモードのため、基準を満たしています", facts)
    return Part("許可の設定が無く、既定のモードも自動で判断するモードではないため、基準を満たしていません", facts)


def _d2(tool, v, r, ai):
    defs = _n(v, "definition_count")
    facts = [F("定時実行の定義", f"{defs}件"), F("直近30日に動いた跡", yn(v.get("recent"))),
             F("基準", "直近30日に動いた")]
    if defs == 0:
        return Part("定時実行の定義が見つからなかったため、" + CANNOT, [F("定時実行の定義", "0件")])
    if v.get("recent"):
        return Part(f"定時実行の定義が{defs}件あり、直近30日に出力かログが更新されていて、基準を満たしています", facts)
    answer = ai.get("answer") if isinstance(ai, dict) else None
    if isinstance(answer, bool):
        facts = facts[:2] + [F("本人の回答", "動いた" if answer else "動いていない"), facts[2]]
        if answer:
            return Part(f"定時実行の定義が{defs}件あり、動いた跡は読めませんでしたが、本人の回答では直近30日に動いていて、基準を満たしています", facts)
        return Part(f"定時実行の定義が{defs}件ありますが、本人の回答では直近30日に動いておらず、基準を満たしていません", facts)
    return Part(f"定時実行の定義が{defs}件ありますが、直近30日に動いた跡を読めず、本人の回答も無かったため、" + CANNOT, facts)


def _d3(tool, v, r, ai):
    hooks = _n(v, "stop_hook_count")
    if tool == "codex":
        machine = [F("終了時に動くフック", f"{hooks}件")]
        machine_text = "終了時に動くフックが無く"
    else:
        agents = _n(v, "readonly_agent_count")
        machine = [F("終了時に動くフック", f"{hooks}件"), F("読むだけの確認役のエージェント", f"{agents}件")]
        machine_text = "終了時に動くフックも、読むだけの確認役のエージェントも無く"
    if not v.get("needs_ai_fallback"):
        if tool == "codex":
            return Part(f"終了時に動くフックがあり、1件以上{MEETS}", machine + [F("基準", "1件以上")])
        if hooks == 0 and agents == 0:
            # 終了時のフックの設定の項目はあるが、中身が数えられなかった（判定は「設定がある」で通っている）
            return Part(f"終了時に動くフックの設定があり、どちらか1件以上{MEETS}",
                        [F("終了時に動くフックの設定", "あり"), F("基準", "どちらか1件以上")])
        return Part(f"終了時に動くフックが{hooks}件、読むだけの確認役のエージェントが{agents}件で、どちらか1件以上{MEETS}",
                    machine + [F("基準", "どちらか1件以上")])
    state, n_lines = _ai_state(ai)
    facts = machine + _ai_facts(state, n_lines)
    if state == "yes":
        return Part(f"{machine_text}、指示書をAIが2回読み、2回とも「終える前に確かめる」決まりが書かれていると判定しました", facts)
    if state == "no":
        return Part(f"{machine_text}、指示書をAIが2回読み、2回とも「終える前に確かめる」決まりは書かれていないと判定しました", facts)
    return Part(f"{machine_text}、" + _ai_unmeasured(state), facts)


def _d4(tool, v, r, ai):
    if tool == "codex":
        return Part(CODEX_LOG_UNREADABLE)
    own, hits, sessions = _n(v, "own_count"), _n(v, "hit_count"), _n(v, "session_count")
    if not r["measured"]:
        if own == 0:
            return Part("自分で定義したエージェントが無いため、" + CANNOT, [F("自分で定義したエージェントの数", "0件")])
        return Part("会話の記録が見つからなかったため、" + CANNOT, [F("会話の記録", "0件")])
    facts = [F("該当する会話", f"{hits}件"), F("調べた会話の記録", f"{sessions}件"), F("基準", "1件以上")]
    if r["pass"]:
        return Part(f"人の発言を挟まずに自作のエージェントが2種類以上続けて動いた会話が{hits}件あり、1件以上{MEETS}", facts)
    return Part(f"人の発言を挟まずに自作のエージェントが2種類以上続けて動いた会話は0件で、1件以上{NOT_MEETS}", facts)


def _d5(tool, v, r, ai):
    if tool == "codex":
        return Part(CODEX_LOG_UNREADABLE)
    mx, th = _n(v, "max_consecutive"), _n(v, "threshold") or 20
    if not r["measured"]:
        return Part("会話の記録が見つからなかったため、" + CANNOT, [F("会話の記録", "0件")])
    facts = [F("いちばん長く続いた回数", f"{mx}回"), F("基準", f"{th}回以上")]
    if r["pass"]:
        return Part(f"直近30日の会話で、人の発言を挟まずに続いた道具の呼び出しは最長{mx}回で、{th}回以上{MEETS}", facts)
    return Part(f"直近30日の会話で、人の発言を挟まずに続いた道具の呼び出しは最長{mx}回で、{th}回以上{NOT_MEETS}", facts)


# ---------------------------------------------------------------------------
# 道具共通の項目（combined）。引数: c＝combined の facts、status、ai＝AIの答え
# ---------------------------------------------------------------------------


def _s1(c, status, ai):
    if status == "unmeasured":
        return Part("キーを走査する対象が見つからなかったため、" + CANNOT)
    repo, config = c.get("repo") or {}, c.get("config") or {}
    rn = sum(int(x) for x in (repo.get("counts_by_kind") or {}).values())
    cn = sum(int(x) for x in (config.get("counts_by_kind") or {}).values())
    rs, cs = _n(repo, "scanned_file_count"), _n(config, "scanned_file_count")
    skipped = _n(repo, "skipped_file_count") + _n(config, "skipped_file_count")
    facts = [F("見つかった件数", f"{rn + cn}件"), F("調べたファイル（作業フォルダ）", f"{rs}個"),
             F("調べたファイル（設定）", f"{cs}個"), F("読まなかったファイル", f"{skipped}個"), F("基準", "0件")]
    if status == "pass":
        return Part(f"作業フォルダのGit管理下のファイル{rs}個と設定ファイル{cs}個を調べ、よくある形のキーは0件で、0件{MEETS}", facts)
    return Part(f"作業フォルダのGit管理下のファイル{rs}個と設定ファイル{cs}個を調べ、よくある形のキーらしい文字列が"
                f"{rn + cn}件（作業フォルダ{rn}件、設定ファイル{cn}件）あり、0件{NOT_MEETS}", facts)


def _g1(c, status, ai):
    if status == "unmeasured":
        return Part("作業フォルダを確かめられなかったため、" + CANNOT)
    git, remote, tracked = bool(c.get("is_git_repo")), bool(c.get("has_remote")), bool(c.get("instruction_tracked"))
    facts = [F("Gitでの管理", yn(git)), F("リモート", yn(remote)), F("指示書がGitの管理下", "はい" if tracked else "いいえ"),
             F("基準", "3つとも満たす")]
    if status == "pass":
        return Part("作業フォルダはGitで管理され、リモートがあり、指示書もGitの管理下にあるため、基準を満たしています", facts)
    if not git:
        return Part("作業フォルダがGitで管理されていないため、基準を満たしていません", facts)
    missing = "、".join(x for x, ok in (("リモートが無い", remote), ("指示書がGitの管理下に無い", tracked)) if not ok)
    return Part(f"作業フォルダはGitで管理されていますが、{missing}ため、基準を満たしていません", facts)


def _g2(c, status, ai):
    if status == "unmeasured":
        return Part(NO_TOOL)
    g, l, o = bool(c.get("global_has_content")), bool(c.get("local_has_content")), bool(c.get("has_override"))
    facts = [F("全体用の指示書の中身", yn(g)), F("作業フォルダ用の指示書の中身", yn(l)), F("個人用の上書きファイル", yn(o)),
             F("基準", "両方に中身があるか、上書きファイルがある")]
    if status == "pass" and g and l:
        return Part("全体用の指示書と作業フォルダ用の指示書の両方に中身があり、基準を満たしています", facts)
    if status == "pass":
        return Part("個人用の上書きファイルがあり、基準を満たしています", facts)
    which = "全体用の指示書" if not g else "作業フォルダ用の指示書"
    if not g and not l:
        which = "全体用と作業フォルダ用の指示書のどちらにも"
        return Part(f"{which}中身が無く、個人用の上書きファイルも無いため、基準を満たしていません", facts)
    return Part(f"{which}に中身が無く、個人用の上書きファイルも無いため、基準を満たしていません", facts)


def _g3(c, status, ai):
    hooks, sched = _n(c, "stop_hook_count"), _n(c, "scheduled_count")
    if not c.get("needs_ai_confirmation"):
        return Part("会話の終わりや区切りで動くフックも定時実行も見つからなかったため、" + CANNOT,
                    [F("終わりや区切りで動くフック", "0件"), F("定時実行", "0件")])
    state, n_lines = _ai_state(ai)
    if hooks == 0 and sched == 0:
        # フックの設定の項目はあるが中身が数えられなかった。「0件の中身を読んだ」と書かない
        facts = [F("終わりや区切りで動く仕組みの設定", "あり")] + _ai_facts(state, n_lines)
        base = "終わりや区切りで動く仕組みの設定の中身をAIが2回読み"
    else:
        facts = [F("終わりや区切りで動くフック", f"{hooks}件"), F("定時実行", f"{sched}件")] + _ai_facts(state, n_lines)
        base = f"終わりや区切りで動くフック{hooks}件と定時実行{sched}件の中身をAIが2回読み"
    if state == "yes":
        return Part(f"{base}、2回とも、記録を残す仕組みだと判定しました", facts)
    if state == "no":
        return Part(f"{base}、2回とも、記録を残す仕組みではないと判定しました", facts)
    return Part("終わりや区切りで動く仕組みは見つかりましたが、" + _ai_unmeasured(state), facts)


ToolBuilder = Callable[[str, dict, dict, object], Part]
CombinedBuilder = Callable[[dict, str, object], Part]

ITEM_BUILDERS: dict[str, ToolBuilder] = {
    "F1": _f1, "F2": _f2, "F3": _f3, "F4": _f4, "F5": _f5, "F6": _f6, "F7": _f7, "F8": _f8, "F9": _f9,
    "F10": _f10, "F11": _f11, "S2": _s2, "S3": _s3, "S4": _s4,
    "D1": _d1, "D2": _d2, "D3": _d3, "D4": _d4, "D5": _d5,
}
COMBINED_BUILDERS: dict[str, CombinedBuilder] = {"S1": _s1, "G1": _g1, "G2": _g2, "G3": _g3}


CRITERIA_LABELS = ("基準", "目安")


def _keep_criteria(facts: list, cap: int) -> list:
    """数が多いときに削るのは状態の側から。基準・目安の値は必ず残す（数字を見比べられるように）。"""
    if len(facts) <= cap:
        return facts
    crit = [f for f in facts if f["label"] in CRITERIA_LABELS][:cap]
    others = [f for f in facts if f["label"] not in CRITERIA_LABELS][: cap - len(crit)]
    return others + crit


def _join(parts: list[tuple[Optional[str], Part]]) -> tuple[str, list]:
    labeled = len(parts) > 1
    sentences, facts = [], []
    # 枠は、数字を持つ道具の数で割る（数字の無い道具の分まで割ると、余裕があるのに数字が落ちる）
    with_facts = sum(1 for _, p in parts if p.facts)
    per_tool_cap = MAX_FACTS // with_facts if with_facts else MAX_FACTS
    for tool, part in parts:
        # Codex だけの文は、Claude Code の項目と取り違えないよう道具の名前を前に付ける
        named = bool(tool) and (labeled or tool == "codex")
        sentences.append((f"{TOOL_LABELS[tool]}では、" if named else "") + part.sentence + "。")
        for f in _keep_criteria(part.facts, per_tool_cap):
            label = f["label"] + (f"（{TOOL_LABELS[tool]}）" if (labeled and tool) else "")
            facts.append({"label": label, "value": f["value"]})
    return "".join(sentences), facts[:MAX_FACTS]


def build_reason(item_def: dict, item_facts: dict, scored: dict, ai_judgments: dict) -> tuple[str, list]:
    """1項目ぶんの reason（文字列）と facts（配列）を返す。検査に通らなければ定型文に置き換える。"""
    reason, facts, _ = build_reason_checked(item_def, item_facts, scored, ai_judgments)
    return reason, facts


def build_reason_checked(item_def: dict, item_facts: dict, scored: dict, ai_judgments: dict) -> tuple[str, list, bool]:
    iid, status = item_def["id"], scored["status"]
    ai_item = (ai_judgments or {}).get(iid) or {}
    if iid in COMBINED_BUILDERS:
        part = COMBINED_BUILDERS[iid](item_facts.get("combined") or {}, status, ai_item.get("combined"))
        reason, facts = _join([(None, part)])
    else:
        per_tool = item_facts.get("per_tool") or {}
        results = scored.get("per_tool") or {}
        parts = []
        for tool in TOOL_ORDER:
            if tool not in per_tool:
                continue
            v = per_tool[tool] if isinstance(per_tool[tool], dict) else {}
            r = results.get(tool) or {"measured": False, "pass": None}
            parts.append((tool, ITEM_BUILDERS[iid](tool, v, r, ai_item.get(tool))))
        if not parts:
            reason, facts = NO_TOOL + "。", []
        else:
            reason, facts = _join(parts)
    return sanitize(iid, status, reason, facts)
