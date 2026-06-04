<h1 align="center">⚔️ 三省六部 · Edict</h1>

<p align="center">
  <strong>私は1,300年前の帝国制度を使って、AIマルチエージェント協調アーキテクチャを再設計しました。<br>結果、古人は現代のAIフレームワークよりも権力分立を深く理解していたのです。</strong>
</p>

<p align="center">
  <sub>12のAIエージェント（11の業務ロール＋1の互換ロール）が三省六部を構成：太子が振り分け、中書省が立案、門下省が審査・封駁、尚書省が配分、六部＋吏部が並列実行。<br>CrewAIにはない<b>制度的レビュー</b>。AutoGenにはない<b>リアルタイムダッシュボード</b>。</sub>
</p>

<p align="center">
  <a href="#-デモ">🎬 デモを見る</a> ·
  <a href="#-30秒クイック体験">🚀 30秒体験</a> ·
  <a href="#️-アーキテクチャ">🏛️ アーキテクチャ</a> ·
  <a href="#-機能全景">📋 ダッシュボード機能</a> ·
  <a href="docs/task-dispatch-architecture.md">📚 アーキテクチャドキュメント</a> ·
  <a href="README.md">中文</a> ·
  <a href="README_EN.md">English</a> ·
  <a href="CONTRIBUTING.md">貢献する</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/OpenClaw-Required-blue?style=flat-square" alt="OpenClaw">
  <img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Agents-12_Specialized-8B5CF6?style=flat-square" alt="Agents">
  <img src="https://img.shields.io/badge/Dashboard-Real--time-F59E0B?style=flat-square" alt="Dashboard">
  <img src="https://img.shields.io/badge/License-MIT-22C55E?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/Frontend-React_18-61DAFB?style=flat-square&logo=react&logoColor=white" alt="React">
  <img src="https://img.shields.io/badge/Backend-FastAPI_+_PostgreSQL_+_Redis-EC4899?style=flat-square" alt="FastAPI + PostgreSQL + Redis">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/公衆号-cft0808-07C160?style=for-the-badge&logo=wechat&logoColor=white" alt="WeChat">
</p>

---

## 🔱 メンテナンスフォークのお知らせ

