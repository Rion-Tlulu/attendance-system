# 本番運用手順（v1.4.3）

## v1.4.3 への切替

1. 更新を停止し、DB・`.env`・ソースの保護されたバックアップを取得する。復元手順と保存先のアクセス権を確認する。
2. 更新後のコードで `python manage.py migrate` を実行する。`corrections.0004` は原打刻・休憩・未完了履歴がなく、旧申請ログで仮勤務と確認できた空レコードだけを申請から切り離して削除する。証拠が不足するレコードは残すため個別確認する。ロールバック時はバックアップからDBを復元する。
3. `python scripts/check_v143.py` で社員番号、入社日、勤務間重複、在籍期間、旧確定版を確認する。対象社員の内部IDと月を記録し、社員や勤怠を自動統合しない。
   有効な業務管理者を運用担当が2人以上確保し、入社日未確認の社員は人事資料で確認して登録する。値を推測して補完しない。旧仮勤務や通知先不明の候補は履歴・原打刻を確認して解決する。
4. 旧確定版に保存済みスナップショットがない月はCSV出力を止める。担当者が旧記録を確認し、理由付きで確定解除して訂正・再照合・再確定する。
5. `python manage.py test` と `python manage.py check --deploy --settings=config.settings_production` を実行し、夜勤の重複、代理申請、出力IDの失効、通知の再実行を確認する。

配布用ZIPや手動コピーには `.gitignore` が適用されない。配布対象をソース・テンプレート・静的ファイル・マイグレーション・依存一覧・手順書に限定し、`.env`、SQLite DB、秘密鍵、バックアップ、`.git`、仮想環境、テスト出力を含めない。作成後はZIPの全エントリを一覧化して確認し、配布先でも環境変数とDBを別経路で設定する。

CSVは同じ出力IDから日次明細と月次集計を取得する。いずれかの社員が確定解除・再確定された場合は旧IDを使わず、新しいIDで両方を取得し直す。社員番号・氏名・部署は文字列列としてPower Queryで読み込み、自動作成された「変更された型」を削除し、`TXT_` 接頭辞を1回だけ除去する。

Power Queryでテキスト型パラメーター `CsvPath` にファイルのフルパスを指定し、詳細エディターに次を設定する。

```powerquery
let
    Input = Csv.Document(File.Contents(CsvPath), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Input),
    Restore = (v as nullable text) as nullable text =>
        if v = null then null
        else if Text.StartsWith(v, "TXT_", Comparer.Ordinal) then Text.Range(v, 4)
        else v,
    Operations = List.Transform({"社員番号", "氏名", "部署"}, each {_, Restore, type text}),
    Result = Table.TransformColumns(Headers, Operations)
in
    Result
```

初回取込とExcel更新時に `0007`、`=1+2`、`TXT_営業`、`TXT_=1+2`、空欄、全角記号、タブ・改行・引用符・カンマを含む値と秒数を照合する。復元済みの表へ同じ処理を再適用しない。

## リリース前確認

1. PostgreSQL の接続と TLS 証明書を確認し、`DJANGO_HSTS_SECONDS=3600` で HTTPS 応答の `Strict-Transport-Security` と `Content-Security-Policy` を実機確認する。初期導入後、HTTPS に問題がなければ HSTS を段階的に 31536000 秒まで延長する。サブドメインと preload は別途確認するまで有効化しない。
   TLS 終端をリバースプロキシに置く場合は、外部からの `X-Forwarded-Proto` をプロキシで破棄・再設定したうえで `DJANGO_TRUST_PROXY_SSL_HEADER=true` を指定する。
2. `python manage.py migrate --settings=config.settings_production` と `python manage.py collectstatic --noinput --settings=config.settings_production` を実行する。Chart.js 4.5.1 は `static/vendor/chartjs/` に固定済みで、外部 CDN へのスクリプト要求が発生しないことを確認する。
   Chart.js 更新時は配布元の確定版の `dist/chart.umd.min.js` とライセンスを差し替え、3画面のグラフと数値表が一致することを再検証する。
3. 管理者、一般社員、権限喪失者で通知の表示、月次確定・解除、CSV のダウンロードを確認する。
4. `python manage.py check --deploy --settings=config.settings_production` を実行する。サブドメインと preload の警告はドメイン全体の HTTPS 条件を確認して判断を記録する。

## 定時ジョブ（Asia/Tokyo）

- 毎日 09:00: `python manage.py notify_incomplete --settings=config.settings_production`
- 毎日 09:15: `python manage.py cleanup_notifications --settings=config.settings_production`
- 毎日、業務開始前の別時刻: `python scripts/backup_postgres.py`（`BACKUP_DIR` は保護されたバックアップ保存先を指定）
- ジョブの終了コードと標準出力を収集し、失敗・未実行時に管理者へ通知する。二重起動を避けるためスケジューラ側で同時実行を禁止する。
- ジョブは `TZ=Asia/Tokyo` で実行する。アプリ設定も `TIME_ZONE=Asia/Tokyo` を使用する。

## PostgreSQL バックアップ・復元

- 毎日、別ホストの保護された保存先に `scripts/backup_postgres.py` で `pg_dump --format=custom --no-owner` を実行する。接続情報は環境変数で渡し、コマンドラインやログへパスワードを出さない。
- 暗号化保存、アクセス権制限、世代管理を行う。バックアップ終了コードとファイルサイズを監視する。
- 月1回、隔離した検証用 PostgreSQL に `pg_restore --clean --if-exists --no-owner --dbname=<staging-database> <backup-file>` で復元し、社員数・勤務数・監査ログ数とアプリの主要画面を確認する。本番 DB へ復元テストしない。
- 復旧目標時間と許容データ損失時間を運用責任者が定め、復元所要時間を記録する。

## 監視と性能

- HTTP 5xx、ログイン失敗の急増、DB 接続失敗、ジョブ失敗、ディスク容量、バックアップ失敗をアラート対象にする。
- `AuditLog` の `AUTH_FAILURE`、`ROLE_CHANGE`、`CSV_EXPORT` と月次確定・解除を定期照合する。監査ログにはパスワードを保存しない。
- 本番相当の PostgreSQL データ量で月次一覧、通知パネル、500人の CSV 出力の応答時間とメモリ使用量を計測し、基準値を記録する。規模に応じてページネーション・クエリ最適化を見直す。
