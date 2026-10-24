# Campus Clinic Finder

宮崎大学生が空きコマで行ける宮崎県の病院・診療所を探し、受診時間や費用、口コミを記録できるWeb版MVPです。県外施設と薬局は検索候補に含めません。登録大学は宮崎大学、出発地点は木花キャンパスに固定しています。

詳しい要件は [SPEC.md](./SPEC.md) を参照してください。

## 必要な環境

- Python 3.10以上
- PostgreSQL 17（ローカルではDocker Composeでも起動可能）
- Node.js（daisyUIの認証画面CSSを再生成する場合）
- インターネット接続（OSRMの経路検索に使用）

DB接続とAuth0のトークン検証に必要なパッケージをインストールします。

```powershell
python -m pip install -r requirements.txt
```

## PostgreSQLのセットアップ

病院・診療科・プロフィール・受診記録・口コミをPostgreSQLに保存します。実行中にSQLiteは使いません。接続先は `.env` または環境変数の `DATABASE_URL` で指定します。未設定・接続失敗時にSQLiteやデモデータへ切り替わることはありません。

新しい環境でDockerを使う場合:

```powershell
docker compose up -d --wait postgres
# .env がない場合だけ実行
Copy-Item .env.example .env
python -m pip install -r requirements.txt
python scripts/migrate_to_postgres.py
python server.py
```

```dotenv
DATABASE_URL=postgresql://campus_clinic:local-development-only@127.0.0.1:5433/campus_clinic
```

`compose.yaml` はPC内の `127.0.0.1:5433` にだけ公開し、DB本体をDockerボリュームへ保存します。上記パスワードはローカル開発専用です。本番には使わないでください。`POSTGRES_PASSWORD` を変更する場合は `DATABASE_URL` も合わせます。既存ボリュームのパスワードは環境変数の変更だけでは変わりません。

このPCでは、既存のシステム用PostgreSQLとは別に `.local/postgres/data` の専用DBを用意しています。Dockerは同時に起動しないでください。PC再起動後などの起動・終了コマンド:

```powershell
& "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe" -D ".local/postgres/data" -l ".local/postgres/postgres.log" -o "-h 127.0.0.1 -p 5433" start
python server.py
# アプリを Ctrl+C で終了してからDBを停止
& "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe" -D ".local/postgres/data" stop
```

この専用DBはlocalhost接続のみの開発用trust認証です。外部公開や本番利用はせず、本番は管理サービスのパスワード・TLS付き接続を使ってください。`.local` はGit・Dockerへの同梱対象外です。

### SQLiteからの初回移行

旧バージョンのアプリを終了してから実行してください。元ファイルは読み取り専用で開き、削除・上書きしません。

```powershell
python scripts/migrate_to_postgres.py
# 記録の保存場所が異なる場合
python scripts/migrate_to_postgres.py --records "C:\path\to\user-records.sqlite3"
# 病院データだけを移行する場合
python scripts/migrate_to_postgres.py --facilities-only
```

初期値は `data/facilities.sqlite3` と `data/user-records.sqlite3` です。移行時に限り旧設定 `RECORDS_DATABASE` も読み、`--records` を最優先します。明示した記録ファイルが存在しない場合はエラーになります。プロフィール・記録・口コミのJSON、Auth0ユーザーID、病院ID、口コミの表示順を引き継ぎます。記録ファイルがない新規環境は空の記録DBで始めます。施設・記録それぞれの取り込みを一つのトランザクションで実行し、その単位で失敗時に取り消します。

完了済みの取り込みは `data_imports` に記録し、再実行時はスキップします。退会後にコマンドを再実行しても過去の利用者を復活させません。初回でも移行先にデータがあれば上書きを拒否します。移行後の更新・バックアップの対象はPostgreSQLです。旧SQLiteやそのバックアップには移行時点の個人情報が残るため、運用者がアクセス制限・保管期限を管理してください。

### テスト

```powershell
python -m unittest discover -s tests -v
# UIテスト用パッケージとブラウザ
python -m pip install playwright
python -m playwright install chromium
python scripts/check_onboarding_ui.py
```

