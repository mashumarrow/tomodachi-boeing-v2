# Campus Clinic Finder

大学生が空きコマで行ける病院・診療所・薬局を探し、受診時間や費用を記録できるWeb版MVPです。

詳しい要件は [SPEC.md](./SPEC.md) を参照してください。

## 必要な環境

- Python 3.10以上
- Node.js（検索用フォールバックデータを再生成する場合のみ）
- インターネット接続（OSRMの経路検索に使用）

追加パッケージのインストールは不要です。

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
data/*.sqlite3
data/*.sqlite3-shm
data/*.sqlite3-wal
__pycache__/
*.pyc
```

## トラブルシューティング

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
