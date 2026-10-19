"""统一身份认证适配器的公共契约。

模式：**后端代理校验** —— 登录页照旧提交账号 + 口令，由后端拿这对凭据去 IdP 校验，
通过即签发本系统 JWT。因此这里只关心"凭据对不对 + 这个人是谁"，
**不涉及组织架构同步**，也不处理浏览器跳转。

约定：
- ``verify()`` 返回 ``None`` 表示"用户名或口令错误"（正常业务结果，不打错误日志）；
- IdP 不可达、配置缺失、协议错误等**系统级故障**抛异常，由上层转译为 503 / 500，
  绝不能当成"登录失败"——否则 IdP 一挂，所有人都只看到"用户名或密码错误"。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.models.enums import AuthSource


class SSOError(Exception):
    """SSO 基础异常。"""


class SSOMisconfiguredError(SSOError):
    """配置项缺失或不完整，属于部署错误。"""


class SSOUnavailableError(SSOError):
    """IdP 不可达 / 超时 / 返回了无法解析的内容。"""


@dataclass(frozen=True)
class IdentityResult:
    """IdP 校验通过后返回的身份信息。"""

    external_id: str
    username: str
    full_name: str | None = None
    email: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.external_id:
            raise ValueError("external_id 不能为空：它是账号与 IdP 绑定的唯一依据")


class SSOProvider(ABC):
    """统一身份认证提供者基类。"""

    source: AuthSource
    provider_id: str = ""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.timeout = int(getattr(settings, "auth_sso_timeout", 8) or 8)

    @abstractmethod
    def verify(self, username: str, password: str) -> IdentityResult | None:
        """校验凭据，成功返回身份信息，凭据错误返回 ``None``。"""

    def describe(self) -> dict[str, Any]:
        """对外暴露的非敏感配置概览（供管理员排查，绝不返回密钥）。"""
        return {"provider": self.provider_id, "source": self.source.value}

    def health_check(self) -> tuple[bool, str]:
        """连通性自检。默认只校验配置完整性，子类可覆盖为真实探活。"""
        return True, "配置完整"


def _missing(required: dict[str, Any]) -> list[str]:
    """挑出缺失的配置项名称。"""
    return [name for name, value in required.items() if not value]
