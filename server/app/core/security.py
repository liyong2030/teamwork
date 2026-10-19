"""安全模块：Argon2id 口令哈希 + JWT 令牌签发与校验 + 口令强度策略。

安全要求：
1. 口令永不明文存储，哈希参数见 Argon2 官方推荐基线；
2. 令牌全部携带过期时间，且校验令牌类型（防止 refresh 当 access 用）；
3. 所有失败路径返回统一的 None / False，由调用方决定响应，不泄漏内部细节。
"""

from __future__ import annotations

import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError

from app.core.config import settings

# Argon2id 参数：OWASP 推荐基线以上
_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64MB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

TokenType = Literal["access", "refresh"]


# ----------------------------------------------------------------------
# 口令哈希
# ----------------------------------------------------------------------
def hash_password(plain: str) -> str:
    """生成 Argon2id 哈希串（含盐与参数，可直接入库）。"""
    return _password_hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """校验口令。哈希损坏 / 不匹配一律返回 False，不抛业务异常。"""
    try:
        return _password_hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    """判断是否需要用新参数重新哈希（参数升级后自动迁移）。"""
    try:
        return _password_hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


# ----------------------------------------------------------------------
# 口令策略
# ----------------------------------------------------------------------
def validate_password_strength(plain: str) -> tuple[bool, str]:
    """口令强度校验。

    规则：长度 >= PASSWORD_MIN_LENGTH（默认 10），
          且大写 / 小写 / 数字 / 符号中至少含三类；不得包含空格。
    返回 (是否通过, 提示信息)。
    """
    min_len = settings.password_min_length
    if len(plain) < min_len:
        return False, f"口令长度至少需要 {min_len} 位"
    if " " in plain:
        return False, "口令不能包含空格"

    classes = 0
    classes += 1 if re.search(r"[A-Z]", plain) else 0
    classes += 1 if re.search(r"[a-z]", plain) else 0
    classes += 1 if re.search(r"\d", plain) else 0
    classes += 1 if re.search(r"[^A-Za-z0-9]", plain) else 0

    if classes < 3:
        return False, "口令需包含大写、小写、数字、符号中的至少三类"
    return True, "ok"


def generate_temp_password(length: int = 16) -> str:
    """生成满足强度策略的随机初始口令（用于 create-admin 与密码重置）。"""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_"
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        ok, _ = validate_password_strength(candidate)
        if ok:
            return candidate


# ----------------------------------------------------------------------
# JWT
# ----------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def create_token(
    subject: str,
    token_type: TokenType = "access",
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """签发 JWT。

    :param subject: 用户唯一标识（此处用 user.id 的字符串形式）
    :param token_type: access / refresh，用于防止令牌混用
    :param expires_delta: 自定义有效期，缺省按配置
    :param extra_claims: 附加声明（如 must_change_password）
    """
    if token_type == "access":
        delta = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    else:
        delta = expires_delta or timedelta(days=settings.refresh_token_expire_days)

    now = _now()
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + delta).timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: TokenType | None = None) -> dict[str, Any] | None:
    """解析 JWT。

    任何异常（过期、签名不符、类型不符）统一返回 None，由上层转换为 401，
    避免向调用方泄漏具体失败原因。
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        return None

    if expected_type and payload.get("type") != expected_type:
        return None
    return payload


def create_access_token(user_id: int, must_change_password: bool = False) -> str:
    """便捷函数：签发访问令牌。"""
    return create_token(
        str(user_id),
        token_type="access",
        extra_claims={"mcp": bool(must_change_password)},
    )


def create_refresh_token(user_id: int) -> str:
    """便捷函数：签发刷新令牌。"""
    return create_token(str(user_id), token_type="refresh")
