# 勤怠管理システム

Django 製の勤怠管理アプリです。社員の打刻・修正申請と、管理者の審査・月次確定・社員管理・部署登録に対応します。

## 構成

| 場所 | 内容 |
| --- | --- |
| `accounts/` | ログイン、パスワード、アカウント |
| `attendance/` | 打刻、勤務記録、月次表示 |
| `corrections/` | 勤怠修正申請 |
| `management/` | 管理者画面、部署、採番、月次確定、CSV |
| `notifications/` | 通知 |
| `operations/` | 移行対応表、受入確認記録、番号保全の手順 |
| `docs/` | 本番運用手順 |

## テスト

各アプリのテストは `tests.py` にまとめています。**全件確認は1コマンド**で実行できます。

```powershell
python manage.py test
```

PostgreSQLの並行処理11件も含める場合は、実行前に `DJANGO_DB_ENGINE=postgresql` と `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_HOST`、`POSTGRES_PORT` を環境変数で設定します。SQLiteで実行するとこの11件はスキップされます。日々の修正は該当アプリの `python manage.py test <app_name>` で確認し、受入時にPostgreSQLで全件を1回実行します。

`DJANGO_SECRET_KEY` は環境変数または `.env` に設定します。`db.sqlite3`、`.env`、`.local/` はGitの対象外です。

## v1.5.6 の記録

- [受入確認記録](operations/v1.5.6-acceptance-report.md)
- [番号保全・復元の運用手順](operations/numbering-ledger-runbook.md)
- [既存部署コードの移行対応表](operations/legacy_department_mapping.json)
