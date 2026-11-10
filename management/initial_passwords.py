"""初期パスワードの安全な発行ヘルパー。"""

import secrets
from datetime import timedelta

from django.utils import timezone

UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
LOWER = "abcdefghjkmnpqrstuvwxyz"
DIGITS = "23456789"
PASSWORD_ALPHABET = UPPER + LOWER + DIGITS

INITIAL_PASSWORD_LENGTH = 20
INITIAL_PASSWORD_LIFETIME = timedelta(hours=72)


def generate_initial_password():
    """大文字・小文字・数字を各1文字以上含む、20文字の安全な乱数。"""
    chars = [
        secrets.choice(UPPER),
        secrets.choice(LOWER),
        secrets.choice(DIGITS),
    ]
    chars += [
        secrets.choice(PASSWORD_ALPHABET) for _ in range(INITIAL_PASSWORD_LENGTH - 3)
    ]
    # secretsの乱数でFisher-Yatesシャッフル。
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def set_initial_password(employee, *, issued_at=None):
    """社員オブジェクトへ発行状態を設定（保存は呼び出し側）。

    戻り値の平文は発行直後の応答以外へ保存しない。
    """
    issued_at = issued_at if issued_at is not None else timezone.now()
    password = generate_initial_password()
    employee.set_password(password)
    employee.must_change_password = True
    employee.initial_password_issued_at = issued_at
    employee.initial_password_expires_at = issued_at + INITIAL_PASSWORD_LIFETIME
    return password
