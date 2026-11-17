# result.json の形（schema_version 4）

このファイルが `result.json` の形の正本です。受け取る側（ひな形・受付・管理画面）は、このファイルだけを見て実装できるように書いています。

`render.py`（および差し替え先のひな形）が読むのは `result.json` だけです。`facts.json` や `ai_judgments.json` の形が変わっても、`result.json` の形が変わらなければ、ひな形は直す必要がありません。

`score.py` が `harness-check-output/result.json` に書き出します。

## 形

```jsonc
{
  "schema_version": 4,       // 3 から items の各項目に reason・facts が付いた。4 から usage_this_month・tool_counts・items.<ID>.usage_tier が付いた
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
      "status": "pass",              // pass | fail | unmeasured
      "reason": "Claude Codeでは、作業フォルダからGitの一番上のフォルダまでに指示書が1件あり、1件以上という基準を満たしています。",
      "facts": [
        { "label": "指示書の数", "value": "1件" },
        { "label": "基準", "value": "1件以上" }
      ],
      "usage_tier": null             // v4。F6・F9・F11 以外は常に null
    },
    "F6": {
      "...": "他の項目と同じ形",
      "usage_tier": {                // v4。F6・F9・F11 だけ値を持つ（直近30日の使用回数の段階。15章）
        "count": 41,                 // 複数の道具が測れたときは回数を合計したもの
        "credit_num": 3, "credit_den": 3,   // 0/3・1/3・2/3・3/3 のどれか（分母は常に3）
        "label": "満点"               // "0" | "1/3" | "2/3" | "満点"
      }
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

    "inventory_truncated": { "skills": 0, "agents": 0, "connectors": 0 },          // v3。inventory で300件を超えて切った数
    "inventory_summaries_replaced": { "skills": 2, "agents": 0, "connectors": 1 }, // v3。説明を「（説明を作れませんでした）」に置き換えた数

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
  "window_days": 30,

  // v4。今月の使用量（時間・トークン）。表紙の点数のすぐ下に出す（15章）。
  // tokens の4区分（input/output/cache_read/cache_write）は排他（重なりが無い）。
  // 足すと実際にやりとりした量＋キャッシュの読み書きの合計になる（二重計上はしていない）。
  // Claude Code は message.id ごとに1回だけ数える（重複行があるため。HIGH差し戻しで対応）。
  // 表紙に大きく出す数字は input + output（実際にやりとりした量）で、cache_* は内訳として小さく出す。
  "usage_this_month": {
    "month": "2026-11",            // 日本時間の暦月のラベル。日付のみ（固有名ではない）
    "claude_code": {
      "measured": true,
      "active_seconds": 44280,     // 記録の時刻の間隔が5分以内の連続を足したもの
      "tokens": { "input": 120000, "output": 30000, "cache_read": 900000, "cache_write": 50000 }
    },
    "codex": {
      "measured": true,
      "active_seconds": 3600,
      "tokens": { "input": 20000, "output": 4000, "cache_read": 10000, "cache_write": 0 },
      "unreadable_session_count": 12   // 今月分のうち、圧縮されていて読めなかった件数。トークン・時間には含めない
    },
    "combined": {                   // 2つの道具の値を単純に足したもの（重複しうる。15章）
      "active_seconds": 47880,
      "tokens": { "input": 140000, "output": 34000, "cache_read": 910000, "cache_write": 50000 }
    }
  },

  // v4。自分で用意したスキル・エージェントの本数（道具ごと）。名前は入らない
  "tool_counts": {
    "claude_code": { "skills": 12, "agents": 4 },
    "codex": { "skills": 1, "agents": 0 },
    "combined": { "skills": 13, "agents": 4 }
  },

  // v3。スキル・エージェント・コネクタの「説明の一覧」（名前は入らない）
  "inventory": {
    "skills":     [{ "summary": "月ごとの実績を表にまとめ、グラフと要点を付ける", "category": "集計", "used_30d": 4 }],
    "agents":     [{ "summary": "書いた文章を、読み手の立場で見直して指摘する", "used_30d": 0 }],
    "connectors": [{ "summary": "チャットの道具とつないで、メッセージを読み書きする", "used_30d": 12 }]
  }
}
```

## items の reason・facts（v3 で追加）

