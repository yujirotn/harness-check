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


def _format_hours(seconds) -> str:
    try:
        return f"{float(seconds) / 3600:.1f}"
    except (TypeError, ValueError):
        return "0.0"


def _format_compact_number(n) -> str:
    """大きな数（主にキャッシュのトークン）をカードに収まる長さで出す。

    1億以上は億単位、1万以上は万単位（小数第1位まで）、それ未満は桁区切りの整数。
    """
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}億"
    if n >= 10_000:
        return f"{n / 10_000:.1f}万"
    return f"{n:,}"


def _exchanged_total(t: dict) -> int:
    # 大きく出す数字は「実際にやりとりした量」＝入力＋出力。キャッシュの読み書きは内訳に回す
    # （合計のほぼ全部がキャッシュで、実感のない数字になるため。4区分は排他）。
    return int(t.get("input", 0) or 0) + int(t.get("output", 0) or 0)


def _kpi(label: str, value: str, unit: str = "", detail: str = "") -> str:
    u = f'<span class="u">{esc(unit)}</span>' if unit else ""
    d = f'<div class="d">{detail}</div>' if detail else ""
    return f'<div class="kpi"><div class="k">{esc(label)}</div><div class="v num">{esc(value)}{u}</div>{d}</div>'


def _render_kpis(result: dict) -> str:
    """今月の時間・トークン（v4）と、直近30日の任せた量（v5）の数字の列。"""
    usage = result.get("usage_this_month") or {}
    autonomy = result.get("autonomy")
    if not usage and not autonomy:
        return ""
    cc, cx, comb = usage.get("claude_code", {}), usage.get("codex", {}), usage.get("combined", {})
    month = usage.get("month")
    cards = []
    if usage:
        def per_tool_hours() -> str:
            parts = []
            for label, u in (("Claude Code", cc), ("Codex", cx)):
                parts.append(f"{label} {_format_hours(u.get('active_seconds', 0))}" if u.get("measured") else f"{label} ―")
            return esc("／".join(parts))

        t = comb.get("tokens", {})
        cards.append(_kpi(f"今月使った時間{'（' + month + '）' if month else ''}",
                          _format_hours(comb.get("active_seconds", 0)), "時間", per_tool_hours()))
        cards.append(_kpi("今月のトークン（入力＋出力）", _format_compact_number(_exchanged_total(t)), "",
                          esc(f"キャッシュ読み{_format_compact_number(t.get('cache_read', 0))}・"
                              f"書き{_format_compact_number(t.get('cache_write', 0))}")))
    if isinstance(autonomy, dict):
        cards.append(_kpi("直近30日に AI が動いた回数", f"{int(autonomy.get('tool_calls_30d', 0)):,}", "回",
                          "道具の呼び出しの合計"))
        cards.append(_kpi("人を挟まず続いた最長", str(autonomy.get("max_consecutive", 0)), "回",
                          "道具の呼び出しの連続"))
    elif usage:
        counts = result.get("tool_counts") or {}
        comb_c = counts.get("combined", {})
        cards.append(_kpi("自分で用意したスキル", str(comb_c.get("skills", 0)), "本"))
        cards.append(_kpi("自分で定義したエージェント", str(comb_c.get("agents", 0)), "件"))
    unreadable = cx.get("unreadable_session_count", 0)
    note = (f'<p class="note">Codexは会話の記録のうち{esc(unreadable)}件が圧縮されていて読めず、'
            f'トークン・時間に含めていない。</p>') if unreadable else ""
    return f'<div class="kpis">{"".join(cards)}</div>{note}'


