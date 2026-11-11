#!/usr/bin/env python3
"""ハーネス点検 — result.json とひな形から HTML と PDF を出す。

読むだけ・通信なし。書き込みは --out で指定した出力フォルダの中だけ。
PDF化は、利用者のPCにある Chrome のヘッドレス実行（--print-to-pdf）を使う。
Chrome が見つからなければ、HTMLを残して開き方を案内する。
標準ライブラリだけで動く（Python 3.9 以上）。

Chrome の起動は readers.common.render_pdf_with_chrome（固定の命令3）だけを通す（5-7）。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from readers import common  # noqa: E402


STATUS_MARK = {"pass": "○", "fail": "×", "unmeasured": "―"}
STATUS_NOTE = {
    "pass": "満たしている",
    "fail": "満たしていない",
    "unmeasured": "測定できず",
}

# 「意味のない識別子」（UUID・長い16進の羅列など）は --show-names でも名前として出さない。
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_LONG_HEX_RE = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)


def is_meaningless_identifier(name: str) -> bool:
    return bool(_UUID_RE.match(name) or _LONG_HEX_RE.match(name))


def _item_id_sort_key(iid: str):
    m = re.match(r"^([A-Za-z]+)(\d+)$", iid)
    if not m:
        return (iid, 0)
    return (m.group(1), int(m.group(2)))


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def render_cover(result: dict) -> str:
    score = result.get("score")
    score_display = esc(score) if score is not None else "―"
    type_name = esc(result.get("type_name", ""))
    judged = result.get("judged_item_count", 0)
    total = result.get("total_item_count", 0)

    pillar_rows = []
    for pid in result["pillar_order"]:
        p = result["pillars"][pid]
        rate = p.get("rate")
        pct = int(round((rate or 0) * 100))
        pillar_rows.append(
            f"""<tr>
  <th>{esc(p['name'])}</th>
  <td class="barcell"><div class="track"><div class="fill" style="width:{pct}%"></div></div></td>
  <td class="pt"><b>{esc(p['passed_count'])}</b> / {esc(p['judged_count'])}</td>
</tr>"""
        )

    next_items = result.get("next_fixes", [])
    next_html = []
    if next_items:
        for i, it in enumerate(next_items, start=1):
            fix_text = it.get("fix_text", it.get("name", ""))
            next_html.append(
                f"""<li><span class="n">{i}</span><div class="body"><b>{esc(fix_text)}</b>
<p>項目ID: {esc(it['id'])}（{esc(result['pillars'][it['pillar']]['name'])}）</p></div></li>"""
            )
        next_block = f"<h2>次に直す項目</h2><ol class=\"next3\">{''.join(next_html)}</ol>"
    else:
        next_block = "<h2>次に直す項目</h2><p>×の項目はありません。</p>"

    return f"""<section class="page">
<header class="pagehead"><span class="t">ハーネス点検レポート</span></header>
<div class="hero">
  <p class="intro">ハーネス＝AIの周りに置く設定・指示・道具の一式。<br>見ているのはPCに残る設定と記録だけ。チャット画面での利用は数えていない。</p>
  <div class="hero-main">
    <div class="score-box"><span class="cap">点数</span><span class="score-num">{score_display}</span><span class="of">/ 100点</span></div>
    <div class="typebox"><div class="now">{type_name}</div>
      <div class="judged">全{esc(total)}項目中{esc(judged)}項目を判定</div></div>
  </div>
</div>
<h2 class="first">柱ごとの結果</h2>
<table class="pillars"><tbody>
{''.join(pillar_rows)}
</tbody></table>
<p class="note">判定できなかった項目は、点数の分母から外している。柱ごとの内訳は次ページ以降。</p>
{next_block}
<footer class="pagefoot">1</footer>
</section>"""


def render_pillar_pages(result: dict) -> str:
    pages = []
    for pid in result["pillar_order"]:
        p = result["pillars"][pid]
        items = [
            (iid, item)
            for iid, item in result["items"].items()
            if item["pillar"] == pid
        ]
        items.sort(key=lambda kv: _item_id_sort_key(kv[0]))
        rows = []
        for iid, item in items:
            status = item["status"]
            rows.append(
                f"""<tr class="{status}">
  <td class="mk">{STATUS_MARK[status]}</td>
  <td class="name">{esc(iid)}　{esc(item['name'])}</td>
  <td class="judge">{esc(item['judge_label'])}</td>
  <td class="note">{STATUS_NOTE[status]}</td>
</tr>"""
            )
        rate = p.get("rate")
        rate_display = f"{int(round(rate * 100))}点" if rate is not None else "判定できず"
        pages.append(
            f"""<section class="page">