テストは接続先DBにランダムな専用スキーマを作成し、終了時にそのスキーマだけを削除します。アプリのデータは変更しません。`TEST_DATABASE_URL` を設定すると別のテスト専用DBを使えます。スキーマの作成権限が必要です。接続先はテスト用・ローカルDBを指定し、本番DBには接続しないでください。

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
docker compose up -d --wait postgres
python scripts/migrate_to_postgres.py
python server.py
```

`.env` はGit管理・Dockerイメージへの同梱対象外です。設定は次のとおりです。Client Secretは不要です。

```dotenv
AUTH0_DOMAIN=dev-dv16o3zjae8nchix.jp.auth0.com
AUTH0_CLIENT_ID=4ShIE6ZNaKmHQHpL1zzEjVaRbOigG2sB
AUTH0_AUDIENCE=https://campus-clinic-api
DATABASE_URL=postgresql://campus_clinic:local-development-only@127.0.0.1:5433/campus_clinic
```

PowerShellやデプロイ環境に設定済みの環境変数は `.env` より優先します（[python-dotenv](https://bbc2.github.io/python-dotenv/)）。手動で環境変数を設定する場合は次のとおりです。

```powershell
$env:AUTH0_DOMAIN = "dev-dv16o3zjae8nchix.jp.auth0.com"
$env:AUTH0_CLIENT_ID = "4ShIE6ZNaKmHQHpL1zzEjVaRbOigG2sB"
$env:AUTH0_AUDIENCE = "https://campus-clinic-api"
python server.py
```

作成済みアプリがRegular Web Applicationの場合は、Applicationsのアプリ設定でApplication TypeをSingle Page Applicationに変更し、Token Endpoint Authentication MethodがNoneになっていることを確認します。APIのバックエンド言語選択はサンプル表示用で、このPythonアプリへC#コードを追加する必要はありません。現在の記録APIは本人のユーザーIDでアクセスを制限するため、カスタム権限・ロールの追加は不要です。

アプリはログイン必須です。初回ログイン後、ニックネーム（公開名・1〜20文字）・学年・性別（回答しないも選択可能）を登録すると検索・受診記録へ進めます。大学の入力欄・候補選択はありません。サーバーが学校コード `F145110111523`（宮崎大学）を保存し、リクエストで別の大学を指定されても採用しません。既存ユーザーでニックネーム未登録、または以前の他大学登録が残っている場合は、入力済みの項目を引き継いだプロフィール画面で再登録します。過去の受診記録は削除しません。検索・記録APIでも本人認証と宮崎大学プロフィールの登録を確認します。

「登録して始める」で進めない場合は、ボタンの近くに表示されるニックネーム・学年・性別の入力エラーを確認してください。保存中はボタンが「登録中…」になり、失敗しても入力内容を残して再試行できます。「ニックネームを保存できませんでした」と出る場合は、更新前のPythonサーバーが起動したままの可能性があります。起動したターミナルで `Ctrl+C` を押し、`python server.py` で再起動してください。

ログイン後もURLは `/` のままです。画面は同一ページ内で切り替え、Auth0から戻ったときの `code`・`state` はコールバック処理後にURLから取り除きます。確認中はログインボタンを表示せず、コールバック処理をセッション復元より先に行います（[Auth0 SDK公式ドキュメント](https://auth0.com/docs/libraries/auth0-single-page-app-sdk)）。

右上のアカウントアイコンからニックネーム・大学名の確認とログアウトができます。「受診予定なし」などのヘッダー表示と、ヘッダー下のアカウント欄は表示しません。Auth0のプロフィール画像がない場合や読み込めない場合は、ニックネームの頭文字を表示します。メニューは外側のタップ・Escape・画面移動で閉じます。ログアウト用のアイコンは [Lucide 0.468.0](https://github.com/lucide-icons/lucide/tree/0.468.0) の同梱SVGを使用し、ライセンスは `assets/icons/LICENSE` に収録しています。

ログアウトではAuth0 SDKの `logout` を呼び、アプリ内のプロフィール・記録・検索結果も消去します。保存済み受診記録とユーザー別の下書きは削除しません。ログアウトしたタブでは `sessionStorage` にフラグを残し、再読み込みで自動ログインしません。次のログインは `prompt: login` で認証し直し、成功したコールバックでフラグを解除します。Auth0との通信失敗時もアプリはログアウト状態に戻します。

右上のアカウントメニューの「アカウント設定」から、登録済みのニックネーム・学年・性別を変更できます。大学は宮崎大学のままです。`PUT /api/profile` はログイン本人の既存プロフィールだけを更新し、過去の口コミの公開名・学年・認証バッジは投稿時の状態を保持します。変更は今後保存する口コミに反映されます。

設定画面の「退会する」から確認画面を開き、削除確認のチェックを入れると退会できます。`DELETE /api/account` は認証済み本人と `{"confirmation":"delete-account"}` の確認データを要求し、稼働DBのプロフィール・受診記録・口コミを一つのトランザクションで削除します。他人のデータは削除しません。削除後はこの端末の本人の受診中の下書きを消し、アプリからログアウトします。Auth0のログインアカウント自体や別端末のブラウザの下書き、運用者が保管したDBバックアップは削除しません。Auth0アカウントで再ログインするとプロフィールの新規登録へ進み、削除した記録は復元されません。退会済みプロフィールへの古い更新リクエストや記録保存で削除データを再作成しないように、存在確認と更新をトランザクション内で実行します。実際の退会操作は取り消せません。

Auth0の **Allowed Logout URLs** には、実際に開くURLを末尾の `/` まで一致させて登録してください。`returnTo` の登録が必要な点は [Auth0 LogoutOptions](https://auth0.github.io/auth0-spa-js/interfaces/LogoutOptions.html) を参照してください。ローカルで使用する例:

```text
http://127.0.0.1:8000/
http://localhost:8000/
http://127.0.0.1:8001/
http://localhost:8001/
```

Auth0側の許可URL設定や実際のSSOセッション終了はローカルの自動テストでは検証していません。通信エラー時の表示や再読み込み・再ログインの制御は、SDKをモックしたブラウザテストで検証しています。

ログイン後に最初の画面へ戻る場合は、画面上部に表示されるエラーコードを確認してください。`invalid_audience` はAPI Identifier、`invalid_issuer` はDomainの不一致です。`token_not_yet_valid` はトークンの発行時刻とPC・サーバーの時計にずれがあるため、日時の自動設定を確認します。トークン検証では60秒までの時計のずれを許容しますが、署名・発行元・Audienceの検証は省略しません。エラー調査のためにアクセストークンや `code` 付きURLを共有する必要はありません。

受診記録とプロフィールはAuth0のユーザーIDにひも付き、本人だけが閲覧できます。受診中の下書きはユーザー別にブラウザへ保存し、完了した記録はサーバーへ保存します。旧バージョンの共通ブラウザ記録は残しますが、自動で特定のユーザーへ移しません。

自分のログは「月の一覧」「日付から探す」のどちらも口コミと共通のカード表示です。病院名・診療科の下に、受診日時、受診条件とよかった点、文章、滞在時間・費用を表示します。自分のログではアイコン・名前・学年・認証バッジのプロフィール行を省きます。ログ・口コミとも「公開中」などの状態ラベルは表示しません。病院の口コミでは投稿者のプロフィールと認証バッジを引き続き表示します。自分のログには、口コミで個別に非公開にしている費用なども本人用として表示します。

受診終了後の口コミフォームは、1. 受診条件（初診・再診、予約、費用）、2. よかった点・助かったこと、3. そう感じた場面（任意・2000文字まで）、4. 次に行く学生へ伝えたいこと（任意・1000文字まで）の4段階です。受診条件とよかった点は必須です。費用は0円も入力できます。待ち時間の入力欄はありません。よかった点は「その他」を含む複数選択で、「特になし・分からない」は他の選択肢と同時には選べません。気になった点も自由に書けます。

宮崎大学の登録者が受診記録を保存すると、口コミも自動で宮大生に公開します。公開するかどうかの選択欄と記録一覧の公開切り替えボタンはありません。APIも保存時に公開扱いとし、旧クライアントから非公開を指定しても公開します。旧公開取り消しAPI（`DELETE /api/reviews`）は405を返します。登録プロフィールのニックネーム・受診日時・よかった点・入力した文章と、学年・予約・滞在時間・費用・初診再診を公開します。学年は投稿時の登録プロフィールから「学部4年」「修士1年」などの形で保存します。文章の2項目は空欄でも投稿できます。ニックネームの再入力、メール認証の手動確認、公開プレビューは不要です。以前の下書きで非公開にした個別項目は引き続き非公開にします。公開ニックネーム・学年はサーバーが登録プロフィールから取得し、投稿データで別の値を指定しても採用しません。

運営者の指定により、過去の非公開・公開取り消し済みの完了記録も口コミに公開します。`python server.py` 起動時に `publish_all_reviews()` が移行し、プロフィールを宮崎大学へ登録し直した場合はその利用者の過去分も移行します。元の記録は削除せず、すでにある公開口コミの文章・ニックネーム・学年・認証バッジは変更しません。移行は繰り返しても重複投稿しません。本文・受診日時は公開されますが、メールアドレス・性別・内部ユーザーIDなどは公開しません。未完了や到着・終了日時が不正な記録、登録プロフィールがない記録は公開対象外です。公開中の病院の平均滞在時間・平均費用にも反映されます。

公開口コミは `reviews` テーブルに保存し、病院IDで取得します。本名・性別・メールアドレス・Auth0ユーザーID・元の記録IDは返しません。すべての公開口コミに受診日時（月日・到着〜終了時刻）を表示し、日時を公開するかのチェックボックスはありません。既存の公開口コミも、同じ投稿者・記録IDに対応する受診記録の到着・終了日時を使って表示します。元の記録がない過去の口コミは、保存されている情報のみ表示します。日時から本人の受診が推測される可能性があることを投稿フォームに明示します。日時は日本時間で表示し、日をまたぐ場合は終了日も表示します。本文やニックネームに個人情報を含めないでください。

大学は宮崎大学に固定していますが、大学メールによる利用制限や在籍確認は必須にしていません。大学メール未確認でもバッジなしで投稿でき、大学名の固定だけで在籍を証明するものではありません。他大学プロフィール向けの動作確認用例外は廃止しました。

### 大学メール認証バッジ

大学メールの認証バッジは、サーバーがAuth0の `/userinfo` にアクセストークンで問い合わせ、本人の `sub`・`email_verified: true`・対応メールドメインのすべてを確認できた場合にだけ付与します。大学名は登録プロフィールや投稿データではなく、確認できたメールドメインから判定します。メールアドレス自体は口コミへ保存・公開しません。

- `student.miyazaki-u.ac.jp`: 口コミのプロフィール行の右端に宮崎大学のマークと「認証済み」を表示します。読み上げとツールチップは「宮崎大学メール認証済み」とし、大学による公式認定ではなくメール確認の表示であることを説明します。[宮崎大学情報基盤センター](https://www.cc.miyazaki-u.ac.jp/service/email-stu.php)の学生メール案内に基づきます。マークは[大学公式サイト](https://www.miyazaki-u.ac.jp/guide/ideal/)の原画像を同梱し、出典は `assets/universities/README.md` に記載しています。公開前に大学のマーク利用条件を確認してください。
- `mail.doshisha.ac.jp`、`mail1.doshisha.ac.jp`〜`mail4.doshisha.ac.jp`: 動作確認用に認証対象とし、口コミでは宮崎大学メールの人と同じ「宮崎大学マーク＋認証済み」を表示します。認証データは同志社大学のまま保持し、読み上げ・ツールチップ・アカウント欄は「同志社大学メール認証済み」と表示します。メール利用例は同志社大学の[メール転送案内](https://www.doshisha.ac.jp/files/ois/news/jpn_25spring_forwarding.pdf)、[学内登録案内](https://www.doshisha.ac.jp/files/bunjm/page/2024%E5%B9%B4%E5%BA%A6%E8%8B%B1%E6%96%87%E5%AD%A6%E7%A7%91%E3%82%AA%E3%83%B3%E3%83%A9%E3%82%A4%E3%83%B3%E7%99%BB%E9%8C%B2%E7%9B%B8%E8%AB%87URL%E3%83%AA%E3%82%B9%E3%83%88.pdf)、[演習ガイダンス](https://sports.doshisha.ac.jp/files/spojm/page/guidance2024.pdf)で確認できます。同志社女子大学のメールや類似ドメインは認証バッジの対象外です。メールにかかわらず登録プロフィールの大学と検索の出発地点は宮崎大学に固定です。

確認できた大学は `verifiedEmailUniversity` としてバッジと一緒に保存します。過去の大学種別なし・認証済み口コミは従来どおり宮崎大学のバッジを表示します。ログイン後とアカウント欄を開いたときにも、サーバーがメール認証を確認します（正常確認後30秒以内の重複確認は省略）。認証済みなら、本人の既存の公開口コミにもバッジを反映します。ほかの利用者の口コミや、非公開・公開取り消し済みの記録には反映しません。文章・費用・日時の公開設定を変更したり、記録を新しく公開したりする処理ではありません。

投稿時もサーバーが自動確認するため、口コミフォームで認証を確認する操作は不要です。クライアントから送った認証済みフラグは信用しません。確認に失敗した新規投稿にはバッジを付けず、記録・口コミ自体は保存します。ログイン時の確認に失敗しただけで既存のバッジを取り消すことはありません。バッジはメール確認状態を表し、受診内容そのものや在籍を証明するものではありません。

バッジが付かない場合は、右上のアカウント欄で状態を確認してください。メール未確認、対象外ドメイン、メール情報の不足、確認APIへの通信失敗を表示します。未確認の場合はAuth0の確認メールのリンクを開いてから再ログインしてください。メール情報が不足している場合は、アプリが一度トークンを更新して再確認します。トークンやメールアドレス全体を共有せず、表示された状態で切り分けできます。

Auth0側では大学メールのアカウントに確認メールを送れるよう、メールプロバイダーとメール確認テンプレートを設定してください。利用者は確認リンクを開き、再ログインします。このアプリが大学メールを直接送信する仕組みではありません。SDKは `openid profile email` を要求します（[Auth0 `/userinfo` の説明](https://support.auth0.com/center/s/article/troubleshooting-issues-with-utilizing-the-userinfo-endpoint)）。Auth0管理画面のメール設定や実際のメール配達は自動変更・検証していません。

宮崎大学の学校コード・正式名称は `data/universities.json` を参照します。元データは `db/20260825-mxt_chousa01-000011635_6.csv` に配置した文部科学省の学校コード一覧（2026年5月1日時点・暫定版）です。出典: https://www.mext.go.jp/b_menu/toukei/mext_01087.html 。全国の大学データと変換スクリプトは保持しますが、登録画面での候補表示や `/api/universities` の公開は行いません。

大学一覧の再生成:

```powershell
python scripts/build_universities.py
```

生成処理はローカルCSVを読み、外部ダウンロードは行いません。CSVを更新したらこのコマンドを実行し、生成JSONもGitへ反映してサーバーを再起動します。小容量の学校コードCSVはGit対象、大容量の病院CSVは引き続き除外します。

出発地点は宮崎大学・木花キャンパスの既存座標に固定し、現在地検索と端末の位置情報取得は行いません。他大学の選択や住所検索は登録・病院検索の処理では使用しません。検索対象は常に宮崎県内です。

固定座標はキャンパスの目安で、建物や入口と異なる場合があります。複数キャンパスの選択には未対応です。

### 公開環境の保存先

Northflank等の環境変数に `AUTH0_DOMAIN`、`AUTH0_CLIENT_ID`、`AUTH0_AUDIENCE` と、管理PostgreSQLの接続URL `DATABASE_URL` を設定します。

アプリ本体の永続ボリュームは不要です。データは独立したPostgreSQLに保存され、アプリの再デプロイでも残ります。DBのバックアップ・保持期間を別途設定してください。`RECORDS_DATABASE` は廃止しました。Auth0は認証用で、受診記録自体は保存しません。

Dockerビルド時にローカルのユーザー記録DBや `.env` は同梱しません。

## 初回セットアップ

### 1. リポジトリへ移動

```powershell
cd "C:\同志社大学\4回生\github\tomodachi-boeing-v2"
```

### 2. 元データを配置

`data/facilities.sqlite3` がある場合は次の元CSV配置・生成を省略できます。全国CSVはGit管理に含めていません。初回移行用データを作り直す場合だけ、次のファイルを `db` フォルダへ配置してください。

```text
db/
├── 01-1_hospital_facility_info_20260601.csv
├── 01-2_hospital_speciality_hours_20260601.csv
├── 02-1_clinic_facility_info_20260601.csv
├── 02-2_clinic_speciality_hours_20260601.csv
└── 05_pharmacy_20260601.csv
```

### 3. 初回移行用の施設データを生成

```powershell
python scripts/build_facility_db.py
```

生成先：

```text
data/facilities.sqlite3
```

### 4. PostgreSQLへ移行してアプリを起動

```powershell
docker compose up -d --wait postgres
python scripts/migrate_to_postgres.py
python server.py
```

ブラウザで次を開きます。

```text
http://127.0.0.1:8000
```

終了するときは、PowerShellで `Ctrl + C` を押してください。

> `python -m http.server` では施設検索APIが動きません。必ず `python server.py` で起動してください。

## 普段の起動

PostgreSQLが起動していて、初回移行と `.env` の設定が済んでいれば、次のコマンドで起動できます。

```powershell
cd "C:\同志社大学\4回生\github\tomodachi-boeing-v2"
python server.py
```

## データの再生成

### 初回移行用のSQLite

初回取り込み元のデータを作るコマンドです。アプリは生成したSQLiteを直接検索しません。PostgreSQLへ全国データを取り込み、検索APIで住所が `宮崎県` から始まる病院・診療所だけを抽出します。

```powershell
python scripts/build_facility_db.py
```

移行済みのDBには、SQLiteの再生成や移行コマンドの再実行だけでは変更を反映しません。移行済みマーカーを削除してユーザー記録を取り込み直すことはしないでください。

## 宮崎県の施設検索

- 登録大学から半径12km以内の、宮崎県内の病院・診療所だけをPostgreSQLから検索
- 診療科で絞り込み、移動・受診時間を計算して最大15件を表示
- APIで県を固定しているため、検索パラメーターを変更しても県外施設・薬局は返さない
- 施設APIに接続できない場合はエラーを表示し、同梱データやデモ施設への切り替えは行わない

以前の `data/facilities.js` とその生成スクリプトはアプリの検索には使用しません。

## 経路時間

OpenStreetMapの道路データとOSRM Table APIを使用し、往路と復路を別々に計算します。

- 対応：徒歩、自転車、車
- 候補15施設を一括検索
- 同じ検索結果はブラウザのセッション内でキャッシュ
- OSRMへ接続できない場合は直線距離による概算へ切り替え

現在はOSRMの公開デモサーバーを使用しています。非商用のMVP・検証用途向けで、アクセスは1秒に1回以下へ制限しています。本番運用ではOSRMのセルフホストまたはSLAのあるサービスへ切り替えてください。

### 院内滞在時間と戻れる時刻

検索時に受診記録を病院IDごとに集計し、「院内滞在」に平均値を表示します。各記録の滞在時間は、到着日時と受診終了日時の差からサーバーが計算した値です。入力データの `stayMinutes` をそのまま信用せず、手入力と時刻ボタンのどちらも同じ計算で保存します。

到着・終了日時を手入力すると、その場で院内滞在時間を更新します。反映ボタンはなく、自動で入力内容を反映します。記録の保存には到着・終了の両方の日時が必要です。日をまたぐ場合は終了日も変更してください。終了が到着より前など、不正な日時のままでは保存できません。

- 集計対象は自分の完了済み記録と、閲覧可能な他の宮大生の公開口コミで滞在時間も公開されている記録です。他人の非公開記録や滞在時間非公開の口コミは対象外です。
- 平均は1分単位で切り上げます。同じ受診記録を保存し直しても二重計上しません。
- 有効な記録がない病院は従来の施設種別の目安（病院60分・診療所35分）を使います。未完了、滞在時間なし、0以下などの無効な記録は集計しません。
- 戻れる時刻は `出発時刻 + 行きの移動時間 + 平均院内滞在時間 + 帰りの移動時間` で算出し、指定した戻り時刻との差で判定します。記録保存後、再検索すると新しい平均を取得します。

個々の受診日付・時刻・ユーザーIDは検索APIへ返しません。以前削除した「実測データ」「滞在時間データ」の表示欄は復活させません。平均はあくまで目安で、個別の待ち時間を保証するものではありません。

### 費用目安

検索結果の「費用目安」と病院詳細の「費用」は、閲覧可能な宮大生の公開口コミの費用を病院IDごとに平均し、`平均 1,501円` のように表示します。平均は1円単位で四捨五入します。

- 自分の記録も含め、非公開の記録と費用非公開の口コミは集計しません。
- 費用の未入力・不正な値は除外し、入力された0円は含めます。自由文の金額ではなく、費用入力欄の値を使います。
- 表示用の最新50件だけではなく、対象病院の公開費用を全件集計します。同じ記録の再保存で二重計上はしません。
- 公開費用がない病院は「データなし」と表示します。修正は再検索で反映します。

初診・再診や診療内容などで実際の費用は異なるため、平均は参考値です。院内滞在時間や戻れる時刻の計算には影響しません。

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

`data/facilities.sqlite3` は初回のPostgreSQL取り込み元として、例外的にGit管理へ含めます。ユーザー記録・DBバックアップ・接続パスワードはGitへ追加しないでください。

## Northflankへデプロイ

ルートの `Dockerfile` でアプリをビルドし、同じプロジェクトの管理PostgreSQLへ接続します。`compose.yaml` はローカル開発専用で、Northflankでは使いません。`data/facilities.sqlite3` は一度だけ施設を取り込むジョブ用です。元CSV、`.env`、ローカルのユーザー記録やバックアップはイメージへ同梱しません。

### 1. デプロイ用ファイルをGitHubへ反映

```powershell
git add .gitignore .dockerignore .env.example Dockerfile requirements.txt database.py schema.sql server.py user_records.py university_locations.py scripts/migrate_to_postgres.py README.md
git commit -m "Use PostgreSQL for facilities and user records"
git push origin main
```

SQLiteは約58MBあるためGitHubから警告されますが、100MBの上限内です。`db` フォルダのCSVは追加しないでください。

### 2. PostgreSQLとアプリを作成

1. Northflankでプロジェクトを作成する
2. 同じプロジェクトにPostgreSQLのデータベースアドオンを作成する
3. 新しいCombined Serviceを作成する
4. GitHubの `tomodachi-boeing-v2` リポジトリを接続する
5. ブランチに `main` を選択する
6. Build typeに `Dockerfile` を選択する
7. Dockerfile pathを `/Dockerfile`、build contextを `/` にする

### 3. 接続情報を設定し、初回データを移行

アドオンの接続情報をSecret Group経由でアプリへ渡し、接続文字列を `DATABASE_URL` に割り当てます。接続先はNorthflankが発行する内部ホスト・ポート・DB名・ユーザー・パスワードを使い、ローカル用の値は使いません。TLSはアドオンの設定に合わせ、外部接続時はTLSを有効にしてください。DBをインターネットへ公開する必要はありません。

```text
DATABASE_URL=<管理PostgreSQLの接続文字列>
AUTH0_DOMAIN=<Auth0のDomain>
AUTH0_CLIENT_ID=<Auth0のClient ID>
AUTH0_AUDIENCE=https://campus-clinic-api
HOST=0.0.0.0
PORT=8000
```

施設の初回取り込みは、アプリと同じイメージ・接続用Secretを使う一回限りのジョブで実行します。

```sh
python scripts/migrate_to_postgres.py --facilities-only
```

既存のローカル記録も本番へ引き継ぐ場合は、利用者が書き込まない状態にして、安全なDB接続（TLSまたはプライベートな転送）を用意し、ローカルから本番用 `DATABASE_URL` を指定して移行コマンドを実行します。アプリの公開前に完了させてください。接続文字列や記録DBをGitへ追加しないでください。すでに本番へプロフィールを登録している場合は、上書き防止で記録移行を拒否します。

初回移行完了後、通常の `python server.py` でアプリを開始します。以降は再起動・デプロイのたびにSQLiteを取り込みません。自動実行するのはテーブル初期化と既存仕様の公開口コミ更新のみです。

管理DBの作成は[Northflank公式ドキュメント](https://northflank.com/guides/deploy-postgres-database-on-northflank)、Secret Groupと接続文字列の別名は[接続設定](https://northflank.com/docs/v1/application/databases-and-persistence/connect-database-secrets-to-workloads)を参照してください。アドオン側の変数名が `POSTGRES_URI` なら、別名に `DATABASE_URL` を追加します。プラン・料金・無料枠の対象は契約時の管理画面で確認してください。

### 4. 公開ポートとAuth0を設定

Networkingで次のポートを追加します。

```text
Port: 8000
Protocol: HTTP
Public: ON
```

ポートにNorthflankの公開サブドメインを割り当てます。発行されたHTTPS URLをAuth0のAllowed Callback URLs・Allowed Logout URLs・Allowed Web Originsにも登録してから開いてください。

管理PostgreSQLはアプリとは別にバックアップを設定してください。Northflankへのデプロイ・本番DBへの移行は、このローカル作業だけでは実行されません。

## トラブルシューティング

### `/api/auth-config` が404になる

`python -m http.server` やLive Serverでは認証APIは動きません。そのサーバーを終了し、Auth0環境変数を設定したPowerShellから `python server.py` を実行してください。仮想環境を使う場合は `.\.venv\Scripts\python.exe server.py` で起動します。

8000番を使っているサーバーを終了できない場合は、起動前に `$env:PORT = "8001"` を設定し、`http://localhost:8001/` を開きます。Auth0のAllowed Callback URLsとAllowed Logout URLsにも `http://localhost:8001/`、Allowed Web Originsには `http://localhost:8001` を登録してください。

