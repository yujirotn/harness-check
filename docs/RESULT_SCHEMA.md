# result.json の形

`render.py`（および差し替え先のひな形）が読むのは `result.json` だけです。`facts.json` や `ai_judgments.json` の形が変わっても、`result.json` の形が変わらなければ、ひな形は直す必要がありません。

`score.py` が `harness-check-output/result.json` に書き出します。

## 形

```jsonc
{
  "schema_version": 2,
  "score": 72,                // 100点満点。四捨五入済み。判定できた項目が0件なら null
  "judged_item_count": 18,    // 判定できた項目の数（23項目中）
  "total_item_count": 23,
  "type_name": "土台は強く、安全が薄い型",  // 柱の呼び名は「土台」「安全」「育つ仕組み」「任せ方」の4つだけ。複数は「、」でつなぐ
  "pillar_order": ["foundation", "safety", "grow", "delegate"],

  "pillars": {
    "foundation": {
      "name": "土台",
      "judged_count": 10,      // この柱で判定できた項目数
      "total_count": 11,       // この柱の項目数（23項目中の内訳。F1〜F11なら11）
      "passed_count": 9,       // ○だった数
      "rate": 0.9              // passed_count / judged_count。judged_count が0なら null
    },
    "safety": { "...": "同じ形" },
    "grow": { "...": "同じ形（name は必ず「育つ仕組み」）" },
    "delegate": { "...": "同じ形" }
  },

  "items": {
    "F1": {
      "name": "作業フォルダに指示書がある",
      "pillar": "foundation",
      "judge": "machine",            // machine | ai | machine_ai | machine_user
      "judge_label": "機械",          // 機械 | AIの判断 | 機械＋AIの判断 | 機械＋本人の回答
      "status": "pass"               // pass | fail | unmeasured
    }
    // ... 23項目分。ひな形側は ID の番号順（F1, F2, ..., F10, F11）に並べ替えて表示する
  },

  "next_fixes": [
    {
      "id": "S1",
      "name": "よくある形のキーが、コードや設定に直接書かれていない",
      "pillar": "safety",
      "fix_text": "コード・設定に直接書かれたキーを環境変数などに移す"  // ひな形はこちらを表示する（動詞の言い方）
    }
    // 最大3件。安全→土台→任せ方→育つ仕組み の順
  ],

  "reference": {
    "names_included": false,  // --show-names を付けたときだけ true。ひな形はこのフラグで表示を分岐する

    "skills": {
      "own_count": 2,              // 自分で用意した本数
      "used_recent_count": 1,      // うち直近30日に使われた本数
      "usage_counts": [5, 1]       // 使用回数を多い順に並べた数字だけ（名前は無い）
    },
    "agents": { "...": "skills と同じ形" },
    "connectors": {
      "count": 1,          // つながっている数
      "calls_30d": 4       // 直近30日の呼び出しの合計
    },

    // names_included が true のときだけ、次が追加される（名前つき）
    "named": {
      "skills": { "demo-skill": 5 },
      "agents": { "demo-agent": 1 },
      "connectors": { "demo-connector": 4 }
      // 「意味のない識別子」（UUID・長い16進など）は、ひな形側で表示から除外し「ほか◯件」にまとめる
    },

    "max_consecutive_tool_calls": { "claude_code": 26 },
    "startup_instructions": {
      "claude_code_total_lines": 42,
      "claude_code_file_count": 13,
      "codex_total_bytes": 1200,
      "codex_file_count": 1
    },
    "secret_scan": {
      "repo":   { "counts_by_kind": { "openai_or_anthropic": 1 }, "scanned_file_count": 663, "skipped_file_count": 0 },
      "config": { "counts_by_kind": { "named_secret": 1 }, "scanned_file_count": 5, "skipped_file_count": 0 }
    }
  },

  "tools_detected": { "claude_code": true, "codex": false },
  "window_days": 30
}
```

## 守っていること

- フォルダ名・ファイルパス・キーの値・ファイルの本文は入らない。
- **スキル・エージェント・コネクタの名前は、`names_included: true`（`--show-names`）のときだけ入る**。既定は数字だけ（名前なし）。
- `status` は3値のみ（`pass` / `fail` / `unmeasured`）。`unmeasured` は点数の分母から外れている。
- 柱の `rate` が `null` の柱は、点数の平均から除外されている（`score.py` 側で処理済み）。
- キーの走査は `repo`（リポジトリの中）と `config`（設定ファイルの中）を分けて持つ。値そのものは入らない。

## ひな形を差し替えるときの注意

- `templates/report.html` を差し替える場合、`render.py` の `render_cover` / `render_pillar_pages` / `render_reference_page` / `render_blindspots_page` が読む項目は、この表の中のキーだけです。
- `render.py` 側も新しいひな形の構造に合わせて直す必要があります（`render.py` は「`result.json` → HTML」の変換ロジックを持っているため、ひな形だけの差し替えでは完結しません）。純粋にデータだけを差し替え可能にするなら、ひな形側で JS を使い `result.json` を直接読み込む形に作り替えることもできますが、本リポジトリの既定実装は Chrome の `--print-to-pdf` での確実な印刷を優先し、Python 側で静的HTMLを生成する方式を採っています。
- 「意味のない識別子」の判定（UUID・16進羅列など）は `render.py` の `is_meaningless_identifier` にある。ひな形を書き換えるときもこの関数は再利用できる。
