# Campus Clinic Finder

大学生が空きコマで行ける病院・診療所を探し、受診時間や費用、口コミを記録できるWeb版MVPです。薬局は検索候補に含めません。

詳しい要件は [SPEC.md](./SPEC.md) を参照してください。

## 必要な環境

- Python 3.10以上
- Node.js（daisyUIの認証画面CSS、検索用フォールバックデータを再生成する場合）
- インターネット接続（OSRMの経路検索に使用）

Auth0のトークン検証に必要なパッケージをインストールします。

```powershell
python -m pip install -r requirements.txt
```

## 認証画面のスタイル

ログイン・新規登録・プロフィール登録はdaisyUI 5とTailwind CSS 4で構成しています。画面はスマホ幅に収めて中央配置し、長いフォームはスクロールできます。daisyUIは `du-` 接頭辞と `.access-screen` のテーマに限定して導入しています。

生成済みの `ui.generated.css` をGitへ含めているため、通常のPython起動とデプロイ時にNode.jsは不要です。`ui.css` やdaisyUIクラスを変更した場合は次を実行します。

```powershell
npm ci
npm run build:css
```

生成後の `ui.generated.css` もGitへ反映してください。

## Auth0ログインの設定

Auth0で「Single Page Application」を作成し、DomainとClient IDを取得します。
続いて「APIs」でAPIを作成し、Identifierを `https://campus-clinic-api`、署名アルゴリズムを `RS256` に設定します。Client Secretはこのアプリでは使用しません。

アプリのAllowed Callback URLsとAllowed Logout URLsに `http://127.0.0.1:8000/`、Allowed Web Originsに `http://127.0.0.1:8000` を登録します。本番のHTTPS URLも同じ項目に追加してください。localhostで開く場合はそのURLも登録します。

ローカルではプロジェクト直下の `.env` を起動時に自動で読み込みます。初回のみ次を実行し、`.env` のAuth0設定を確認してください。すでに `.env` がある場合はコピーを省略します。

```powershell
Copy-Item .env.example .env
python -m pip install -r requirements.txt
python server.py
```

`.env` はGit管理・Dockerイメージへの同梱対象外です。設定は次のとおりです。Client Secretは不要です。

```dotenv
AUTH0_DOMAIN=dev-dv16o3zjae8nchix.jp.auth0.com
AUTH0_CLIENT_ID=4ShIE6ZNaKmHQHpL1zzEjVaRbOigG2sB
AUTH0_AUDIENCE=https://campus-clinic-api
```