<header class="pagehead"><span class="t">ハーネス点検レポート</span></header>
<div class="pillar-block">
<div class="pillar-head"><h3>{esc(p['name'])}</h3><span class="rate"><b>{esc(p['passed_count'])}</b> / {esc(p['judged_count'])}（{rate_display}）</span></div>
<table class="items">
<thead><tr><th class="mk"></th><th class="name">項目</th><th class="judge">判定の種類</th><th class="note">結果</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody></table>
</div>
<p class="note">○＝満たしている／×＝満たしていない／―＝測定できず。判定の種類は「機械」「AIの判断」「機械＋AIの判断」「機械＋本人の回答」のいずれか。</p>
<footer class="pagefoot">{esc(p['name'])}</footer>
</section>"""
        )
    return "".join(pages)


def _anon_count_block(title: str, stats: dict, unit_label: str) -> str:
    own = stats.get("own_count", stats.get("count", 0))
    used_recent = stats.get("used_recent_count")
    usage_counts = stats.get("usage_counts")
    parts = [f"自分で用意した{unit_label}: {esc(own)}本"]
    if used_recent is not None:
        parts.append(f"うち直近30日に使われた: {esc(used_recent)}本")
    if usage_counts:
        nums = "、".join(str(n) for n in usage_counts)
        parts.append(
            f"使用回数（多い順・名前は出さない。少数の道具に偏っていないかの目安）: {esc(nums)}"
        )
    return f"<h3>{esc(title)}</h3><p>{'／'.join(parts)}</p>"


def _named_count_table(title: str, counts: dict, unit_label: str) -> str:
    if not counts:
        return f"<h3>{esc(title)}</h3><p class=\"note\">記録なし。</p>"
    filtered = {k: v for k, v in counts.items() if not is_meaningless_identifier(k)}
    meaningless_count = len(counts) - len(filtered)
    ranked = sorted(filtered.items(), key=lambda kv: (-kv[1], kv[0]))
    TOP_N = 12
    shown = ranked[:TOP_N]
    rest_count = len(ranked) - len(shown) + meaningless_count
    rows = "".join(f"<tr><td>{esc(name)}</td><td>{esc(n)}</td></tr>" for name, n in shown)
    extra = f"<p class=\"note\">ほか{rest_count}件。</p>" if rest_count else ""
    return (
        f"<h3>{esc(title)}</h3>"
        f"<table class=\"counttable\">"
        f"<thead><tr><th>名前</th><th>直近30日の使用回数</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        f"{extra}"
    )


def render_reference_page(result: dict) -> str:
    ref = result.get("reference", {})
    names_included = bool(ref.get("names_included"))

    secret_scan = ref.get("secret_scan", {})
    repo_scan = secret_scan.get("repo", {})
    config_scan = secret_scan.get("config", {})
    repo_total = sum(repo_scan.get("counts_by_kind", {}).values())
    config_total = sum(config_scan.get("counts_by_kind", {}).values())
    startup = ref.get("startup_instructions", {})
    max_consec = ref.get("max_consecutive_tool_calls", {})

    stat_cards = f"""<div class="statgrid">
  <div class="card"><div class="label">毎回読まれる指示の合計行数（Claude Code）</div><div class="value">{esc(startup.get('claude_code_total_lines', 0))}行 / {esc(startup.get('claude_code_file_count', 0))}ファイル</div></div>
  <div class="card"><div class="label">読まれる AGENTS.md の合計サイズ（Codex）</div><div class="value">{esc(startup.get('codex_total_bytes', 0))}バイト / {esc(startup.get('codex_file_count', 0))}ファイル</div></div>
  <div class="card"><div class="label">最長の連続回数（人の発言を挟まず）</div><div class="value">{esc(max_consec.get('claude_code', 0))}回</div></div>
  <div class="card"><div class="label">キーらしき文字列（リポジトリ）</div><div class="value">{esc(repo_total)}件 / 走査 {esc(repo_scan.get('scanned_file_count', 0))}・読まなかった {esc(repo_scan.get('skipped_file_count', 0))}（画像など文字でないもの、1MBを超えるもの）</div></div>
  <div class="card"><div class="label">キーらしき文字列（設定ファイル）</div><div class="value">{esc(config_total)}件 / 走査 {esc(config_scan.get('scanned_file_count', 0))}</div></div>
</div>"""

    if names_included:
        named = ref.get("named", {})
        body = (
            _named_count_table("スキルごとの使用回数", named.get("skills", {}), "スキル")
            + _named_count_table("エージェントごとの使用回数", named.get("agents", {}), "エージェント")
            + _named_count_table("コネクタごとの使用回数", named.get("connectors", {}), "コネクタ")
        )
        names_note = '<p class="note shown-names">固有名を含みます</p>'
    else:
        skills = ref.get("skills", {})
        agents = ref.get("agents", {})
        connectors = ref.get("connectors", {})
        body = (
            _anon_count_block("スキル", skills, "スキル")
            + _anon_count_block("エージェント", agents, "エージェント")
            + f"<h3>コネクタ</h3><p>つながっている数: {esc(connectors.get('count', 0))}／"
            f"直近30日の呼び出しの合計: {esc(connectors.get('calls_30d', 0))}</p>"
        )
        names_note = ""

    return f"""<section class="page">