def _render_daily_chart(result: dict) -> str:
    """直近30日の日別の使っていた時間（棒グラフ・SVG）。v5。"""
    days = result.get("daily_30d")
    if not isinstance(days, list) or not days:
        return ""
    W, H, top, bottom = 600.0, 110.0, 14.0, 16.0
    n = len(days)
    slot = W / n
    bw = slot * 0.66
    secs = [max(0, int(d.get("active_seconds", 0) or 0)) for d in days]
    mx = max(secs) if secs else 0
    scale = (H - top - bottom) / mx if mx > 0 else 0
    base = H - bottom
    bars = []
    for i, v in enumerate(secs):
        x = i * slot + (slot - bw) / 2
        h = v * scale
        if v > 0:
            h = max(h, 1.5)
            bars.append(f'<rect class="bar" x="{x:.1f}" y="{base - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="1.5"/>')
        else:
            bars.append(f'<rect class="bar zero" x="{x:.1f}" y="{base - 1.5:.1f}" width="{bw:.1f}" height="1.5"/>')
    labels = []
    for i in (0, n // 2, n - 1):
        x = i * slot + slot / 2
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        lx = x - slot / 2 + 1 if i == 0 else (x + slot / 2 - 1 if i == n - 1 else x)
        labels.append(f'<text x="{lx:.1f}" y="{H - 3:.1f}" text-anchor="{anchor}">{esc(days[i].get("date", ""))}</text>')
    grid = ""
    if mx > 0:
        grid = (f'<line class="grid" x1="0" y1="{top:.1f}" x2="{W:.1f}" y2="{top:.1f}"/>'
                f'<text x="{W:.1f}" y="{top - 3:.1f}" text-anchor="end">最大 {esc(_format_hours(mx))}時間</text>')
    active_days = sum(1 for v in secs if v > 0)
    sessions = sum(int(d.get("sessions", 0) or 0) for d in days)
    svg = (f'<svg viewBox="0 0 {W:.0f} {H:.0f}" preserveAspectRatio="none" role="img" aria-label="直近30日の日別の使用時間">'
           f'{grid}<line class="axis" x1="0" y1="{base:.1f}" x2="{W:.1f}" y2="{base:.1f}"/>{"".join(bars)}{"".join(labels)}</svg>')
    return (f'<div class="chart"><div class="cap"><span>直近30日の日別の使用時間（Claude Code）</span>'
            f'<span>使った日 <b class="num">{active_days}</b> / {n}日・始めた会話 <b class="num">{sessions}</b>件</span></div>'
            f'{svg}</div>')


def _render_breadth_and_autonomy(result: dict) -> str:
    """使われている／眠っている本数（v5）と、任せた量の残り（v5）。"""
    breadth = result.get("usage_breadth")
    autonomy = result.get("autonomy")
    if not isinstance(breadth, dict) and not isinstance(autonomy, dict):
        return ""
    rows = []
    if isinstance(breadth, dict):
        for key, label, unit in (("skills", "スキル", "本"), ("agents", "エージェント", "件"), ("connectors", "コネクタ", "個")):
            b = breadth.get(key) or {}
            own, used = int(b.get("own", 0) or 0), int(b.get("used", 0) or 0)
            pct = (used / own * 100) if own else 0
            rows.append(
                f'<div class="brow"><span class="bl">{label}</span>'
                f'<div class="track"><div class="used" style="width:{pct:.0f}%"></div></div>'
                f'<span class="bn">使用 <b class="num">{used}</b> / {own}{unit}</span></div>'
            )
    left = (f'<div><div class="chart"><div class="cap"><span>直近30日に使われているもの／眠っているもの</span></div></div>'
            f'{"".join(rows)}</div>') if rows else "<div></div>"
    right = "<div></div>"
    if isinstance(autonomy, dict):
        right = (
            '<div><div class="chart"><div class="cap"><span>人を挟まず任せて動いた会話（直近30日）</span></div></div><div class="auto">'
            f'<div class="a"><div class="k">20回以上続いた会話</div><div class="v num">{esc(autonomy.get("sessions_20plus", 0))}<span class="u">件</span></div></div>'
            f'<div class="a"><div class="k">エージェントの連携</div><div class="v num">{esc(autonomy.get("agent_relay_sessions", 0))}<span class="u">件</span></div></div>'
            '</div></div>'
        )
    return f'<div class="breadth">{left}{right}</div>'


def render_cover(result: dict) -> str:
    score = result.get("score")
    withheld = score is None
    type_name = result.get("type_name") or ""
    judged = result.get("judged_item_count", 0)
    total = result.get("total_item_count", 0)

    dashboard = _render_kpis(result) + _render_daily_chart(result) + _render_breadth_and_autonomy(result)
    dashboard_block = (f'<h2 class="first">今どれだけ使えているか<span class="sub">PCに残る会話の記録から数えた数。名前は出していない</span></h2>'
                       f'{dashboard}') if dashboard else ""

    pillar_rows = []
    for pid in result["pillar_order"]:
        p = result["pillars"][pid]
        rate = p.get("rate")
        sufficient = p.get("sufficient", True)
        pct = int(round((rate or 0) * 100))
        if rate is None:
            pct_display = "判定できず"
        elif not sufficient:
            pct_display = f"判定不足（{pct}%）"
        else:
            pct_display = f"達成率{pct}%"
        cls = "" if sufficient else ' class="insufficient"'
        pillar_rows.append(
            f"""<tr{cls}>
  <th>{esc(p['name'])}</th>
  <td class="barcell"><div class="track"><div class="fill" style="width:{pct}%"></div></div></td>
  <td class="pt"><b>{esc(p['passed_count'])}</b> / {esc(p['judged_count'])}<span class="pctnum">{esc(pct_display)}</span></td>
</tr>"""
        )

    if withheld:
        scorebox = f"""<div class="scorebox withheld"><div class="cap">点数</div><div class="score-num">―</div>
  <div class="withheld-note">まだ測れるものが少ないため、点数と型の名前は出していません（判定できた項目が半分未満）。下の「次に直す項目」から始めてください。</div>
  <div class="judged">全{esc(total)}項目中{esc(judged)}項目を判定</div></div>"""
    else:
        scorebox = f"""<div class="scorebox"><div class="cap">点数</div><div><span class="score-num num">{esc(score)}</span><span class="of">/ 100点</span></div>
  <div class="now">{esc(type_name)}</div>
  <div class="judged">全{esc(total)}項目中{esc(judged)}項目を判定</div></div>"""

    next_items = result.get("next_fixes", [])
    if next_items:
        lis = []
        for i, it in enumerate(next_items, start=1):
            fix_text = it.get("fix_text", it.get("name", ""))
            lis.append(f"""<li><span class="n num">{i}</span><div class="body"><b>{esc(fix_text)}</b>
<p>項目ID: {esc(it['id'])}（{esc(result['pillars'][it['pillar']]['name'])}）</p></div></li>""")
        next_block = f"<h2>次に直す項目</h2><ol class=\"next3\">{''.join(lis)}</ol>"
    else:
        next_block = "<h2>次に直す項目</h2><p>×の項目はありません。</p>"

    return f"""<section class="page">
<header class="pagehead"><span class="t">ハーネス点検レポート</span><span>1 / 表紙</span></header>
<p class="intro">ハーネス＝AIの周りに置く設定・指示・道具の一式。<br>見ているのはPCに残る設定と記録だけ。チャット画面での利用は数えていない。</p>
{dashboard_block}
<h2>点数と型</h2>
<div class="scorerow">
{scorebox}
<table class="pillars"><tbody>
{''.join(pillar_rows)}
</tbody></table>
</div>
<p class="note">判定できなかった項目は分母から外している。判定できた項目が半分未満の柱は「判定不足」として、点数と型の名前に使っていない。スキル・エージェント・コネクタの使用は回数に応じた部分点なので、達成率は「満たした数／判定できた数」と一致しないことがある。</p>
{next_block}
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
            reason = item.get("reason")
            tier = item.get("usage_tier")
            # MEDIUM差し戻し: 段階は「項目の行」そのもの（結果の列）に必ず並べる
            # （reasonの文末に添えるだけでは、行を見ただけで段階が分からない）。
            # status（○×測定できず）の3値は変えない（下流が前提にしているため）。
            note_text = (
                f'{STATUS_NOTE[status]}（{esc(tier["count"])}回・段階{esc(tier["label"])}）'
                if isinstance(tier, dict)
                else STATUS_NOTE[status]
            )
            # v3 から項目ごとの理由がある。v2 の result.json には無いので、そのときは出さない
            reason_row = (
                f"""<tr class="reason-row"><td></td><td colspan="3" class="reason">{esc(reason)}</td></tr>"""
                if isinstance(reason, str) and reason
                else ""
            )
            rows.append(
                f"""<tbody class="item"><tr class="{status}">
  <td class="mk"><span>{STATUS_MARK[status]}</span></td>
  <td class="name">{esc(iid)}　{esc(item['name'])}</td>
  <td class="judge">{esc(item['judge_label'])}</td>
  <td class="note">{note_text}</td>
</tr>{reason_row}</tbody>"""
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
{''.join(rows)}
</table>
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
<li>キーの走査の限界: よくある形のキー（<code>sk-</code>・<code>AIza</code>等）と、設定ファイルの中の名前でわかるもの（<code>token</code>・<code>secret</code>等）だけを探している。1MBを超えるファイルと、Gitの対象外のファイル（.env等）は見ていない。</li>
<li>小文字だけの値や、小文字・数字・ハイフンだけの値は、名前や見本とみなして数えない。</li>
<li>秘密ファイルを読ませない設定（S2）と、取り返しのつかない操作の承認（S3）は、設定の行とフックの中身に、系統ごとの語が書かれているかだけを見ている。フックを実行して、本当に止まるかは試していない。</li>
<li>直近30日の日別グラフと「使われている／眠っているもの」「任せて動いた量」は、Claude Code の会話の記録だけから作っている。</li>
<li>今月の使用時間の合計は、Claude Code と Codex の値を単純に足したもの。同時に両方を使っていた時間があれば、その分は重複して数えている。</li>
<li>Codex のトークンは、会話の記録が圧縮されていて読めない分は足していない（推測で埋めていない）。</li>
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