PowerShellやデプロイ環境に設定済みの環境変数は `.env` より優先します（[python-dotenv](https://bbc2.github.io/python-dotenv/)）。手動で環境変数を設定する場合は次のとおりです。

```powershell
$env:AUTH0_DOMAIN = "dev-dv16o3zjae8nchix.jp.auth0.com"
$env:AUTH0_CLIENT_ID = "4ShIE6ZNaKmHQHpL1zzEjVaRbOigG2sB"
$env:AUTH0_AUDIENCE = "https://campus-clinic-api"
python server.py
```

作成済みアプリがRegular Web Applicationの場合は、Applicationsのアプリ設定でApplication TypeをSingle Page Applicationに変更し、Token Endpoint Authentication MethodがNoneになっていることを確認します。APIのバックエンド言語選択はサンプル表示用で、このPythonアプリへC#コードを追加する必要はありません。現在の記録APIは本人のユーザーIDでアクセスを制限するため、カスタム権限・ロールの追加は不要です。

アプリはログイン必須です。ログイン後、大学・学年・性別（回答しないも選択可能）を登録すると検索・受診記録へ進めます。既存ユーザーもプロフィール未登録なら登録画面が表示されます。検索・記録APIでも本人認証とプロフィール登録を確認します。

ログイン後もURLは `/` のままです。画面は同一ページ内で切り替え、Auth0から戻ったときの `code`・`state` はコールバック処理後にURLから取り除きます。確認中はログインボタンを表示せず、コールバック処理をセッション復元より先に行います（[Auth0 SDK公式ドキュメント](https://auth0.com/docs/libraries/auth0-single-page-app-sdk)）。

ログイン後に最初の画面へ戻る場合は、画面上部に表示されるエラーコードを確認してください。`invalid_audience` はAPI Identifier、`invalid_issuer` はDomainの不一致です。`token_not_yet_valid` はトークンの発行時刻とPC・サーバーの時計にずれがあるため、日時の自動設定を確認します。トークン検証では60秒までの時計のずれを許容しますが、署名・発行元・Audienceの検証は省略しません。エラー調査のためにアクセストークンや `code` 付きURLを共有する必要はありません。

受診記録とプロフィールはAuth0のユーザーIDにひも付き、本人だけが閲覧できます。受診中の下書きはユーザー別にブラウザへ保存し、完了した記録はサーバーへ保存します。旧バージョンの共通ブラウザ記録は残しますが、自動で特定のユーザーへ移しません。

受診終了後は費用（円）・予約・待ち時間に加えて、任意の口コミ（2000文字まで）を入力できます。初期状態は本人だけの記録です。宮崎大学を登録した利用者は「宮大生に口コミを公開する」を選び、学年帯・予約の有無・滞在時間・費用の公開を個別に選択できます。投稿前に公開内容を確認でき、公開後は記録一覧から取り消せます。取り消しても自分の受診記録は残ります。

公開口コミは `reviews` テーブルに保存し、病院IDで取得します。閲覧・投稿は宮崎大学の登録者に限定し、氏名・性別・正確な学年・受診日時・Auth0ユーザーID・元の記録IDは返しません。学年帯は登録プロフィールからサーバーで生成します。名前や受診日時などを自由文へ書くと、その文章は公開されるため投稿時に注意してください。既存の記録を自動公開することはありません。サンプル口コミも表示しません。

これは登録大学による制限で、在籍確認ではありません。大学メール認証による宮崎大学への在籍確認や、アプリ全体の大学選択の固定はまだ行っていません。

大学選択は `db/20260825-mxt_chousa01-000011635_6.csv` に配置した文部科学省の学校コード一覧（2026年5月1日時点・暫定版）から大学を抽出した `data/universities.json` を使用します。出典: https://www.mext.go.jp/b_menu/toukei/mext_01087.html 。大学名・都道府県を入力すると候補が表示され、クリックまたは上下キーとEnterで選択できます。学校コードで保存するため同名校も区別します。大学の選択は在籍証明にはなりません。

大学一覧の再生成:

```powershell
python scripts/build_universities.py
```

生成処理はローカルCSVを読み、外部ダウンロードは行いません。CSVを更新したらこのコマンドを実行し、生成JSONもGitへ反映してサーバーを再起動します。小容量の学校コードCSVはGit対象、大容量の病院CSVは引き続き除外します。

出発地点は「自分の大学」「現在地」の2択で、初期値は自分の大学です。登録大学の学校コードから所在地を取得します。宮崎大学は木花、同志社大学は今出川の既存座標を使用し、それ以外は国土地理院の住所検索で登録住所から位置を取得し、ユーザー記録DBの `university_locations` テーブルへキャッシュします。大学選択の候補表示はローカルデータだけで行い、外部APIへ送信しません。

住所からの位置は所在地の目安で、通学先キャンパスや入口と異なる場合があります。複数キャンパスの選択には未対応です。住所を取得できない場合は現在地から検索してください。

### 公開環境の保存先

Northflank等の環境変数にも `AUTH0_DOMAIN`、`AUTH0_CLIENT_ID`、`AUTH0_AUDIENCE` を設定します。ユーザー記録の初期保存先は `data/user-records.sqlite3` です。

公開運用では永続ボリュームを例えば `/records` にマウントし、`RECORDS_DATABASE=/records/user-records.sqlite3` を設定してください。実行ユーザーがそのディレクトリへ書き込める必要があります。ボリュームを用意しないと再デプロイ・再起動でユーザー記録が消える場合があります。複数インスタンスではこのSQLiteを共有せず、外部DBへ移行してください。Auth0は認証用で、受診記録自体は保存しません。

Dockerビルド時にローカルのユーザー記録DBや `.env` は同梱しません。

## 初回セットアップ

### 1. リポジトリへ移動

```powershell
cd "C:\同志社大学\4回生\github\tomodachi-boeing-v2"
```

### 2. 元データを配置

GitHubの容量制限があるため、全国CSVと生成SQLiteはGit管理に含めていません。次のファイルを `db` フォルダへ配置してください。

```text
db/
├── 01-1_hospital_facility_info_20260601.csv
├── 01-2_hospital_speciality_hours_20260601.csv
├── 02-1_clinic_facility_info_20260601.csv
├── 02-2_clinic_speciality_hours_20260601.csv
└── 05_pharmacy_20260601.csv
```

### 3. 全国施設DBを生成

```powershell
python scripts/build_facility_db.py
```

生成先：

```text
data/facilities.sqlite3
```

### 4. アプリを起動

```powershell
python server.py
```

ブラウザで次を開きます。

```text
http://127.0.0.1:8000
```

終了するときは、PowerShellで `Ctrl + C` を押してください。

> `python -m http.server` では全国施設検索APIが動きません。必ず `python server.py` で起動してください。

## 普段の起動

施設DBを一度生成した後は、次のコマンドだけで起動できます。

```powershell
cd "C:\同志社大学\4回生\github\tomodachi-boeing-v2"
python server.py
```

## データの再生成

### 全国検索用SQLite

元CSVを更新した場合に実行します。

```powershell
python scripts/build_facility_db.py
```

### 大学周辺のフォールバックデータ

施設APIへ接続できない場合に使う軽量データです。宮崎大学木花キャンパスと同志社大学今出川キャンパスの各12km圏内を収録します。

```powershell
node scripts/build-facility-data.js
```

生成先：

```text
data/facilities.js
```

## 現在地検索

検索画面の出発地点で「現在地を使う」を選択し、ブラウザの位置情報を許可してください。

- 現在地から半径12km以内を全国施設DBから検索
- 位置情報は検索にだけ使用し、DBやローカルストレージへ保存しない
- 位置情報は `localhost` またはHTTPS環境で利用可能

## 経路時間

OpenStreetMapの道路データとOSRM Table APIを使用し、往路と復路を別々に計算します。

- 対応：徒歩、自転車、車
- 候補15施設を一括検索
- 同じ検索結果はブラウザのセッション内でキャッシュ
- OSRMへ接続できない場合は直線距離による概算へ切り替え

現在はOSRMの公開デモサーバーを使用しています。非商用のMVP・検証用途向けで、アクセスは1秒に1回以下へ制限しています。本番運用ではOSRMのセルフホストまたはSLAのあるサービスへ切り替えてください。

## GitHubへの反映

通常の変更は次の手順で反映します。

```powershell
git status
git add .
git commit -m "変更内容"
git push origin main
```

次の大容量ファイルは `.gitignore` で除外されています。ローカルからは削除されません。

```text
db/*.csv
data/*.sqlite3-shm
data/*.sqlite3-wal
__pycache__/
*.pyc
```

`data/facilities.sqlite3` はNorthflankへのデプロイに必要なため、例外としてGit管理へ含めます。

## Northflankへデプロイ

このリポジトリは、ルートの `Dockerfile` を使ってNorthflankへデプロイできます。全国施設DBはコンテナへ同梱するため、`data/facilities.sqlite3` もGitへ追加します。元CSVは追加しません。

### 1. デプロイ用ファイルをGitHubへ反映

```powershell
git add .gitignore .dockerignore Dockerfile server.py README.md data/facilities.sqlite3
git commit -m "Add Northflank deployment configuration"
git push origin main
```

SQLiteは約58MBあるためGitHubから警告されますが、100MBの上限内です。`db` フォルダのCSVは追加しないでください。

### 2. Northflankでサービスを作成

1. Northflankでプロジェクトを作成する
2. 新しいCombined Serviceを作成する
3. GitHubの `tomodachi-boeing-v2` リポジトリを接続する
4. ブランチに `main` を選択する
5. Build typeに `Dockerfile` を選択する
6. Dockerfile pathを `/Dockerfile`、build contextを `/` にする
7. Developer Sandboxの無料プランを選択する

### 3. 公開ポートを設定

Networkingで次のポートを追加します。

```text
Port: 8000
Protocol: HTTP
Public: ON
```

ポートにNorthflankの公開サブドメインを割り当て、デプロイが完了したら発行されたHTTPS URLを開きます。ログインには上記のAuth0環境変数と、ユーザー記録用の永続保存先も設定します。

> NorthflankのDeveloper Sandboxは無料枠ですが、アカウント確認のため支払い方法の登録が必要です。

## トラブルシューティング

### `/api/auth-config` が404になる

`python -m http.server` やLive Serverでは認証APIは動きません。そのサーバーを終了し、Auth0環境変数を設定したPowerShellから `python server.py` を実行してください。仮想環境を使う場合は `.\.venv\Scripts\python.exe server.py` で起動します。

8000番を使っているサーバーを終了できない場合は、起動前に `$env:PORT = "8001"` を設定し、`http://localhost:8001/` を開きます。Auth0のAllowed Callback URLsとAllowed Logout URLsにも `http://localhost:8001/`、Allowed Web Originsには `http://localhost:8001` を登録してください。

### 現在地検索で施設が表示されない

1. `data/facilities.sqlite3` が存在するか確認する
2. `python server.py` で起動しているか確認する
3. ブラウザで位置情報を許可する
4. PowerShellにAPIエラーが出ていないか確認する

DBがない場合は再生成します。

```powershell
python scripts/build_facility_db.py
```

### OSRMの時間が取得できない

インターネット接続を確認してください。OSRM公開サーバーが利用できない場合、アプリは直線距離による概算時間を表示します。

### 8000番ポートが使用中

先に起動しているサーバーを `Ctrl + C` で終了してから、もう一度起動してください。

## 実装済み

- 全国の病院・診療所・薬局検索
- 診療科、出発時刻、戻り時刻、移動手段による絞り込み
- 宮崎大学、同志社大学、端末の現在地からの検索
- OpenStreetMap + OSRMによる往復経路時間
- 滞在時間、費用目安、予定に間に合うかの表示
- 病院詳細と匿名口コミ
- 手動での到着・受診終了記録
- 費用、予約有無、待ち時間の記録
- ローカルストレージ保存
- カレンダー形式の受診ログと月間サマリー
