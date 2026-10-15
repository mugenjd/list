# MUGENブログ新着記事一覧（GitHub Pages）

## ファイル
- `RSS.html`：一覧表示、タイトル・ブログ名検索、ブログ絞り込み
- `sites.txt`：取得対象ブログ（1行1URL）
- `fetch_articles.py`：RSS/Atom取得、RSSが見つからない場合のHTML解析
- `articles.json`：取得結果（Actionsが生成・更新）
- `fetch-log.txt`：サイトごとの取得状況
- `.github/workflows/update.yml`：毎日1回の自動更新

## GitHubへの設置手順
1. GitHubでPublicリポジトリを作成します。
2. ZIP内のファイル・フォルダをリポジトリのルートにアップロードします（`.github/workflows/update.yml` の場所を変えないでください）。
3. リポジトリの **Settings → Pages** を開き、Build and deployment の Source を **Deploy from a branch**、Branch を `main`（または実際の既定ブランチ）、Folder を `/(root)` にして保存します。
4. **Settings → Actions → General → Workflow permissions** で、可能なら **Read and write permissions** を選び保存します。
5. **Actions** タブ → **Update blog articles** → **Run workflow** で初回実行します。
6. Actionsの実行が成功し `articles.json` が作られたら、Pagesの公開URLに `/RSS.html` を付けて開きます。例：`https://ユーザー名.github.io/リポジトリ名/RSS.html`。

## 更新時刻
Workflowの `cron: "17 16 * * *"` はUTC 16:17、JSTでは毎日01:17です。GitHub Actionsのスケジュール実行には遅延が起きる場合があります。

## 取得の注意
- RSS/Atomが使えるサイトはフィードを優先します。
- RSSが見つからない場合、トップページのHTMLから記事リンクを抽出します。HTML構造によっては取得できないサイトがあります。
- 未来の日付が付いた記事は除外し、1ブログあたり最大5件まで掲載します。公開日時が取得できない記事は未来記事と判定できないため、日時不明のまま対象に含めます。
- `fetch-log.txt` で `FAIL` になったサイトは、RSS URLの追加やサイト別のHTML解析調整が必要です。
- HTML解析のフォールバックは、トップページに表示された記事が対象です。全過去記事を取得するものではありません。
- アクセス拒否、CAPTCHA、ログイン必須、JavaScript描画のみのページは取得できないことがあります。アクセス制限を回避する処理は行いません。
- 毎日の巡回で対象サイトへ過剰なアクセスをしないよう、サイト間に短い待機を入れています。
- 初回実行時に多数のサイトがエラーになっても、取得できたサイトの記事は公開できます。
- RSSに日時がない、またはHTML解析で日付を取得できない記事は日時不明として扱われます。日時不明の記事は表示時の並び順で末尾付近になります。

## サイトを追加・削除する
`sites.txt` を1行1URLで編集してコミットします。`http://` と `https://` のどちらでも登録できます。編集後はActionsが自動実行されます。


## Seesaaブログの取得補足
Seesaaブログでは `index.rdf` に加えて `index20.rdf` もRSS 2.0のURLとして使われます。取得処理は両方を順に試すようにしています。公式ヘルプ： https://faq.seesaa.net/article/422864638.html