| キー | 型 | 決まり |
|---|---|---|
| `reason` | 文字列 | 1〜300字。必ずある。日本語の1〜2文（道具が2つ見つかったときは道具ごとに1文ずつ） |
| `facts` | 配列 | 0〜6個。必ずある（無ければ空の配列） |
| `facts[].label` | 文字列 | 1〜40字 |
| `facts[].value` | 文字列 | 1〜60字 |

`facts` の各要素のキーは `label` と `value` の2つだけ。

### 何が書いてあるか

- `reason` は「**今の状態**」（何が何件・何行・何回・有る無し）と、「**判定の基準とどう比べたか**」だけを書く。
  - 通った・通らなかった: 「〜が3件あり、1件以上という基準を満たしています」「いちばん長いものは412行で、200行未満という目安を超えるものが2件あります」
  - AIが判定した項目: 「〜をAIが2回読み、2回とも、〜と判定しました」（AIが書いた文は使わない。決まった文だけ）
  - 判定なし: 何が足りなくて判定できなかったか。「会話の記録が見つからなかったため、判定できませんでした」「AIが2回読んだ答えが食い違ったため、判定できませんでした」
- 「なぜそれが良い・困るのか」の意味づけや、評価の言葉（「問題です」「素晴らしい」など）は入れない。項目ごとの説明は読む側（管理画面など）が持つ。
- `facts` には、理由の根拠になった数・状態と、**基準の値**（`label` が「基準」か「目安」）を入れる。読む人が数字を見比べられるようにするため。
- 道具が2つ（Claude Code と Codex）見つかったとき、`reason` の各文は「Claude Codeでは、」「Codexでは、」で始まり、`facts` の `label` の末尾に「（Claude Code）」「（Codex）」が付く。Codex だけのときも「Codexでは、」で始まる。
- 項目全体の `status` と、道具ごとの文の結論が違うことがある（例: 「あることを見る項目」で、Claude Code は満たし、Codex は満たしていない → 項目は `pass`）。合わせ方は `docs/SPEC.md` 5-2。

### reason・facts に入らないもの

`reason`・`facts` は、決まった文の型（`reasons.py` の `ITEM_BUILDERS`・`COMBINED_BUILDERS`）に**整数と決まった語だけ**を差し込んで作る。差し込める値に名前や文が無い作りなので、次は入らない。`--show-names`（名前つき）で作った結果でも同じ。

- ファイルやフォルダの場所（パス）、ファイル名（拡張子つきの名前。`CLAUDE.md` のような道具の一般名も使わず「指示書」と書く）
- スキル名・エージェント名・コネクタ名・プロジェクト名・人名・社名などの固有の名前
- 設定の項目名や値（`permissions.deny`・`approval_policy` など。「許可の設定」「承認の方式」と書く）
- キーやトークンの値、メールアドレス、電話番号、URL
- 指示書や会話の中身の引用、AIが書いた文（`ai_judgments.json` に理由の文があっても使わない）

