import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from cryptography.fernet import Fernet

from .config import settings


class AuthError(Exception):
    pass


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict:
    """Проверка подписи Telegram Mini App initData. Возвращает данные пользователя."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise AuthError("no hash")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise AuthError("bad signature")
    if time.time() - int(pairs.get("auth_date", 0)) > max_age:
        raise AuthError("initData expired")
    try:
        return json.loads(pairs["user"])
    except (KeyError, ValueError) as e:
        raise AuthError("no user") from e


def _fernet() -> Fernet:
    key = settings.secret_key
    if not key:  # dev-режим: ключ выводится из webhook_secret. В продакшне задайте SECRET_KEY.
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.webhook_secret.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode() if value else ""
