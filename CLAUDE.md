# Bassly

ベース演奏者向けのAI学習支援ツール。TABを「数字の列」ではなく音楽的な語彙
（コードトーン、ペンタトニック、半音アプローチ…）として理解し、
「理解によって記憶量を圧縮する」ことを支援する。

**まず [docs/philosophy.md](docs/philosophy.md) を読むこと。**
機能追加で迷ったら判断基準は「この機能は、ユーザーが音楽を"理解"する助けになるか」。

## 構成

- `bassly/domain.py` — Pydanticモデル。不確実なデータは `source` / `confidence` を持つ
- `bassly/theory.py` — 決定的な音楽理論 (音名・度数)。AI非依存・テスト必須
- `bassly/tabtext.py` — テキストTAB形式 (1小節=16トークン、16分グリッド) のパーサ
- `bassly/cli.py` — Typer CLI: `bassly show` (音名表示) / `bassly tab` (ASCII TAB描画)
- `data/songs/<slug>/` — ユーザーの曲データ (song.yaml, tab.txt, audio/)。
  **gitignore対象**: 著作権のあるTAB・音源・転記をリポジトリに含めない
- `data/user.yaml` — ユーザープロファイル (notation・表示設定・習熟度の自己申告)。
  曲の事実と分離。将来のOSS/SaaS分離では「ユーザーモデル」層になる
- `lessons/*.md` — 汎用理論の1枚ペラ (自作・OSS候補)。語彙タグから just-in-time で
  練習ページに紐づく。用語はScrapbox風に相互リンクされる
- `tests/` — 自作スニペットのみ使用 (著作物を含めない)

要望のトリアージ: ①全ベーシストに正しい→機能/デフォルト ②好み・学習スタイル→
user.yaml ③今の習熟度の話→skills (時間で変わる)。迷ったらユーザーと相談。

## コマンド

```bash
uv run pytest -q
uv run bassly show data/songs/polaris --bars 5-12     # 音名+コード表示
uv run bassly tab data/songs/polaris --bars 5-12      # ASCII TAB (検証用)
uv run bassly analyze data/songs/polaris --bars 29-32 # 度数+語彙タグ (根拠)
uv run bassly sheet data/songs/polaris                # レベル2譜面 (output/level2.md)
uv run bassly practice data/songs/polaris             # 練習ページ (output/practice.html)
```

現在のフェーズ: ドッグフーディング。ユーザーが practice.html とレベル2譜面で
ポラリスを練習し、チャットで質問・フィードバック→改善を繰り返す。
解釈の一文は data/songs/polaris/analysis/phrases.yaml で編集する。

## 設計原則 (要点)

- 人間をループに入れる: AI/PDF/Moises由来のデータは全て人間が修正できる
- 構造化データ (音名・度数・コード) と自然言語の説明を分離する
- 根拠を保持する: 「ペンタトニック」と判定したらどの音とコードの関係からかを追跡可能に
- 練習メニューは必ず実際の曲の演奏につなげる
- 作り込みすぎない (マイクロサービス、完全自動採譜などはやらない)

## ユーザーコンテキスト

- 5弦ベース (BEADG)。セクション名は日本式 (Aメロ/Bメロ/サビ/Cメロ/間奏)
- 課題曲: Aooo「ポラリス」(G♭メジャー, 179bpm, 159小節, 5線TAB PDF)
- Moisesデスクトップアプリからコード/セクションを画面自動化で取り込み済み
  (手順は `~/.claude/projects/.../memory/moises-app-automation.md`)