### 検索で施設が表示されない

1. `DATABASE_URL` の接続先PostgreSQLが起動しているか確認する
2. `python server.py` で起動しているか確認する
3. 登録大学から12km以内に宮崎県内の対象診療科の施設があるか確認する
4. PowerShellにAPIエラーが出ていないか確認する

施設データが未登録の場合は、初回移行を実行します。

```powershell
python scripts/migrate_to_postgres.py --facilities-only
```

### OSRMの時間が取得できない

インターネット接続を確認してください。OSRM公開サーバーが利用できない場合、アプリは直線距離による概算時間を表示します。

### 8000番ポートが使用中

先に起動しているサーバーを `Ctrl + C` で終了してから、もう一度起動してください。

## 実装済み

- 宮崎県内の病院・診療所検索（薬局・県外施設は対象外）
- 診療科、出発時刻、戻り時刻、移動手段による絞り込み
- 登録大学の所在地からの検索（現在地検索なし）
- OpenStreetMap + OSRMによる往復経路時間
- 滞在時間、費用目安、予定に間に合うかの表示
- 病院詳細と匿名口コミ
- 手動での到着・受診終了記録
- 費用、予約有無、よかった点・文章の記録
- PostgreSQLへの保存（受診中の下書きはブラウザ保存）
- カレンダー形式の受診ログと月間サマリー
