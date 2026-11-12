# v1.5.6 番号保全・復元の運用手順

部署コードと社員番号の発行履歴は、DBとは別の署名付きJSON記録にも保全する。保存先は `NUMBERING_LEDGER_PATH` で指定する。未指定時は `.local/numbering-ledger.json` を使用する。複数のWebプロセスは同じファイルとロックファイルにアクセスする必要がある。`DJANGO_SECRET_KEY` を変更すると署名を検証できなくなるため、鍵も別途安全に保全する。

## 初回導入

1. DBをバックアップする。既存データには `operations/legacy_department_mapping.json` の確認済み対応表を使用する。
2. `python manage.py migrate` を実行する。
3. `python manage.py migrate_legacy_numbering --mapping-file operations/legacy_department_mapping.json --actor-number <有効な管理者番号> --dry-run` で対象を確認する。
4. `--dry-run` を外して移行し、`python manage.py numbering_ledger initialize` を実行する。既存の保全記録は上書きされない。
5. `python manage.py numbering_ledger verify` が成功すること、A03の部署選択とA07の登録履歴が一致することを確認する。

## 定期バックアップ

DBバックアップと番号保全記録、署名に使用する鍵を、DB障害で同時に失われない保管先へ保存する。PostgreSQLのDBバックアップには `scripts/backup_postgres.py`、SQLiteには `scripts/backup_sqlite.py` を使用できる。これらのスクリプトは番号保全記録を含めないため、別途保存する。整合した組を取得する際はA03/A07の書き込みを止め、`numbering_ledger verify`、DBバックアップ、保全記録のコピー、再度の `verify` の順に実行し、同じ世代として管理する。保管先、暗号化、実行間隔、保持期間、監視担当は導入先の運用決定事項とする。

## 不整合時

照合失敗時はA07登録とA03採番が停止する。DBと保全記録の双方を退避し、原因を調べる。`initialize` で上書きして解消しない。

- DBのバックアップを復元した後、保全記録に存在する部署・登録結果・番号履歴・A05登録監査だけが欠けている場合は、有効な業務管理者が `python manage.py numbering_ledger restore --actor-number <管理者番号>` を実行する。既存データとの衝突や社員番号の不一致があれば停止する。
- DBへの登録は確定し、保全記録だけが `pending` の場合は、操作IDとDB上の登録結果を確認し、`python manage.py numbering_ledger reconcile --actor-number <管理者番号> --reason <照合理由>` を実行する。処理の監査がA05に残る。DBに結果がなければ再開できない。
- 復元・再開後は `python manage.py numbering_ledger verify` を実行し、A03の部署選択、A07の同一操作ID再送、A05監査を確認する。

本番の保全先と復元・再開の責任者はU02の決定後に設定する。ローカル試験では `.local/` を使用した。