<header class="pagehead"><span class="t">ハーネス点検レポート</span></header>
<h2 class="first">参考の数字（直近{esc(result.get('window_days', 30))}日）</h2>
{stat_cards}
{body}
<p class="note">数え方: 使用回数は会話の記録（直近30日）から数えたもの。キーらしき文字列は種類と件数のみで、値・ファイル名・行番号は出していない。</p>
{names_note}
<footer class="pagefoot">参考</footer>
</section>"""


def render_blindspots_page(result: dict) -> str:
    tools = result.get("tools_detected", {})
    unmeasured = [
        (iid, item) for iid, item in sorted(result["items"].items(), key=lambda kv: _item_id_sort_key(kv[0]))
        if item["status"] == "unmeasured"
    ]
    unmeasured_html = "".join(f"<li>{esc(iid)}　{esc(item['name'])}</li>" for iid, item in unmeasured)
    if not unmeasured_html:
        unmeasured_html = "<li>今回はすべての項目を判定できた。</li>"

    tools_line = "、".join(name for name, on in (("Claude Code", tools.get("claude_code")), ("Codex", tools.get("codex"))) if on) or "検出できなかった"

    return f"""<section class="page">
<header class="pagehead"><span class="t">ハーネス点検レポート</span></header>
<h2 class="first">この点検が見ていないもの</h2>
<ul class="blindspots">
<li>claude.ai や ChatGPT などの、チャット画面だけでの利用は数えていない（PCに残る記録だけを見ている）。</li>
<li>Codex の会話の記録は、標準機能で読める形になっていないため、使用実績が要る項目は「測定できず」にしている。</li>
<li>この点検で検出した道具: {tools_line}。</li>
<li>キーの走査の限界: よくある形のキー（sk-・AIza等）と、設定ファイルの中の名前でわかるもの（token・secret等）だけを探している。1MBを超えるファイルと、Gitの対象外のファイル（.env等）は見ていない。</li>
<li>小文字だけの値や、小文字・数字・ハイフンだけの値は、名前や見本とみなして数えない。</li>
</ul>
<h3>今回「測定できず」だった項目</h3>
<ul class="blindspots">
{unmeasured_html}
</ul>
<p class="note">「測定できず」は点数の分母から外している（×にはしていない）。</p>
<footer class="pagefoot">見ていないもの</footer>
</section>"""


def build_html(template_text: str, result: dict) -> str:
    body = (
        render_cover(result)
        + render_pillar_pages(result)
        + render_reference_page(result)
        + render_blindspots_page(result)
    )
    return template_text.replace("{{BODY}}", body)


def try_print_to_pdf(html_path: Path, pdf_path: Path, out_dir: Path) -> tuple[bool, str]:
    """PDF化は readers.common.render_pdf_with_chrome（固定命令3）に完全に委譲する。

    Chrome の探し方・起動・専用設定フォルダの作成と削除は、すべて入口の側（common）が行う。
    """
    ok = common.render_pdf_with_chrome(html_path, pdf_path, out_dir)
    if not ok:
        return False, "Chrome が見つからないか、PDFが作れなかった。"
    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description="ハーネス点検: result.json → HTML / PDF")
    parser.add_argument("--out", default=os.environ.get("HARNESS_CHECK_OUT", "harness-check-output"))
    parser.add_argument(
        "--template",
        default=str(Path(__file__).resolve().parent / "templates" / "report.html"),
    )
    parser.add_argument("--no-pdf", action="store_true", help="PDF化を試さず HTML だけ出す（テスト用）")
    args = parser.parse_args()

    out_dir = Path(args.out).expanduser().resolve()
    result_path = out_dir / "result.json"
    with result_path.open("r", encoding="utf-8") as fh:
        result = json.load(fh)

    template_text = Path(args.template).read_text(encoding="utf-8")
    full_html = build_html(template_text, result)

    html_path = out_dir / "report.html"
    html_path.write_text(full_html, encoding="utf-8")
    print(f"report.html を書きました: {html_path}")

    if args.no_pdf:
        return 0

    pdf_path = out_dir / "report.pdf"
    ok, message = try_print_to_pdf(html_path, pdf_path, out_dir)
    if ok:
        print(f"report.pdf を書きました: {pdf_path}")
    else:
        print(f"PDFは作れなかった: {message}")
        print(f"HTML をブラウザで開いて、印刷からPDFとして保存してください: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
