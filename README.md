# Campus Clinic Finder

大学生が空きコマで行ける宮崎県の病院・診療所を探し、受診時間や費用、口コミを記録できるWeb版MVPです。県外施設と薬局は検索候補に含めません。出発地点は登録大学の所在地です。

詳しい要件は [SPEC.md](./SPEC.md) を参照してください。

## 必要な環境

- Python 3.10以上
- Node.js（daisyUIの認証画面CSSを再生成する場合）
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

アプリはログイン必須です。初回ログイン後、ニックネーム（公開名・1〜20文字）・大学・学年・性別（回答しないも選択可能）を登録すると検索・受診記録へ進めます。既存ユーザーもニックネーム未登録なら登録画面が表示され、登録済みの大学・学年・性別を引き継いで追加入力できます。検索・記録APIでも本人認証とプロフィール登録を確認します。

「登録して始める」で進めない場合は、ボタンの近くに表示される入力エラーを確認してください。大学名は文字を入力した後、候補から選択します。保存中はボタンが「登録中…」になり、失敗しても入力内容を残して再試行できます。「ニックネームを保存できませんでした」と出る場合は、更新前のPythonサーバーが起動したままの可能性があります。起動したターミナルで `Ctrl+C` を押し、`python server.py` で再起動してください。

ログイン後もURLは `/` のままです。画面は同一ページ内で切り替え、Auth0から戻ったときの `code`・`state` はコールバック処理後にURLから取り除きます。確認中はログインボタンを表示せず、コールバック処理をセッション復元より先に行います（[Auth0 SDK公式ドキュメント](https://auth0.com/docs/libraries/auth0-single-page-app-sdk)）。

右上のアカウントアイコンからニックネーム・大学名の確認とログアウトができます。「受診予定なし」などのヘッダー表示と、ヘッダー下のアカウント欄は表示しません。Auth0のプロフィール画像がない場合や読み込めない場合は、ニックネームの頭文字を表示します。メニューは外側のタップ・Escape・画面移動で閉じます。ログアウト用のアイコンは [Lucide 0.468.0](https://github.com/lucide-icons/lucide/tree/0.468.0) の同梱SVGを使用し、ライセンスは `assets/icons/LICENSE` に収録しています。

ログアウトではAuth0 SDKの `logout` を呼び、アプリ内のプロフィール・記録・検索結果も消去します。保存済み受診記録とユーザー別の下書きは削除しません。ログアウトしたタブでは `sessionStorage` にフラグを残し、再読み込みで自動ログインしません。次のログインは `prompt: login` で認証し直し、成功したコールバックでフラグを解除します。Auth0との通信失敗時もアプリはログアウト状態に戻します。

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

受診終了後の口コミフォームは、1. 受診条件（初診・再診、予約、費用）、2. よかった点・助かったこと、3. そう感じた場面（任意・2000文字まで）、4. 次に行く学生へ伝えたいこと（任意・1000文字まで）の4段階です。受診条件とよかった点は、公開・非公開に関係なく必須です。費用は0円も入力できます。待ち時間の入力欄はありません。よかった点は「その他」を含む複数選択で、「特になし・分からない」は他の選択肢と同時には選べません。気になった点も自由に書けます。

宮崎大学の登録者が受診記録を保存すると、口コミも自動で宮大生に公開します。公開するかどうかの選択欄はなく、保存前に公開される旨を表示します。登録プロフィールのニックネーム・受診した月・よかった点・入力した文章と、学年・予約・滞在時間・費用・初診再診を公開します。学年は投稿時の登録プロフィールから「学部4年」「修士1年」などの形で保存します。過去の口コミに学年帯しか残っていない場合はそのまま表示します。文章の2項目は空欄でも投稿できます。ニックネームの再入力、メール認証の手動確認、公開プレビューは不要です。過去に保存した非公開記録を自動で公開することはありません。以前の下書きで非公開にした個別項目は引き続き非公開にします。記録一覧から公開を取り消しても自分の受診記録は残ります。公開ニックネーム・学年はサーバーが登録プロフィールから取得し、投稿データで別の値を指定しても採用しません。

公開口コミは `reviews` テーブルに保存し、病院IDで取得します。本名・性別・メールアドレス・Auth0ユーザーID・元の記録IDは返しません。受診月は到着日時から日本時間でサーバーが算出し、「2026年10月」のように表示します。正確な受診日時は、投稿者が別途「受診日時（月日・到着〜終了時刻）も公開する」を選択した場合のみ返します。この同意は初期状態でオフで、過去の口コミへ日時を自動追加しません。日時を公開すると本人の受診が推測される可能性があることをフォームに明示します。日時は日本時間で表示し、日をまたぐ場合は終了日も表示します。名前や受診日時を自由文やニックネームへ書くとそのまま公開されるため注意してください。

閲覧・投稿自体は引き続き登録大学による制限で、大学メール未確認でもバッジなしで投稿できます。大学選択の固定や、全利用者の在籍確認を必須にする制限は行っていません。

### 大学メール認証バッジ

「宮崎大学メール認証済み」は、サーバーがAuth0の `/userinfo` にアクセストークンで問い合わせ、本人の `sub`・`email_verified: true`・メールドメイン `student.miyazaki-u.ac.jp` のすべてを確認できた場合にだけ付与します。学生メールのドメインは[宮崎大学情報基盤センター](https://www.cc.miyazaki-u.ac.jp/service/email-stu.php)の案内に基づきます。教職員用ドメインや、末尾に別のドメインを付けたアドレスは対象外です。

投稿時にサーバーが自動確認するため、口コミフォームで認証を確認する操作は不要です。クライアントから送った認証済みフラグは信用しません。確認に失敗した場合はバッジを付けずに記録・口コミを保存します。バッジは投稿時点のメール確認状態で、受診内容そのものを証明するものではありません。

Auth0側では大学メールのアカウントに確認メールを送れるよう、メールプロバイダーとメール確認テンプレートを設定してください。利用者は確認リンクを開き、再ログインします。このアプリが大学メールを直接送信する仕組みではありません。SDKは `openid profile email` を要求します（[Auth0 `/userinfo` の説明](https://support.auth0.com/center/s/article/troubleshooting-issues-with-utilizing-the-userinfo-endpoint)）。Auth0管理画面のメール設定や実際のメール配達は自動変更・検証していません。

大学選択は `db/20260825-mxt_chousa01-000011635_6.csv` に配置した文部科学省の学校コード一覧（2026年5月1日時点・暫定版）から大学を抽出した `data/universities.json` を使用します。出典: https://www.mext.go.jp/b_menu/toukei/mext_01087.html 。大学名・都道府県を入力すると候補が表示され、クリックまたは上下キーとEnterで選択できます。学校コードで保存するため同名校も区別します。大学の選択は在籍証明にはなりません。

大学一覧の再生成:

```powershell
python scripts/build_universities.py
```

生成処理はローカルCSVを読み、外部ダウンロードは行いません。CSVを更新したらこのコマンドを実行し、生成JSONもGitへ反映してサーバーを再起動します。小容量の学校コードCSVはGit対象、大容量の病院CSVは引き続き除外します。

出発地点は登録大学の所在地に固定し、現在地検索と端末の位置情報取得は行いません。登録大学の学校コードから所在地を取得します。宮崎大学は木花、同志社大学は今出川の既存座標を使用し、それ以外は国土地理院の住所検索で登録住所から位置を取得し、ユーザー記録DBの `university_locations` テーブルへキャッシュします。検索対象は常に宮崎県内のため、県外の大学を登録しても近隣の県外施設は表示しません。大学選択の候補表示はローカルデータだけで行い、外部APIへ送信しません。

住所からの位置は所在地の目安で、通学先キャンパスや入口と異なる場合があります。複数キャンパスの選択には未対応です。住所を取得できない場合は時間をおいて再度検索してください。

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

> `python -m http.server` では施設検索APIが動きません。必ず `python server.py` で起動してください。

## 普段の起動

施設DBを一度生成した後は、次のコマンドだけで起動できます。

```powershell
cd "C:\同志社大学\4回生\github\tomodachi-boeing-v2"
python server.py
```

## データの再生成

### 施設検索用SQLite

元CSVを更新した場合に実行します。SQLiteには全国データを残し、検索APIで住所が `宮崎県` から始まる病院・診療所だけを抽出します。DBや元CSVから県外の行を削除する必要はありません。

```powershell
python scripts/build_facility_db.py
```

## 宮崎県の施設検索

- 登録大学から半径12km以内の、宮崎県内の病院・診療所だけをSQLiteから検索
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

到着・終了日時を手入力すると、その場で院内滞在時間を更新します。「入力した時刻を反映」を押さずに記録を保存しても、入力欄の日時を使用します。日をまたぐ場合は終了日も変更してください。終了が到着より前など、不正な日時のままでは保存できません。

- 集計対象は自分の完了済み記録と、閲覧可能な他の宮大生の公開口コミで滞在時間も公開されている記録です。他人の非公開記録や滞在時間非公開の口コミは対象外です。
- 平均は1分単位で切り上げます。同じ受診記録を保存し直しても二重計上せず、口コミの公開取り消しも次回検索から反映します。
- 有効な記録がない病院は従来の施設種別の目安（病院60分・診療所35分）を使います。未完了、滞在時間なし、0以下などの無効な記録は集計しません。
- 戻れる時刻は `出発時刻 + 行きの移動時間 + 平均院内滞在時間 + 帰りの移動時間` で算出し、指定した戻り時刻との差で判定します。記録保存後、再検索すると新しい平均を取得します。

個々の受診日付・時刻・ユーザーIDは検索APIへ返しません。以前削除した「実測データ」「滞在時間データ」の表示欄は復活させません。平均はあくまで目安で、個別の待ち時間を保証するものではありません。

### 費用目安

検索結果の「費用目安」と病院詳細の「費用」は、閲覧可能な宮大生の公開口コミの費用を病院IDごとに平均し、`平均 1,501円` のように表示します。平均は1円単位で四捨五入します。

- 自分の記録も含め、非公開の記録と費用非公開の口コミは集計しません。
- 費用の未入力・不正な値は除外し、入力された0円は含めます。自由文の金額ではなく、費用入力欄の値を使います。
- 表示用の最新50件だけではなく、対象病院の公開費用を全件集計します。同じ記録の再保存で二重計上はしません。
- 公開費用がない病院は「データなし」と表示します。修正や公開取り消しは再検索で反映します。

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

### 検索で施設が表示されない

1. `data/facilities.sqlite3` が存在するか確認する
2. `python server.py` で起動しているか確認する
3. 登録大学から12km以内に宮崎県内の対象診療科の施設があるか確認する
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

- 宮崎県内の病院・診療所検索（薬局・県外施設は対象外）
- 診療科、出発時刻、戻り時刻、移動手段による絞り込み
- 登録大学の所在地からの検索（現在地検索なし）
- OpenStreetMap + OSRMによる往復経路時間
- 滞在時間、費用目安、予定に間に合うかの表示
- 病院詳細と匿名口コミ
- 手動での到着・受診終了記録
- 費用、予約有無、待ち時間の記録
- ローカルストレージ保存
- カレンダー形式の受診ログと月間サマリー