出てくる英字の語は **「Claude」「Code」「Codex」「Git」「AI」だけ**。記号の `/` `\` `~` `@` `:` `-` `_` `.` は使わない（数字はすべて整数。大きさは「2048バイト」のように書く）。

`score.py` は、出来上がった文を `reasons.find_forbidden` で検査する（受付の「名前らしい文字列」の走査と同じ形の検査＋上の5語以外の英字・パスの記号・URL・メール・長い数字の並び）。当たったときは、その項目の `reason` を「この項目は基準を満たしています。」などの定型文に、`facts` を空に置き換え、標準出力に件数を出す（文の型の不具合なので、テストで0件であることを確かめている）。

### 文の例

| 状態 | reason | facts |
|---|---|---|
| F2 通らなかった | 毎回読まれる指示ファイルが3件あり、いちばん長いものは412行で、200行未満という目安を超えるものが2件あります。 | 指示ファイルの数=3件／いちばん長い指示ファイル=412行／目安を超えたファイル=2件／目安=200行未満 |
| F6 通った（道具2つ） | Claude Codeでは、直近30日に、自分で用意したスキル12本のうち3本が合計41回使われ、1回以上という基準を満たしています。Codexでは、会話の記録が標準の機能で読めない形のため、判定できませんでした。 | 自分で用意したスキルの数（Claude Code）=12本／直近30日に使われた数（Claude Code）=3本／基準（Claude Code）=直近30日に1回以上 |
| F3 判定なし | AIが2回読んだ答えが食い違ったため、判定できませんでした（食い違ったときは判定しない決まりです）。 | AIが読んだ数=1件／AIの判定=1回目と2回目で違う答え |
| S1 通らなかった | 作業フォルダのGit管理下のファイル10個と設定ファイル3個を調べ、よくある形のキーらしい文字列が3件（作業フォルダ2件、設定ファイル1件）あり、0件という基準を満たしていません。 | 見つかった件数=3件／…／基準=0件 |

項目ごと・状態ごとの文の型の一覧は `reasons.py`（`ITEM_BUILDERS`・`COMBINED_BUILDERS`）。全23項目×3状態の例は `tests/test_reasons.py` の `SCENARIOS` で組み立てて確かめている。

## inventory（v3 で追加・説明の一覧）

スキル・エージェント・コネクタが「何をするものか」を、**名前を使わずに1文ずつ**並べたもの。名前なし・名前つきのどちらの結果にも必ずある（3つの配列とも必ずある。空の配列もありうる）。

| キー | 型 | 決まり |
|---|---|---|
| `inventory.skills[]` | オブジェクト | キーは `summary`・`category`・`used_30d` の3つだけ |
| `inventory.agents[]`・`inventory.connectors[]` | オブジェクト | キーは `summary`・`used_30d` の2つだけ |
| `summary` | 文字列 | 1〜80字・改行なし。何をするものかの1文。作れなかったときは「（説明を作れませんでした）」（全角の括弧） |
| `category` | 文字列 | 「集計」「資料」「メール」「相談」「調べもの」「自動化」「その他」のどれか |
| `used_30d` | 整数か null | 直近30日に使われた回数（0以上）。数えられないとき（Codex のもの、会話の記録が無いとき）は null |
| 各配列の長さ | — | 300件まで。超えた数は `reference.inventory_truncated` |

- 並びは `used_30d` の多い順（null は最後）、同じ回数なら `summary` の文字順。名前の順・頭文字・文字数など、名前を逆算できる情報は入れない。
- 数えている範囲: Claude Code のスキル・エージェント・コネクタ（設定にあるものと、会話の記録に出たもの）、Codex のスキル・エージェント。Codex のコネクタは名前を集めていないので入らない。同じ名前のものが両方の道具にあれば1つにまとめる。
- **説明はお客様の PC の AI が書く**（`AGENTS.md` の手順3）。`score.py` が機械で検査し、1つでも当たれば捨てて「（説明を作れませんでした）」に置き換える。置き換えた数は `reference.inventory_summaries_replaced`。AIが書かなかった・`ai_targets.json` が無いときも同じ文になり、点検そのものは止まらない。
- 検査の中身（`inventory.py` の `check_summary`）:
  - そのもの自身の名前、ほかのスキル・エージェント・コネクタの名前、作業フォルダの場所の各段・定時実行の名前と、それらを `-` `_` `.` `/` 空白などで割った部分が、文字として含まれていないか。大文字小文字・全角半角・ハイフンと空白の違いはならして比べる。日本語2文字以下・英数字2文字以下の短い名前と、下の一般語は、普通の言葉と区別できないので比べない
  - 英字は「AI」「PDF」「CSV」「HTML」「Web」「SNS」「PC」「3D」だけを許す。ほかの英字の並びは止める（製品名・英字の名前・識別子を止めるため）
  - パス・拡張子つきの名前・URL・メール・英数字の識別子らしい語（`kebab-case`・`snake_case`・`CamelCase`）・記号 `/` `\` `~` `@` `:` `<` `>` など・7桁以上の数字の並び・80字超え・改行・制御文字
  - 社名・人名らしい印（`propernoun.py`）: 株式会社・有限会社・合同会社・(株)・(有)・御中、固有の語の後ろの工務店・ホーム・ハウス・建設・不動産・事務所・商事・商店（「ホームページ」「ハウスメーカー」「建設業」「地域の工務店」「設計事務所」のような一般の言い方は通す）、漢字・カタカナの名前の後ろのさん・様・氏・くん・ちゃん・部長・課長・社長・店長（「お客様」「担当者様」「皆様」「社長向け」「営業部長」は通す）
- **説明の中の社名や人名は、機械では見つけきれません。** 印の付かない固有名詞（「田中の週報」、カタカナだけの社名・商品名、地名や案件名）は通ってしまうので、送るスキル（sho-san-share）の下見で説明の一覧を本人に全部見せ、目を通してもらってから送ります。

## v2・v3・v4 の違い

| | v2 | v3 | v4 |
|---|---|---|---|
| `schema_version` | 2 | 3 | 4 |
| `items.<ID>` のキー | `name`・`pillar`・`judge`・`judge_label`・`status` | 左の5つ＋`reason`・`facts` | 左の7つ＋`usage_tier`（F6・F9・F11以外はnull） |
| 一番上 | — | `inventory` が増える | `usage_this_month`・`tool_counts` が増える |
| `reference` | — | `inventory_truncated`・`inventory_summaries_replaced` が増える（名前なし・名前つきとも）。名前つき（`names_included: true`）のときだけ `named` があるのは v2 と同じ | 変わらない |
| `pillars`・`next_fixes` | — | 変わらない | 変わらない（キーの形は同じ。`pillars.<p>.rate` の**計算の仕方**だけが変わる。15章・5-10） |

- 読む側は `schema_version` で分ける。v2 には `reason`・`facts` が無く、v2・v3 には `usage_tier`・`usage_this_month`・`tool_counts` が無い。**この挙動は本リポジトリの `render.py` に限った話**（どの版の `result.json` を渡されても、その版に無いキーの枠を出さないだけで動く）。
- **送り先（送るスキル sho-san-share・事例ボックス）は、現状 `schema_version` を見て版を判定しており、知らない版（v4）は拒否する。** 「未知のキーは無視すれば動く」は保証されていない。v4 を受け付けるには送り先側の対応が別途必要（送り先の修正は別作業として扱う。このリポジトリ側の対応は、この事実を正しく書くところまで）。
- `score.py` は v4 の `facts.json`（`collect.py` が出すもの）しか受け付けない。古い `facts.json` を渡すと止まるので、`collect.py` からやり直す。
- v4で`pillars.<p>.rate`の**計算の仕方**が変わった点に注意: v3までは「○の数÷判定できた数」。v4は、段階評価のある項目（F6・F9・F11）がある柱では「部分点の合計÷判定できた数」。段階評価の無い柱（安全・育つ仕組み・任せ方）は、○＝1／×＝0のままなので計算結果は変わらない。

## 守っていること

- フォルダ名・ファイルパス・キーの値・ファイルの本文は入らない。`reason`・`facts` も同じ（上の「入らないもの」）。
- **スキル・エージェント・コネクタの名前は、`names_included: true`（`--show-names`）のときだけ入る**。既定は数字だけ（名前なし）。
- `status` は3値のみ（`pass` / `fail` / `unmeasured`）。`unmeasured` は点数の分母から外れている。
- 柱の `rate` が `null` の柱は、点数の平均から除外されている（`score.py` 側で処理済み）。
- キーの走査は `repo`（リポジトリの中）と `config`（設定ファイルの中）を分けて持つ。値そのものは入らない。
- `usage_this_month`・`tool_counts`・`usage_tier` に入るのは数（秒・トークン・本数・回数・段階）だけ。名前・場所は入らない（v4）。

## ひな形を差し替えるときの注意

- `templates/report.html` を差し替える場合、`render.py` の `render_cover` / `render_pillar_pages` / `render_reference_page` / `render_blindspots_page` が読む項目は、この表の中のキーだけです。
- `render.py` 側も新しいひな形の構造に合わせて直す必要があります（`render.py` は「`result.json` → HTML」の変換ロジックを持っているため、ひな形だけの差し替えでは完結しません）。純粋にデータだけを差し替え可能にするなら、ひな形側で JS を使い `result.json` を直接読み込む形に作り替えることもできますが、本リポジトリの既定実装は Chrome の `--print-to-pdf` での確実な印刷を優先し、Python 側で静的HTMLを生成する方式を採っています。
- 「意味のない識別子」の判定（UUID・16進羅列など）は `render.py` の `is_meaningless_identifier` にある。ひな形を書き換えるときもこの関数は再利用できる。
