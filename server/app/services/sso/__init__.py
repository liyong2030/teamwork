"""统一身份认证（SSO）适配器包。

对外只需用 ``registry.get_provider()`` 拿到适配器，再调 ``verify(username, password)``。
"""

from .base import (
    IdentityResult,
    SSOError,
    SSOMisconfiguredError,
    SSOProvider,
    SSOUnavailableError,
)
from .registry import build_provider, clear_cache, get_provider, provider_choices

__all__ = [
    "IdentityResult",
    "SSOError",
    "SSOMisconfiguredError",
    "SSOProvider",
    "SSOUnavailableError",
    "build_provider",
    "clear_cache",
    "get_provider",
    "provider_choices",
]
