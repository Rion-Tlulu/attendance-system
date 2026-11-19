"""
勤怠管理システム：本番用Django設定。

使用方法：
    --settings=config.settings_production

注意：
- 開発用settings.pyを変更しない
- 秘密鍵とDBの配置先は環境変数から取得
- HTTPSでの運用を前提とする
- DB は SQLite の db.sqlite3（既定はプロジェクト直下。移す場合だけ
  DJANGO_SQLITE_PATH に永続ローカル領域の絶対パスを指定）
- バックアップは scripts/backup_sqlite.py（SQLite Online Backup API）
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .settings import *

# ==========================================
# 環境変数の取得
# ==========================================


def required_env(name):
    """必須の環境変数を取得する。"""

    value = os.environ.get(name, "").strip()

    if not value:
        raise ImproperlyConfigured(f"環境変数 {name} が設定されていません。")

    return value


def comma_separated_env(name):
    """カンマ区切りの設定値をリストへ変換。"""

    value = os.environ.get(name, "")

    return [item.strip() for item in value.split(",") if item.strip()]


# ==========================================
# 基本設定
# ==========================================

DEBUG = False


# ==========================================
# シークレットキー
# ==========================================

SECRET_KEY = required_env("DJANGO_SECRET_KEY")

if len(SECRET_KEY) < 50 or SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured("安全なDJANGO_SECRET_KEYを設定してください。")


# ==========================================
# 許可ホスト
# ==========================================

ALLOWED_HOSTS = comma_separated_env("DJANGO_ALLOWED_HOSTS")

if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTSが未設定です。")

if "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("本番環境ではワイルドカードを許可しません。")


# ==========================================
# CSRF
# ==========================================

CSRF_TRUSTED_ORIGINS = comma_separated_env("DJANGO_CSRF_TRUSTED_ORIGINS")


# ==========================================
# データベース
# ==========================================

# 本番も SQLite を継続使用する（要件定義書 v1.5.7 11章）。
# DB は単一ホストの永続ローカル領域に置き、公開先やネットワーク共有に置かない。
# トランザクション方式とロック待ちは開発用 settings.py と同じ値を使う。


def sqlite_database_path():
    """本番 SQLite の配置先を検証して返す。"""

    raw = os.environ.get("DJANGO_SQLITE_PATH", "").strip() or str(BASE_DIR / "db.sqlite3")
    path = Path(raw)

    if not path.is_absolute():
        raise ImproperlyConfigured("DJANGO_SQLITE_PATH は絶対パスで指定してください。")

    if raw.startswith(("\\\\", "//")):
        raise ImproperlyConfigured("SQLite をネットワーク共有に置かないでください。")

    resolved = path.resolve()
    public_roots = [(BASE_DIR / "staticfiles").resolve(), (BASE_DIR / "static").resolve()]
    if any(resolved == root or root in resolved.parents for root in public_roots):
        raise ImproperlyConfigured("SQLite を公開ディレクトリに置かないでください。")

    if not resolved.parent.is_dir():
        raise ImproperlyConfigured("DJANGO_SQLITE_PATH の親ディレクトリが存在しません。")

    return resolved


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": sqlite_database_path(),
        "OPTIONS": dict(DATABASES["default"].get("OPTIONS", {})),
    }
}

if DATABASES["default"]["OPTIONS"].get("transaction_mode") != "IMMEDIATE":
    raise ImproperlyConfigured("本番の SQLite は IMMEDIATE 方式で開始してください。")


# ==========================================
# HTTPS
# ==========================================

SECURE_SSL_REDIRECT = True

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True

SECURE_REFERRER_POLICY = "same-origin"


# ==========================================
# Cookie
# ==========================================

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"


# ==========================================
# クリックジャッキング対策
# ==========================================

X_FRAME_OPTIONS = "DENY"


# ==========================================
# HSTS
# ==========================================

# 本番環境は HTTPS 専用。初期値は短い期間とし、運用確認後に延長する。
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))
if SECURE_HSTS_SECONDS < 0:
    raise ImproperlyConfigured("DJANGO_HSTS_SECONDS は0以上にしてください。")

SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

MIDDLEWARE += ["config.security.ContentSecurityPolicyMiddleware"]

if os.environ.get("DJANGO_TRUST_PROXY_SSL_HEADER", "").lower() == "true":
    # 信頼済みリバースプロキシが外部入力の同名ヘッダーを破棄する場合だけ設定。
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# ==========================================
# 静的ファイル
# ==========================================

STATIC_ROOT = BASE_DIR / "staticfiles"


# ==========================================
# ロギング
# ==========================================

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "management": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
