# ハーネス点検

AIエージェント（Claude Code、Codex など）を使っている人が、自分の「ハーネス」（AIの周りに置く設定・指示・道具の一式）を自分で点検する道具です。

使い方は1つです。利用者が自分のAIに「このリポジトリを読んで、手順どおりに私の環境を点検して」と頼みます。AIが手順書（`AGENTS.md` / `CLAUDE.md`）に従って事実を集め、点数つきのレポート（PDF）を出します。

## 何を読むか

- `items.json`（点検項目の定義）
- `collect.py` と `readers/` 配下（事実を集めるスクリプト。読むだけ・通信なし）
- 利用者の設定フォルダ（`~/.claude`、`~/.codex`、作業フォルダの Git 管理下のテキスト）

## 何を読まないか・何をしないか

- インターネット通信は一切しない。
- 起動されうる命令は3つだけに固定されている（`readers/common.py`）: `git ls-files -z`・`git remote`（引数なし）・Chrome での出力フォルダ内HTML→PDF書き出し。任意の引数を渡せる汎用の入口は無い。
- 利用者のPCへの書き込みは、出力フォルダ（既定 `harness-check-output/`）の中だけ。
- `.env` など Git の対象外になっている秘密ファイルは読まない（スキャン対象に含めない）。
- キーの値・フォルダ名・ファイルの本文・会話の本文は、レポートに出さない。**スキル・エージェント・コネクタの名前も、既定では出さない**（`--show-names` を付けたときだけ出す）。

## 使い方（人が直接動かす場合）

```bash
python3 collect.py --workdir . --out ./harness-check-output
# facts.json にある「AIへの質問」に、ai_targets.json のファイルを実際に読んで答え、
# ai_judgments.json を作る（AIが行う）
python3 score.py --out ./harness-check-output
python3 render.py --out ./harness-check-output
```

名前つきのレポートが欲しいときは `collect.py` に `--show-names` を付ける。

**人に渡してよいのは `report.pdf` と `report.html` だけです。** `facts.json`・`result.json`・`ai_judgments.json`・`ai_targets.json` は手元用（フォルダ名などが入りうる）です。レポートができたら `ai_targets.json` は消してください。

詳しい手順は `AGENTS.md` を参照してください（AIが点検を行うときの正本です）。

## テスト

```bash
python3 -m unittest discover -s tests
```

**`python3 -m unittest`（引数なし）は何もテストを実行せずに成功と表示するので使わないこと。**
必ず `discover -s tests` を付ける。

## ファイル構成

```
harness-check/
├── README.md            このファイル
├── AGENTS.md             AIへの手順書
├── CLAUDE.md             AGENTS.md と同じ内容
├── items.json            点検項目の定義（23項目）
├── collect.py            事実を集めて facts.json を出す
├── readers/
│   ├── common.py          道具共通の読み取りユーティリティ
│   ├── claude_code.py     Claude Code 用の読み取り部品
│   └── codex.py           Codex 用の読み取り部品
├── score.py               facts.json と ai_judgments.json から result.json を出す
├── render.py              result.json とひな形から HTML と PDF を出す
├── templates/report.html  レポートのひな形（差し替え可能・result.json だけを読む）
├── tests/                 見本の設定フォルダを使った自動テスト
└── docs/
    ├── SPEC.md             仕様書（採点の正本）
    └── RESULT_SCHEMA.md    ひな形が読む result.json の形
```

## 仕様

採点の中身・項目の定義は `docs/SPEC.md` が正本です。仕様を変えるときは、先にこのファイルを直してください。
