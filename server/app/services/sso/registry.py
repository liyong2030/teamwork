"""SSO 提供者注册表：按配置构造并缓存适配器实例。

缓存 key 包含关键配置，配置一改就自动重建；测试里可用 ``clear_cache()`` 复位。
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import AuthSource

from .base import SSOProvider, SSOError
from .cas import CASProvider
from .ldap import LDAPProvider
from .oidc import OIDCProvider

logger = get_logger(__name__)

_CACHE: dict[tuple[str, str], SSOProvider] = {}

_PROVIDERS: dict[str, type[SSOProvider]] = {
    "cas": CASProvider,
    "oidc": OIDCProvider,
    "ldap": LDAPProvider,
}

# SAML 只能走浏览器跳转，与本项目的"后端代理校验"模式不兼容，一期不提供实现
_UNSUPPORTED = {"saml": "SAML 需浏览器跳转（SP-initiated），当前版本尚未实现"}


def provider_choices() -> list[dict[str, str]]:
    """可选协议清单（含未实现的，便于前端/文档说明边界）。"""
    return [
        {"id": "cas", "label": "CAS", "source": AuthSource.CAS.value, "supported": True},
        {"id": "oidc", "label": "OIDC / OAuth2", "source": AuthSource.OIDC.value, "supported": True},
        {"id": "ldap", "label": "LDAP / AD", "source": AuthSource.LDAP.value, "supported": True},
        {
            "id": "saml",
            "label": "SAML 2.0",
            "source": AuthSource.SAML.value,
            "supported": False,
            "reason": _UNSUPPORTED["saml"],
        },
    ]


def build_provider(provider_id: str, cfg: Any | None = None) -> SSOProvider:
    """构造指定协议的适配器。"""
    cfg = cfg or settings
    key = provider_id.lower()
    if key in _UNSUPPORTED:
        raise SSOError(_UNSUPPORTED[key])
    provider_cls = _PROVIDERS.get(key)
    if provider_cls is None:
        raise SSOError(f"不支持的统一身份认证协议：{provider_id}")
    return provider_cls(cfg)


def get_provider(provider_id: str | None = None, cfg: Any | None = None) -> SSOProvider | None:
    """取（缓存的）适配器实例；未启用 SSO 时返回 None。"""
    cfg = cfg or settings
    if not cfg.auth_sso_enabled:
        return None
    key = (provider_id or cfg.auth_sso_provider).lower()
    cache_key = (key, _config_fingerprint(cfg))
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached
    provider = build_provider(key, cfg)
    _CACHE[cache_key] = provider
    return provider


def _config_fingerprint(cfg: Any) -> str:
    """关键配置的指纹：配置变化时缓存自动失效。"""
    fields = (
        "auth_sso_timeout",
        "cas_server_url",
        "cas_rest_path",
        "cas_service_url",
        "cas_require_service_ticket",
        "oidc_issuer",
        "oidc_token_endpoint",
        "oidc_userinfo_endpoint",
        "oidc_client_id",
        "oidc_client_secret",
        "oidc_scope",
        "ldap_server_uri",
        "ldap_bind_dn_template",
        "ldap_base_dn",
        "ldap_user_filter",
        "ldap_search_bind_dn",
    )
    return "|".join(f"{name}={getattr(cfg, name, '')!s}" for name in fields)


def clear_cache() -> None:
    """清空缓存（测试或配置热更新后调用）。"""
    _CACHE.clear()
