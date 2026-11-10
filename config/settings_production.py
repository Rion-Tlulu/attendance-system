"""
勤怠管理システム：本番用Django設定。

使用方法：
    --settings=config.settings_production

注意：
- 開発用settings.pyを変更しない
- 秘密鍵とDB接続情報は環境変数から取得
- HTTPSでの運用を前提とする
- 本番用PostgreSQL接続が必要
"""

import os

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

# 本番はPostgreSQLを想定
# SQLite設定をそのまま引き継がない

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": required_env("POSTGRES_DB"),
        "USER": required_env("POSTGRES_USER"),
        "PASSWORD": required_env("POSTGRES_PASSWORD"),
        "HOST": required_env("POSTGRES_HOST"),
        "PORT": os.environ.get(
            "POSTGRES_PORT",
            "5432",
        ),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "sslmode": os.environ.get(
                "POSTGRES_SSLMODE",
                "verify-full",
            ),
        },
    }
}


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
