"""OIDC 适配器：Resource Owner Password Credentials Grant（密码模式）。

流程：
1. ``POST {token_endpoint}``  grant_type=password & username & password & client_id/secret
2. 用 access_token 调 ``userinfo`` 端点取 ``sub`` / 姓名 / 邮箱；
   未配置 userinfo 时退化为解析 ``id_token``（不验签，仅取声明）。

端点可以从 ``oidc_issuer`` 的 ``.well-known/openid-configuration`` 自动发现。

> 安全提示：password grant 要求 IdP 侧为该 client 显式开启，且本系统会**短暂接触明文口令**
> （仅用于当次校验，不做存储、不写日志）。若 IdP 不允许该模式，请改用授权码模式（二期）。
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import get_logger
from app.models.enums import AuthSource

from .base import (
    IdentityResult,
    SSOProvider,
    SSOUnavailableError,
    SSOMisconfiguredError,
    _missing,
)

logger = get_logger(__name__)

# 进程内缓存：避免每次登录都去拉一次 discovery 文档
_DISCOVERY_CACHE: dict[str, dict[str, Any]] = {}


class OIDCProvider(SSOProvider):
    source = AuthSource.OIDC
    provider_id = "oidc"

    def __init__(self, settings: Any) -> None:
        super().__init__(settings)
        self.issuer = (settings.oidc_issuer or "").rstrip("/")
        self.token_endpoint = settings.oidc_token_endpoint or ""
        self.userinfo_endpoint = settings.oidc_userinfo_endpoint or ""
        self.client_id = settings.oidc_client_id
        self.client_secret = settings.oidc_client_secret
        self.scope = settings.oidc_scope or "openid profile email"
        self.verify_ssl = bool(settings.oidc_verify_ssl)

    def _validate_config(self) -> None:
        gaps = _missing({"oidc_client_id": self.client_id})
        if not (self.token_endpoint or self.issuer):
            gaps.append("oidc_token_endpoint / oidc_issuer")
        if gaps:
            raise SSOMisconfiguredError(f"OIDC 配置缺失：{', '.join(gaps)}")

    def _discover(self) -> dict[str, Any]:
        """拉取并缓存 discovery 文档；失败只告警，允许用显式配置的端点继续。"""
        if not self.issuer:
            return {}
        cached = _DISCOVERY_CACHE.get(self.issuer)
        if cached is not None:
            return cached
        url = f"{self.issuer}/.well-known/openid-configuration"
        try:
            resp = httpx.get(url, timeout=self.timeout, verify=self.verify_ssl)
            if resp.status_code == 200:
                _DISCOVERY_CACHE[self.issuer] = resp.json()
                return _DISCOVERY_CACHE[self.issuer]
            logger.warning("OIDC discovery 返回 HTTP %s", resp.status_code)
        except httpx.HTTPError as exc:
            logger.warning("OIDC discovery 不可用：%s", exc)
        return {}

    def _endpoints(self) -> tuple[str, str]:
        doc = self._discover()
        token_url = self.token_endpoint or doc.get("token_endpoint", "")
        userinfo_url = self.userinfo_endpoint or doc.get("userinfo_endpoint", "")
        return token_url, userinfo_url

    def verify(self, username: str, password: str) -> IdentityResult | None:
        self._validate_config()
        token_url, userinfo_url = self._endpoints()
        if not token_url:
            raise SSOMisconfiguredError("未能确定 OIDC token_endpoint（请显式配置或提供 issuer）")

        token = self._request_token(token_url, username, password)
        if token is None:
            return None

        claims: dict[str, Any] = {}
        access_token = str(token.get("access_token") or "")
        if access_token and userinfo_url:
            claims = self._fetch_userinfo(userinfo_url, access_token)
        if not claims and token.get("id_token"):
            claims = _decode_id_token_claims(str(token["id_token"]))

        external_id = str(claims.get("sub") or username)
        return IdentityResult(
            external_id=external_id,
            username=str(
                claims.get("preferred_username")
                or claims.get("username")
                or username
            ),
            full_name=claims.get("name") or claims.get("nickname"),
            email=claims.get("email"),
            raw={"claims": claims},
        )

    def _request_token(self, url: str, username: str, password: str) -> dict[str, Any] | None:
        data = {
            "grant_type": "password",
            "username": username,
            "password": password,
            "scope": self.scope,
        }
        if self.client_id:
            data["client_id"] = self.client_id
        if self.client_secret:
            data["client_secret"] = self.client_secret

        try:
            resp = httpx.post(url, data=data, timeout=self.timeout, verify=self.verify_ssl)
        except httpx.HTTPError as exc:
            raise SSOUnavailableError(f"OIDC 令牌端点不可达：{exc}") from exc

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError as exc:
                raise SSOUnavailableError(f"OIDC 令牌响应不是合法 JSON：{exc}") from exc
        if resp.status_code in (400, 401):
            # invalid_grant / invalid_client 都归为"凭据不被接受"
            logger.info("OIDC 认证失败 username=%s status=%s", username, resp.status_code)
            return None
        raise SSOUnavailableError(f"OIDC 令牌端点异常：HTTP {resp.status_code}")

    def _fetch_userinfo(self, url: str, access_token: str) -> dict[str, Any]:
        try:
            resp = httpx.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
        except httpx.HTTPError as exc:
            raise SSOUnavailableError(f"OIDC userinfo 不可达：{exc}") from exc
        if resp.status_code != 200:
            raise SSOUnavailableError(f"OIDC userinfo 返回 HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise SSOUnavailableError(f"OIDC userinfo 响应不是合法 JSON：{exc}") from exc

    def describe(self) -> dict[str, Any]:
        token_url, userinfo_url = self._endpoints()
        return {
            **super().describe(),
            "issuer": self.issuer or None,
            "token_endpoint": token_url or None,
            "userinfo_endpoint": userinfo_url or None,
            "scope": self.scope,
            "client_id": self.client_id or None,
            # 密钥不回传
            "client_secret": "***" if self.client_secret else None,
        }

    def health_check(self) -> tuple[bool, str]:
        try:
            self._validate_config()
        except SSOMisconfiguredError as exc:
            return False, str(exc)
        token_url, _ = self._endpoints()
        return (True, f"令牌端点：{token_url}") if token_url else (False, "未能确定令牌端点")


def _decode_id_token_claims(id_token: str) -> dict[str, Any]:
    """无验签解析 id_token 的声明（仅用于兜底取 sub/姓名/邮箱）。

    真正的身份断言由 IdP 的令牌端点完成（凭据错误时根本拿不到 id_token），
    这里不做签名校验，因此**不参与任何鉴权决策**，只用于补全展示信息。
    """
    import base64
    import binascii

    payload = id_token.split(".")[1] if id_token.count(".") >= 2 else ""
    if not payload:
        return {}
    payload += "=" * (-len(payload) % 4)
    try:
        import json

        return json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, binascii.Error):
        logger.warning("id_token 无法解析，回退使用登录名作为身份标识")
        return {}
