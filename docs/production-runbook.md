# 本番運用手順（v1.4）

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