> これは [cft0808/edict](https://github.com/cft0808/edict) の **downstream fork** です。以下の変更を検証し、upstream PR として整理することを目的としています：

| 変更点 | 状態 | 説明 |
|------|------|------|
| **DB-first タスク状態** | ✅ 実装済み | PostgreSQL + Redis Streams 駆動、`task_source_mode.py` で切替 |
| **Telegram ワークフロー** | ✅ 実装済み | 通知チャネルを Feishu から Telegram に移行、source channel 追跡 |
| **繁体字中国語ローカライズ** | ✅ 実装済み | Dashboard 全インターフェース繁体字対応、`fanti_convert.py` ツール |
| **ローカルデプロイ強化** | ✅ 実装済み | systemd user service、`.env` キー管理、edict.sh 全サービス管理 |
| **セキュリティ強化** | ✅ 実装済み | API Key バックエンド認証、動的パスワード生成、監査ログ |
| **Windows 互換性** | 🚧 検証中 | パス解析、シェルスクリプトのクロスプラットフォーム対応 |
| **コードコメント補完** | 🚧 進行中 | RULES.md に基づき中国語の必要コメントを補完 |

> 上流の [cft0808/edict](https://github.com/cft0808/edict) は三省六部 AI マルチエージェント協調アーキテクチャのオリジナルプロジェクトです。本 fork の変更は順次 PR として上流に還元されます。

## 🆕 最近の更新（2026-06）

- **タスクデータソースを DB-first に変更**：Dashboard `live-status` が `db/json/auto` モード切替に対応、デフォルトは `db` を推奨。
- **モード切替 CLI**：`scripts/task_source_mode.py` を新規追加、データソースモードの照会・切替とバックエンドヘルス状態の確認が可能。
- **フロー一貫性の強化**：メインパスは **Event Bus** を基準とし、CLI はトラブルシューティングとリカバリのみに使用。
- **モデル設定のアップグレード**：各 Agent が LLM と THINK を個別に切替可能、モデルドロップダウンは runtime で利用可能な項目を優先表示。
- **バックエンドセキュリティ強化**：書き込みエンドポイントで API Key 認証を強制、パスワード/キーは `.env` で一元管理、デフォルト値は動的ランダム生成に変更。
- **通知チャネルの Telegram 化**：Feishu から Telegram に移行、dispatch がタスクのソースチャネルを自動追跡し優先的に返信。
- **Dispatch 統一リファクタリング**：重複していた配分ロジックを排除、`openclaw` パス解析を統一、指数バックオフリトライに対応。
- **繁体字中国語ローカライズ**：`scripts/fanti_convert.py` を新規追加、Dashboard 全インターフェースが繁体字中国語に対応。
- **デッドコード削除**：35個の `_fanti` 重複ファイル、`channels/__init__.py` の残留コードを削除。
- **安定性修正**：互換レイヤーと同期パスの修正を完了、現在のテスト結果は **225 passed**。
- **Dashboard タスク分類修正**：`isEdict()` が UUID 形式タスクを正しく識別し、小タスクと誤分類されないよう修正。
- **システムデプロイ自動化**：`systemd/` テンプレート（5つの user service）と `.env.example` を追加、`install.sh` が `install-services` + `init_env` に対応。
- **バックエンド設定の集中化**：`config.py` に7つの Settings フィールドを追加（stall 閾値、dispatch タイムアウト、リトライ回数、Dashboard port など）、Worker のハードコードを排除。
- **Dashboard 安定性強化**：`STATE_LABEL` 未定義、`loadAll()` 競合状態、`isEdict()` が JJC- のみマッチ、`EventBus.get_pending` 欠落、`flow_log` 重複フィールドを修正。
- **Dashboard port 環境変数化**：`DASHBOARD_PORT` / `EDICT_DASHBOARD_PORT` に対応、フォールバックは 7891。

```bash
# 現在のデータソースモードを確認
python3 scripts/task_source_mode.py status

# DB モードに切替
python3 scripts/task_source_mode.py set db
```

## 🎬 デモ

<p align="center">
  <video src="docs/Agent_video_Pippit_20260225121727.mp4" width="100%" autoplay muted loop playsinline controls>
    お使いのブラウザは動画再生に対応していません。下のGIFをご覧いただくか、<a href="docs/Agent_video_Pippit_20260225121727.mp4">動画をダウンロード</a>してください。
  </video>
  <br>
  <sub>🎥 三省六部 AI マルチエージェント協調の全フロー実演</sub>
</p>

<details>
<summary>📸 GIFプレビュー（読み込みが速い）</summary>
<p align="center">
  <img src="docs/demo.gif" alt="三省六部 Demo" width="100%">
  <br>
  <sub>Telegram で勅令 → 太子振り分け → 中書省立案 → 門下省審議 → 六部並列実行 → 奏折返信（30秒）</sub>
</p>
</details>

> 🐳 **OpenClawをお持ちでない場合** `docker run -p 7891:7891 cft0808/edict` を一行実行すれば、プリセットのシミュレーションデータでダッシュボード全機能を体験できます。

---

## 🤔 なぜ三省六部なのか？

ほとんどのマルチエージェントフレームワークのパターンは：

> *「さあ、お前たちAI同士で話し合って、結果をくれ。」*

そして、どう処理されたかわからない結果を受け取り、再現も監査も介入もできません。

**三省六部のアプローチは根本的に異なります** — 私たちは中国に1,400年存在した制度アーキテクチャを採用しました：

```
あなた（皇帝） → 太子（振り分け） → 中書省（立案） → 門下省（審議） → 尚書省（配分） → 六部（実行） → 回奏
```

これは派手な比喩ではありません。**真の権力分立と抑制均衡**です：

| | CrewAI | MetaGPT | AutoGen | **三省六部** |
|---|:---:|:---:|:---:|:---:|
| **審査メカニズム** | ❌ なし | ⚠️ オプション | ⚠️ Human-in-loop | **✅ 門下省専任審査 · 封駁可能** |
| **リアルタイムダッシュボード** | ❌ | ❌ | ❌ | **✅ 軍機処 Kanban + タイムライン** |
| **タスク介入** | ❌ | ❌ | ❌ | **✅ 停止 / キャンセル / 再開** |
| **フロー監査** | ⚠️ | ⚠️ | ❌ | **✅ 完全な奏折アーカイブ** |
| **Agent ヘルスモニタリング** | ❌ | ❌ | ❌ | **✅ ハートビート + アクティビティ検出** |
| **モデルホットスワップ** | ❌ | ❌ | ❌ | **✅ ダッシュボードでワンクリック切替** |
| **スキル管理** | ❌ | ❌ | ❌ | **✅ 閲覧 / 追加** |
| **ニュース集約配信** | ❌ | ❌ | ❌ | **✅ 天下要聞 + Telegram プッシュ** |
| **デプロイ難易度** | 中 | 高 | 中 | **低 · ワンクリックインストール / Docker** |

> **コアの差別化：制度的審査 + 完全な可観測性 + リアルタイム介入**

<details>
<summary><b>🔍 なぜ「門下省の審査」が決定的なのか？（クリックで展開）</b></summary>

<br>

CrewAI や AutoGen の Agent 協調モードは **「完了したら提出」** — 誰もアウトプットの品質をチェックしません。QA部門のない会社でエンジニアがコードを書いてすぐ本番反映するようなものです。

三省六部の **門下省** はまさにこの役割を担います：

- 📋 **計画の品質を審査** — 中書省の立案は完全か？サブタスクの分割は妥当か？
- 🚫 **不合格な成果物を封駁** — 警告ではなく、直接差し戻してやり直し
- 🔄 **強制リワークループ** — 基準を満たすまで通過させない

これはオプションのプラグインではありません — **アーキテクチャの一部**です。すべての勅令は必ず門下省を通過します。例外はありません。

これが三省六部が複雑なタスクを処理し、信頼できる結果を出せる理由です：実行レイヤーに到達する前に、必須の品質ゲートが存在するからです。1,300年前、唐の太宗はすでに理解していました — **抑制されない権力は必ず誤りを犯す**のです。

</details>

---

## ✨ 機能全景

### 🏛️ 十二部制 Agent アーキテクチャ
- **太子** メッセージ振り分け —— 雑談は自動返信、勅令のみタスク化
- **三省**（中書·門下·尚書）が立案、審議、配分を担当
- **七部**（戸·礼·兵·刑·工·吏 + 早朝官）が専門実行を担当
- 厳格な権限マトリクス —— 誰が誰にメッセージを送れるか、明確に規定
- **状態遷移検証** —— kanban_update.py が合法的な遷移パスを強制、不正な状態ジャンプは拒否
- 各 Agent が独立した Workspace · 独立した Skills · 独立したモデル
- **勅令データクレンジング** —— タイトル/備考からファイルパス、メタデータ、無効なプレフィックスを自動除去

### 📋 軍機処ダッシュボード（10機能パネル）

<table>
<tr><td width="50%">

**📋 勅令看板 · Kanban**
- 状態列ごとに全タスクを表示
- 省部フィルター + 全文検索
- ハートビートバッジ（🟢アクティブ 🟡停滞 🔴警告）
- タスク詳細 + 完全なフローチェーン
- 停止 / キャンセル / 再開操作

</td><td width="50%">

**🔭 省部スケジューリング · Monitor**
- 各状態のタスク数を可視化
- 部門分布の横棒グラフ
- Agent ヘルス状態リアルタイムカード

</td></tr>
<tr><td>

**📜 奏折閣 · Memorials**
- 完了した勅令を自動的に奏折としてアーカイブ
- 五段階タイムライン：聖旨→中書→門下→六部→回奏
- ワンクリックで Markdown コピー
- 状態フィルター対応

</td><td>

**📜 旨庫 · Template Library**
- 9つのプリセット聖旨テンプレート
- カテゴリフィルター · パラメータフォーム · 所要時間と費用の見積もり
- 勅令プレビュー → ワンクリック発令

</td></tr>
<tr><td>

**👥 官員総覧 · Officials**
- Token 消費ランキング
- アクティビティ · 完了数 · セッション統計

</td><td>

**📰 天下要聞 · News**
- 毎日自動でテクノロジー/金融ニュースを収集
- カテゴリ購読管理 + Telegram プッシュ

</td></tr>
<tr><td>

**⚙️ モデル設定 · Models**
- 各 Agent が LLM と THINK を個別に切替
- 適用後 Gateway を自動再起動（約5秒で反映、モデルとTHINK同期）

</td><td>

**🛠️ スキル設定 · Skills**
- 各省部のインストール済み Skills 一覧
- 詳細表示 + 新規スキル追加

</td></tr>
<tr><td>

**💬 小タスク · Sessions**
- OC-* セッションのリアルタイム監視
- ソースチャネル · ハートビート · メッセージプレビュー

</td><td>

**🎬 上朝儀式 · Ceremony**
- 毎日最初のアクセス時にオープニングアニメーションを再生
- 本日の統計 · 3.5秒で自動消去

</td></tr>
<tr><td>

**🏛️ 朝堂議政 · Court Discussion**
- 複数の官員が議題を巡って部門視点から討論
- LLM 駆動のマルチロールディベート（各部が職責に基づき専門意見を発表）
- 複数ラウンド進行 · 結論のまとめ · 討論記録の保存

</td><td>

</td></tr>
</table>

---

## 🖼️ スクリーンショット

### 勅令看板
![勅令看板](docs/screenshots/01-kanban-main.png)

<details>
<summary>📸 さらに表示</summary>

### 省部スケジューリング
![省部スケジューリング](docs/screenshots/02-monitor.png)

### タスクフロー詳細
![タスクフロー詳細](docs/screenshots/03-task-detail.png)

### モデル設定
![モデル設定](docs/screenshots/04-model-config.png)

### スキル設定
![スキル設定](docs/screenshots/05-skills-config.png)

### 官員総覧
![官員総覧](docs/screenshots/06-official-overview.png)

### セッション記録
![セッション記録](docs/screenshots/07-sessions.png)

### 奏折アーカイブ
![奏折アーカイブ](docs/screenshots/08-memorials.png)

### 聖旨テンプレート
![聖旨テンプレート](docs/screenshots/09-templates.png)

### 天下要聞
![天下要聞](docs/screenshots/10-morning-briefing.png)

### 上朝儀式
![上朝儀式](docs/screenshots/11-ceremony.png)

</details>

---

## 🚀 30秒クイック体験

### Docker ワンクリック起動

```bash
docker run -p 7891:7891 cft0808/sansheng-demo
```
http://localhost:7891 を開けば軍機処ダッシュボードを体験できます。

<details>
<summary><b>⚠️ <code>exec format error</code> が発生した場合（クリックで展開）</b></summary>

**x86/amd64** マシン（Ubuntu、WSL2など）で以下のエラーが表示される場合：
```
exec /usr/local/bin/python3: exec format error
```

これはイメージのアーキテクチャが一致しないためです。`--platform` パラメータを使用してください：
```bash
docker run --platform linux/amd64 -p 7891:7891 cft0808/sansheng-demo
```

または docker-compose（`platform: linux/amd64` が組み込み済み）を使用：
```bash
docker compose up
```

</details>

### フルインストール

#### 前提条件
- [OpenClaw](https://openclaw.ai) がインストール済み
- Python 3.10+
- macOS / Linux

#### インストール

```bash
git clone https://github.com/cft0808/edict.git
cd edict
chmod +x install.sh && ./install.sh
```

インストールスクリプトが自動で以下を実行：
- ✅ 全 Agent Workspace を作成（太子/吏部/早朝を含む、過去の main と互換）
- ✅ 各省部の SOUL.md を作成（ロール人格 + ワークフロールール + データクレンジング規範）
- ✅ `.env` 設定ファイルを生成（API Key とデータベースパスワードを含む、デフォルト値は動的ランダム生成）
- ✅ Agent と権限マトリクスを `openclaw.json` に登録
- ✅ **シンボリックリンクでデータを統一**（各 Workspace の data/scripts → プロジェクトディレクトリ、データの一貫性を確保）
- ✅ **Agent 間通信可視性を設定**（`sessions.visibility all`、メッセージ到達不能問題を解決）
- ✅ **API Key を全 Agent に同期**（設定済み Agent から自動コピー）
- ✅ React フロントエンドをビルド（Node.js 18+ が必要、未インストール時はスキップ）
- ✅ データディレクトリの初期化 + 初回データ同期（官員統計を含む）
- ✅ Gateway を再起動して設定を反映

> ⚠️ **初回インストール**：先に API Key を設定してください：`openclaw agents add taizi`、その後再度 `./install.sh` を実行して全 Agent に同期します。

#### 起動

```bash
# 方法 1：ワンクリック起動（推奨）
chmod +x start.sh && ./start.sh

# 方法 2：個別起動
bash scripts/run_loop.sh &      # データ更新ループ
python3 dashboard/server.py     # ダッシュボードサーバー

# ブラウザで開く
open http://127.0.0.1:7891
```

<details>
<summary><b>🖥️ 本番環境デプロイ（systemd user）</b></summary>

Edict は **user-level systemd** でバックエンドサービスを管理します。root 権限は不要です：

```bash
# systemd user サービスをインストール（リポジトリ内の edict.sh から）
bash edict.sh install-services

# 全サービス起動 / 停止
bash edict.sh start-all
bash edict.sh stop-all

# 個別管理
systemctl --user start edict-backend          # FastAPI バックエンド (port 8000)
systemctl --user start edict-dispatch-worker  # 配分 Worker
systemctl --user start edict-orchestrator     # DAG オーケストレータ
systemctl --user start edict-outbox-relay     # Outbox Relay

# 状態確認 / ログ
bash edict.sh status
journalctl --user -u edict-backend -f         # リアルタイムログ
```

</details>

> 💡 **ダッシュボードはすぐに使用可能**：`server.py` に `dashboard/dashboard.html` が内蔵されています。Docker イメージにはビルド済み React フロントエンドが含まれています。

> 💡 詳細なチュートリアルは [Getting Started ガイド](docs/getting-started.md) をご覧ください。

---

## 🏛️ アーキテクチャ

```
                           ┌───────────────────────────────────┐
                           │          👑 皇帝（あなた）           │
                           │     Telegram · Signal     │
                           └─────────────────┬─────────────────┘
                                             │ 勅令発布
                           ┌─────────────────▼─────────────────┐
                           │          👑 太子 (taizi)            │
                           │    振り分け：雑談は直接返信 / 勅令はタスク化  │
                           └─────────────────┬─────────────────┘
                                             │ 勅令伝達
                           ┌─────────────────▼─────────────────┐
                           │          📜 中書省 (zhongshu)       │
                           │       勅令受理 → 立案 → サブタスク分解    │
                           └─────────────────┬─────────────────┘
                                             │ 審査提出
                           ┌─────────────────▼─────────────────┐
                           │          🔍 門下省 (menxia)         │
                           │       方案審議 → 裁可 / 封駁 🚫       │
                           └─────────────────┬─────────────────┘
                                             │ 裁可 ✅
                           ┌─────────────────▼─────────────────┐
                           │          📮 尚書省 (shangshu)       │
                           │     タスク配分 → 六部調整 → 結果集約    │
                           └───┬──────┬──────┬──────┬──────┬───┘
                               │      │      │      │      │
                         ┌─────▼┐ ┌───▼───┐ ┌▼─────┐ ┌───▼─┐ ┌▼─────┐
                         │💰 戸部│ │📝 礼部│ │⚔️ 兵部│ │⚖️ 刑部│ │🔧 工部│
                         │ データ │ │ 文書  │ │ 開発  │ │ 監査  │ │ 基盤  │
                         └──────┘ └──────┘ └──────┘ └─────┘ └──────┘
                                                               ┌──────┐
                                                               │📋 吏部│
                                                               │ 人事  │
                                                               └──────┘
```

### 各省部の職責

| 部門 | Agent ID | 職責 | 得意分野 |
|------|----------|------|---------|
| 👑 **太子** | `taizi` | メッセージ振り分け、要件整理 | 雑談識別、勅令抽出、タイトル要約 |
| 📜 **中書省** | `zhongshu` | 勅令受理、立案、分解 | 要件理解、タスク分割、方案設計 |
| 🔍 **門下省** | `menxia` | 審議、チェック、封駁 | 品質レビュー、リスク識別、基準管理 |
| 📮 **尚書省** | `shangshu` | 配分、調整、集約 | タスクスケジューリング、進捗追跡、結果統合 |
| 💰 **戸部** | `hubu` | データ、リソース、計算 | データ処理、レポート生成、コスト分析 |
| 📝 **礼部** | `libu` | 文書、規範、報告 | 技術文書、API ドキュメント、規範策定 |
| ⚔️ **兵部** | `bingbu` | コード、アルゴリズム、巡回 | 機能開発、バグ修正、コードレビュー |
| ⚖️ **刑部** | `xingbu` | セキュリティ、コンプライアンス、監査 | セキュリティスキャン、コンプライアンスチェック、レッドライン管理 |
| 🔧 **工部** | `gongbu` | CI/CD、デプロイ、ツール | Docker 設定、パイプライン、自動化 |
| 📋 **吏部** | `libu_hr` | 人事、Agent 管理 | Agent 登録、権限維持、研修 |
| 🌅 **早朝官** | `zaochao` | 毎日の早朝、ニュース集約 | 定期放送、データ集約 |

### 権限マトリクス

> 誰でも好きに送れるわけではありません —— 真の権力分立と抑制均衡

| From ↓ \ To → | 太子 | 中書 | 門下 | 尚書 | 戸 | 礼 | 兵 | 刑 | 工 | 吏 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **太子** | — | ✅ | | | | | | | | |
| **中書省** | ✅ | — | ✅ | ✅ | | | | | | |
| **門下省** | | ✅ | — | ✅ | | | | | | |
| **尚書省** | | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **六部+吏部** | | | | ✅ | | | | | | |

### タスク状態遷移

```
皇帝 → 太子振り分け → 中書立案 → 門下審議 → 配分済 → 実行中 → 審査待ち → ✅ 完了
                      ↑          │                              │
                      └──── 封駁 ─┘                    ブロック Blocked
```

> ⚡ **状態遷移は保護されています**：`kanban_update.py` に `_VALID_TRANSITIONS` ステートマシン検証が組み込まれており、
> 不正な遷移（例：Doing→Taizi）は拒否されログに記録されます。フローの迂回は不可能です。
>
> 🔄 **非同期イベント駆動**：サービス間は Redis Streams EventBus で疎結合通信、Outbox Relay がイベントの信頼性ある配信を保証します。
> すべての状態変更は自動的に監査ログ（`audit.py`）に書き込まれ、完全な追跡が可能です。

### 🔄 非同期バックエンドアーキテクチャ

Edict のタスクフローは **PostgreSQL + Redis Streams** 駆動の非同期バックエンドによって支えられ、イベントの信頼性ある配信と状態の一貫性を確保します：

| サービス | 技術 | 説明 |
|------|------|------|
| **バックエンド API** | FastAPI + SQLAlchemy | タスク/監査/Outbox の永続化、RESTful API（port 8000） |
| **EventBus** | Redis Streams | イベントバス、サービス間の Pub/Sub 疎結合 |
| **Dispatch Worker** | Python asyncio | 並列配分、指数バックオフリトライ + リソースロック |
| **Orchestrator** | DAG 解析 | タスク分解と依存関係のトポロジカルソート |
| **Outbox Relay** | トランザクショナル Outbox | イベントの at-least-once 配信を保証、取りこぼし防止 |

#### Systemd サービス管理

```bash
# 全サービス起動
bash edict.sh start-all

# 個別管理
systemctl --user start edict-backend       # FastAPI バックエンド
systemctl --user start edict-dispatch      # 配分 Worker
systemctl --user start edict-orchestrator  # DAG オーケストレータ
systemctl --user start edict-outbox        # Outbox Relay

# 状態確認
bash edict.sh status
```

#### セキュリティ機構

- **API Key 認証**：すべての書き込みエンドポイントで `X-API-Key` ヘッダーを強制検証
- **.env キー管理**：パスワード/Token は `.env` から一元読み込み、デフォルト値は `secrets.token_urlsafe(32)` で動的ランダム生成
- **監査ログ**：すべての状態変更が自動的に `audit` テーブルに書き込まれ、完全な追跡が可能

---

## 📁 プロジェクト構成

```
edict/
├── agents/                     # 12 Agent の人格テンプレート
│   ├── taizi/SOUL.md           # 太子 · メッセージ振り分け（勅令タイトル規範を含む）
│   ├── zhongshu/SOUL.md        # 中書省 · 立案中枢
│   ├── menxia/SOUL.md          # 門下省 · 審議チェック
│   ├── shangshu/SOUL.md        # 尚書省 · スケジューリング脳
│   ├── hubu/SOUL.md            # 戸部 · データリソース
│   ├── libu/SOUL.md            # 礼部 · 文書規範
│   ├── bingbu/SOUL.md          # 兵部 · 開発実装
│   ├── xingbu/SOUL.md          # 刑部 · コンプライアンス監査
│   ├── gongbu/SOUL.md          # 工部 · インフラ基盤
│   ├── libu_hr/                # 吏部 · 人事管理
│   └── zaochao/SOUL.md         # 早朝官 · 情報ハブ
├── dashboard/
│   ├── dashboard.html          # 軍機処ダッシュボード（単一ファイル · 依存ゼロ · 約3400行）
│   ├── dist/                   # React フロントエンドビルド成果物（Docker イメージ内に含む、ローカルはオプション）
│   ├── auth.py                 # Dashboard ログイン認証
│   ├── court_discuss.py        # 朝堂議政（多官員 LLM 討論エンジン）
│   └── server.py               # API サーバー（Python 標準ライブラリ · 依存ゼロ · 約3200行）
├── edict/backend/              # 非同期バックエンドサービス（SQLAlchemy + Redis）
│   ├── app/models/
│   │   ├── task.py             # タスクモデル + ステートマシン
│   │   ├── audit.py            # 監査ログモデル
│   │   └── outbox.py           # Outbox メッセージモデル
│   ├── app/services/
│   │   ├── event_bus.py        # Redis Streams EventBus
│   │   └── task_service.py     # タスクサービス層
│   └── app/workers/
│       ├── dispatch_worker.py  # 並列スケジューリング + リトライ + リソースロック
│       ├── orchestrator_worker.py  # DAG オーケストレータ
│       └── outbox_relay.py     # トランザクショナル Outbox Relay
├── scripts/
│   ├── run_loop.sh             # データ更新ループ（15秒ごと）
│   ├── kanban_update.py        # ダッシュボード CLI（勅令データクレンジング + タイトル検証 + ステートマシン）
│   ├── tg_cli.py               # Telegram 向けタスク CLI
│   ├── skill_manager.py        # Skill 管理ツール（リモート/ローカル Skills の追加、更新、削除）
│   ├── refresh_watcher.py      # データ変更リスナー
│   ├── sync_from_openclaw_runtime.py
│   ├── sync_agent_config.py
│   ├── apply_thinking_changes.py
│   ├── sync_officials_stats.py
│   ├── fetch_morning_news.py
│   ├── refresh_live_data.py
│   ├── apply_model_changes.py
│   └── file_lock.py            # ファイルロック（複数 Agent の同時書き込み防止）
├── tests/
│   ├── test_e2e_kanban.py      # エンドツーエンドテスト（21アサーション）
│   └── test_state_machine_consistency.py  # ステートマシン一貫性テスト
├── data/                       # ランタイムデータ（gitignore 対象）
├── docs/
│   ├── task-dispatch-architecture.md  # 📚 詳細アーキテクチャドキュメント：タスク配分、フロー、スケジューリングの完全設計（業務＋技術）
│   ├── getting-started.md             # クイックスタートガイド
│   ├── wechat-article.md              # WeChat 記事
│   └── screenshots/                   # 機能スクリーンショット（11枚）
├── install.sh                  # ワンクリックインストールスクリプト
├── start.sh                    # ワンクリック起動（Dashboard + データ更新）
├── edict.service               # systemd サービス設定（本番デプロイ）
├── edict.sh                    # サービス管理スクリプト（start/stop/restart/status）
├── RULES.md                    # 開発ルール（デッドコード/セキュリティ/テスト/ドキュメント規範）
├── .env.example                # 環境変数テンプレート
├── CONTRIBUTING.md             # 貢献ガイド
└── LICENSE                     # MIT License
```

---

## 🎯 使用方法

### AI に勅令を下す

Telegram / Signal で中書省にメッセージを送信：

```
ユーザー登録システムを設計してください。要件：
1. RESTful API（FastAPI）
2. PostgreSQL データベース
3. JWT 認証
4. 完全なテストケース
5. デプロイドキュメント
```

**あとは座って見ているだけ：**

1. 📜 中書省が勅令を受理し、サブタスク配分案を立案
2. 🔍 門下省が審議し、裁可 / 封駁で差し戻し再立案
3. 📮 尚書省が裁可し、兵部 + 工部 + 礼部に配分
4. ⚔️ 各部が並列実行、進捗はリアルタイムで可視化
5. 📮 尚書省が結果を集約し、あなたに回奏

全工程を**軍機処ダッシュボード**でリアルタイム監視可能。いつでも**停止、キャンセル、再開**できます。

### 聖旨テンプレートを使用

> ダッシュボード → 📜 旨庫 → テンプレート選択 → パラメータ入力 → 勅令発布

9つのプリセットテンプレート：週報生成 · コードレビュー · API 設計 · 競合分析 · データレポート · ブログ記事 · デプロイ方案 · メール文案 · スタンドアップ要約

### Agent のカスタマイズ

`agents/<id>/SOUL.md` を編集すれば、Agent の人格、職責、出力規範を変更できます。

### Skills の追加（ネットから接続）

**3つの方法で Skills を追加：**

#### 1️⃣ ダッシュボード UI（最も簡単）

```
ダッシュボード → 🔧 スキル設定 → ➕ リモート Skill 追加
→ Agent + Skill 名 + GitHub URL を入力
→ 確認 → ✅ 完了
```

#### 2️⃣ CLI コマンド（最も柔軟）

```bash
# GitHub から mmx_cli skill を門下省に追加
python3 scripts/skill_manager.py add-remote \
  --agent menxia \
  --name mmx_cli \
  --source https://raw.githubusercontent.com/MiniMax-AI/cli/main/skill/SKILL.md \
  --description "MiniMax マルチモーダル CLI スキル"

# デフォルト skills を指定 agents に一括インポート
python3 scripts/skill_manager.py import-official-hub \
  --agents menxia,shangshu

# 追加済みの全リモート skills を一覧表示
python3 scripts/skill_manager.py list-remote

# 特定の skill を最新バージョンに更新
python3 scripts/skill_manager.py update-remote \
  --agent menxia \
  --name mmx_cli
```

#### 3️⃣ API リクエスト（自動化統合）

```bash
# リモート skill を追加
curl -X POST http://localhost:7891/api/add-remote-skill \
  -H "Content-Type: application/json" \
  -d '{
    "agentId": "menxia",
    "skillName": "mmx_cli",
    "sourceUrl": "https://raw.githubusercontent.com/MiniMax-AI/cli/main/skill/SKILL.md",
    "description": "MiniMax マルチモーダル CLI スキル"
  }'

# 全リモート skills を表示
curl http://localhost:7891/api/remote-skills-list
```

**デフォルトでインポート可能な Skill：**

対応 Skills：
- `mmx_cli` — MiniMax マルチモーダル CLI スキル（テキスト、画像、動画、音声、音楽、検索）

独自の Skills Hub をお持ちの場合は、`OPENCLAW_SKILLS_HUB_BASE` または `~/.openclaw/skills-hub-url` でカスタムソースを設定できます。

詳細は [🎓 リモート Skills リソース管理ガイド](docs/remote-skills-guide.md) をご覧ください。

---

## 🔧 技術的ハイライト

| 特徴 | 説明 |
|------|------|
| **React 18 フロントエンド** | TypeScript + Vite + Zustand 状態管理、13の機能コンポーネント |
| **純 stdlib Dashboard** | `server.py` は `http.server` ベース、依存ゼロ、API + 静的ファイル配信を同時提供 |
| **FastAPI バックエンド** | `edict/backend/` は FastAPI + SQLAlchemy + Redis を使用、EventBus、Outbox Relay、並列スケジューリングなどのサービスを提供 |
| **EventBus イベントバス** | Redis Streams Pub/Sub、サービス間の疎結合通信 |
| **Outbox Relay** | トランザクショナル Outbox パターン、イベントの信頼性ある配信を保証（at-least-once セマンティクス） |
| **ステートマシン監査** | 厳格なライフサイクル状態遷移 + 完全な監査ログ（`audit.py`） |
| **並列スケジューリングエンジン** | Dispatch Worker が並列実行、指数バックオフリトライ、リソースロックに対応 |
| **DAG オーケストレータ** | Orchestrator が DAG ベースのタスク分解と依存関係解決を実施 |
| **Agent 思考の可視化** | Agent の thinking 過程、ツール呼び出し、返却結果をリアルタイム表示 |
| **ワンクリックインストール / 起動** | `install.sh` で自動設定、`start.sh` 一行で全サービス起動 |
| **systemd 本番デプロイ** | `edict.service` で systemd デーモン、起動時自動開始に対応 |
| **15秒同期** | データ自動更新、ダッシュボードにカウントダウン表示 |
| **Dashboard 認証** | `auth.py` がダッシュボードログイン認証を提供 |
| **毎日の儀式** | 初回アクセス時に上朝オープニングアニメーションを再生 |
| **リモート Skills エコシステム** | GitHub/URL からワンクリックでインポート、バージョン管理 + CLI + API + UI に対応 |

---

## 📖 さらに深く理解する

### コアドキュメント

- **[📖 タスク配分フロー完全アーキテクチャ](docs/task-dispatch-architecture.md)** — **必読ドキュメント**
  - 三省六部が複雑なタスクをどのように処理するか、業務設計と技術実装を詳細に解説
  - 網羅内容：9大タスクステートマシン / 権限マトリクス / 4段階スケジューリング（リトライ→エスカレーション→ロールバック）/ Session JSONLデータ融合
  - 完全な使用例、API エンドポイント説明、CLI ツールドキュメントを含む
  - CrewAI/AutoGen との比較：なぜ制度化が自由協調より優れているのか
  - 障害シナリオと復旧メカニズム
  - **このドキュメントを読めば、三省六部がなぜこれほど強力なのか理解できます**（9500字以上、30分で完全理解）

- **[🎓 リモート Skills リソース管理ガイド](docs/remote-skills-guide.md)** — Skills エコシステム
  - ネットから skills を接続・追加、GitHub/Gitee/任意の HTTPS URL に対応
  - デフォルト Skills ソースとカスタム Hub 対応
  - CLI ツール + ダッシュボード UI + RESTful API
  - Skills ファイル規範とセキュリティ保護
  - バージョン管理とワンクリック更新に対応

- **[⚡ Remote Skills クイックスタート](docs/remote-skills-quickstart.md)** — 5分で始める
  - クイック体験、CLI コマンド、ダッシュボード操作例
  - 独自の Skills ライブラリを作成
  - API 完全リファレンス + よくある質問

- **[🚀 クイックスタートガイド](docs/getting-started.md)** — 初心者向け入門
- **[🤝 貢献ガイド](CONTRIBUTING.md)** — 貢献したい方へ

---

## 🔧 よくある問題と解決策

<details>
<summary><b>❌ タスクが常にタイムアウトする / 部下が完了しても太子に返せない</b></summary>

**症状**：六部または尚書省がタスクを完了したが、太子が返信を受け取れず、最終的にタイムアウトする。

**調査手順**：

1. **Agent 登録状態を確認**：
```bash
curl -s http://127.0.0.1:7891/api/agents-status | python3 -m json.tool
```
`taizi` agent の `statusLabel` が `alive` であることを確認します。

2. **Gateway ログを確認**：
```bash
ls /tmp/openclaw/ | tail -5          # 最新ログを特定
grep -i "error\|fail\|unknown" /tmp/openclaw/openclaw-*.log | tail -20
```

3. **よくある原因**：
   - Agent ID の不一致（v1.2 で修正済み：`main` → `taizi`）
   - LLM provider のタイムアウト（自動リトライを追加済み）
   - ゾンビ Agent プロセス（`ps aux | grep openclaw` で確認）

4. **強制リトライ**：
```bash
# 手動で巡回スキャンをトリガー（スタックしたタスクを自動リトライ）
curl -X POST http://127.0.0.1:7891/api/scheduler-scan \
  -H 'Content-Type: application/json' -d '{"thresholdSec":60}'
```

</details>

<details>
<summary><b>❌ Docker: exec format error</b></summary>

**症状**：`exec /usr/local/bin/python3: exec format error`

**原因**：イメージアーキテクチャ（arm64）とホストアーキテクチャ（amd64）が一致しない。

**解決策**：
```bash
# 方法 1：プラットフォームを指定
docker run --platform linux/amd64 -p 7891:7891 cft0808/sansheng-demo

# 方法 2：docker-compose を使用（platform が組み込み済み）
docker compose up
```

</details>

<details>
<summary><b>❌ Skill のダウンロードに失敗する</b></summary>

**症状**：`python3 scripts/skill_manager.py import-official-hub` でエラーが発生する。

**調査**：
```bash
# ネットワーク接続をテスト
curl -I https://raw.githubusercontent.com/MiniMax-AI/cli/main/skill/SKILL.md

# タイムアウトする場合、プロキシを使用
export https_proxy=http://your-proxy:port
python3 scripts/skill_manager.py import-official-hub --agents menxia
```

**よくある原因**：
- 中国本土から GitHub raw リソースへのアクセスにプロキシが必要
- ネットワークタイムアウト（30秒 + 自動リトライ3回に増加済み）
- デフォルト skill ソースにアクセスできない、またはカスタム Skills Hub の設定ミス

</details>

<details>
<summary><b>❌ バックエンドコード修正後も API が古いデータを返す / agent 一覧が更新されない</b></summary>

**症状**：`backend/app/api/agents.py`、`config.py` などの Python ファイルを修正した後も、API が修正前の内容を返す。例：agent 数が合わない、フィールド値が変わらない。

**原因**：Python は `.py` を `__pycache__/*.pyc` にコンパイルしてキャッシュします。`systemctl restart` でバックエンドを再起動する際、`.pyc` のタイムスタンプが `.py` より新しい場合（または複数バージョンの Python が共存してクロスバージョンのキャッシュ混乱が発生した場合）、uvicorn は新しいソースコードではなく古いバイトコードを読み込みます。

**解決策**：バックエンドの Python ファイルを修正した後は、必ずキャッシュを削除してから再起動してください：

```bash
# 1. すべての __pycache__ を削除
find ~/ai-base/core/edict/edict/backend -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# 2. バックエンドを再起動
systemctl --user restart edict-backend

# 3. 検証（agents を例に）
curl -s http://127.0.0.1:8000/api/agents | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Agent count: {len(d[\"agents\"])}')  # 11 であるべき
for a in d['agents']:
    print(f'  {a[\"id\"]:12s} {a[\"name\"]}')
"
```

**予防**：複数の Python バージョン（例：3.11 + 3.12）が同時にインストールされている場合、両者がそれぞれ `.pyc` を生成し、混乱しやすくなります。`edict.sh` やデプロイスクリプトに自動キャッシュクリアの手順を追加することをお勧めします。

</details>

---

## 🗺️ ロードマップ
> 完全なロードマップと参加方法：[ROADMAP.md](ROADMAP.md)

### Phase 1 — コアアーキテクチャ ✅
- [x] 十二部制 Agent アーキテクチャ（太子 + 三省 + 七部 + 早朝官）+ 権限マトリクス
- [x] 軍機処リアルタイムダッシュボード（10機能パネル + リアルタイムアクティビティパネル）
- [x] タスク停止 / キャンセル / 再開
- [x] 奏折システム（自動アーカイブ + 五段階タイムライン）
- [x] 聖旨テンプレートライブラリ（9プリセット + パラメータフォーム）
- [x] 上朝儀式感アニメーション
- [x] 天下要聞 + Telegram プッシュ + 購読管理
- [x] モデルホットスワップ + スキル管理 + スキル追加
- [x] 官員総覧 + Token 消費統計
- [x] 小タスク / セッション監視
- [x] 太子メッセージ振り分け（雑談自動返信 / 勅令タスク化）
- [x] 勅令データクレンジング（パス/メタデータ/プレフィックスを自動除去）
- [x] 重複タスク防止 + 完了タスク保護
- [x] エンドツーエンドテストカバレッジ（21アサーション）
- [x] React 18 フロントエンドリファクタリング（TypeScript + Vite + Zustand · 13コンポーネント）
- [x] Agent 思考過程の可視化（リアルタイム thinking / ツール呼び出し / 返却結果）
- [x] フロントエンド・バックエンド統合デプロイ（server.py が API + 静的ファイル配信を同時提供）

### Phase 2 — 制度深化 🚧
- [ ] 御批モード（手動承認 + ワンクリック裁可/封駁）
- [x] 功過簿（Agent パフォーマンス評価 + モデル推薦 + コスト最適化）
- [x] EventBus イベントバス（Redis Streams 疎結合通信）
- [x] Outbox Relay（トランザクショナルイベント配信）
- [x] ステートマシン監査（厳格なライフサイクル + 監査ログ）
- [x] 並列スケジューリングエンジン（指数バックオフリトライ + リソースロック）
- [x] DAG オーケストレータ（タスク分解 + 依存関係解決）
- [x] Dashboard 認証（ログイン認証）
- [x] ワンクリック起動 / systemd 本番デプロイ
- [ ] 急遞鋪（Agent 間リアルタイムメッセージフロー可視化）
- [ ] 国史館（ナレッジベース検索 + 引用溯源）

### Phase 3 — エコシステム拡張
- [ ] Docker Compose + デモイメージ
- [ ] Notion / Linear アダプター
- [ ] 年度大考（Agent 年間パフォーマンスレポート）
- [ ] モバイル対応 + PWA
- [ ] ClawHub 掲載

---

## 🤝 貢献する

あらゆる形の貢献を歓迎します！詳細は [CONTRIBUTING.md](CONTRIBUTING.md) をご覧ください。

特に歓迎する方向性：
- 🎨 **UI 強化**：ダーク/ライトテーマ、レスポンシブ、アニメーション最適化
- 🤖 **新 Agent**：特定シーンに適した専任 Agent ロール
- 📦 **Skills エコシステム**：各部専用のスキルパック
- 🔗 **統合拡張**：Notion · Jira · Linear · GitHub Issues
- 🌐 **国際化**：日本語 · 韓国語 · スペイン語
- 📱 **モバイル**：レスポンシブ対応、PWA

---

## 📂 事例

`examples/` ディレクトリには実際のエンドツーエンド使用事例が収録されています：

| 事例 | 勅令 | 関係部門 |
|------|------|----------|
| [競合分析](examples/competitive-analysis.md) | 「CrewAI vs AutoGen vs LangGraph を分析せよ」 | 中書→門下→戸部+兵部+礼部 |
| [コードレビュー](examples/code-review.md) | 「この FastAPI コードのセキュリティをレビューせよ」 | 中書→門下→兵部+刑部 |
| [週報生成](examples/weekly-report.md) | 「今週のエンジニアリングチーム週報を生成せよ」 | 中書→門下→戸部+礼部 |

各事例には以下が含まれます：完全な勅令 → 中書省立案 → 門下省審査意見 → 各部実行結果 → 最終奏折。

---

## ⭐ スター履歴

このプロジェクトがあなたの心を動かしたなら、Star をお願いします ⚔️

[![Star History Chart](https://api.star-history.com/svg?repos=cft0808/edict&type=Date)](https://star-history.com/#cft0808/edict&Date)

---

## 📮 朕の邸報——公衆号

> 古は邸報が天下に政令を伝え、今は公衆号が AI アーキテクチャを語る。

<p align="center">
  <img src="docs/assets/wechat-qrcode.jpg" width="220" alt="公衆号 QR コード · cft0808">
  <br><br>
  <b>👆 スキャンして「cft0808」をフォロー —— 朕の技術邸報</b>
</p>

ここで見られるもの：

- 🏛️ **アーキテクチャ分解** —— 三省六部はいかに権力分立と抑制均衡を実現するのか？12 の Agent は各々何を司るのか？
- 🔥 **失敗談の振り返り** —— Agent が喧嘩したらどうする？Token を使い果たしたらどう節約する？門下省はなぜいつも封駁するのか？
- 🛠️ **Issue 修正実録** —— すべてのバグは一道の奏折、朕がいかに朱筆を入れるかを見よ
- 💡 **Token 節約術** —— 1/10 の token で門下省の審査効果を実現する秘密
- 🎭 **Agent キャラ設定の裏話** —— 六部の SOUL.md はどう書かれたのか？

> *「朕が AI を出勤させたら、AI の方が朕より勤勉だった。」* —— フォローすればわかります。

---

## 📄 ライセンス

[MIT](LICENSE) · [OpenClaw](https://openclaw.ai) コミュニティによって構築

---

<p align="center">
  <strong>⚔️ 古の制度で新しき技術を御し、知恵をもって AI を統治する</strong><br>
  <sub>Governing AI with the wisdom of ancient empires</sub><br><br>
  <a href="#-朕の邸報公衆号"><img src="https://img.shields.io/badge/公衆号_cft0808-フォローして最新情報を-07C160?style=for-the-badge&logo=wechat&logoColor=white" alt="WeChat"></a>
</p>
