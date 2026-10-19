"""应用配置中心：全部配置走环境变量 / .env，禁止在代码中硬编码敏感信息。

加载优先级：环境变量 > .env 文件 > 默认值。
"""

from __future__ import annotations

import re
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# server/ 目录（app/core/config.py 往上三级）
BASE_DIR = Path(__file__).resolve().parents[2]

_SQLITE_PATH_RE = re.compile(r"^sqlite(?P<driver>\+[a-z0-9]+)?:///(?P<path>.*)$")


class Settings(BaseSettings):
    """全局配置对象。"""

    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用 ----------
    app_env: Literal["dev", "prod"] = "dev"
    app_name: str = "团队协作管理系统"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True

    # ---------- 数据库 ----------
    database_url: str = "sqlite:///./data/app.db"
    sql_echo: bool = False

    # ---------- 安全 ----------
    secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 小时
    refresh_token_expire_days: int = 7

    # ---------- 时区 ----------
    tz: str = "Asia/Shanghai"

    # ---------- 周报口径 ----------
    report_deadline_weekday: int = 5   # 1=周一 … 5=周五
    report_deadline_time: str = "18:00"
    report_finalize_weekday: int = 1   # 下周一
    report_finalize_time: str = "09:30"
    report_valid_min_chars: int = 20

    # ---------- 定时任务 ----------
    scheduler_enabled: bool = True
    scheduler_timezone: str = "Asia/Shanghai"

    # ---------- 邮件 ----------
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_name: str = "团队协作管理系统"
    smtp_use_ssl: bool = True
    email_enabled: bool = False

    # ---------- CORS ----------
    cors_origins: str = "http://localhost:5173,http://localhost"

    # ---------- 密码策略 ----------
    password_min_length: int = 10

    # ---------- 统一身份认证（SSO）----------
    # 模式说明：后端代理校验 —— 登录页仍提交账号密码，由后端拿这对凭据去 IdP 校验，
    # 通过即签发本系统 JWT。不同步组织架构，只做认证。
    auth_sso_enabled: bool = False
    auth_sso_provider: Literal["cas", "oidc", "ldap", "saml"] = "cas"
    auth_sso_label: str = "统一身份认证"
    # True 时所有账号默认走 SSO；False 时按账号自身的 auth_source 决定
    auth_sso_default: bool = False
    # IdP 通过但本地无同名账号时自动建号
    auth_sso_auto_create: bool = True
    # IdP 通过且本地存在同名本地账号时，自动把该账号绑定到 SSO
    auth_sso_bind_existing: bool = True
    auth_sso_timeout: int = 8

    # CAS：REST 接口换取 TGT，再用 TGT 换 ST 并校验（需要 CAS 开启 REST 支持）
    cas_server_url: str = ""
    cas_rest_path: str = "/cas/v1/tickets"
    cas_service_url: str = ""
    # False 时只要换到 TGT 即视为通过（CAS 未开放 service 校验场景）
    cas_require_service_ticket: bool = True

    # OIDC：password grant 换取令牌，再用 userinfo 拉取身份
    oidc_issuer: str = ""
    oidc_token_endpoint: str = ""
    oidc_userinfo_endpoint: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scope: str = "openid profile email"
    oidc_verify_ssl: bool = True

    # LDAP / AD
    ldap_server_uri: str = ""
    ldap_bind_dn_template: str = ""
    ldap_base_dn: str = ""
    ldap_user_filter: str = "(uid={username})"
    ldap_attr_username: str = "uid"
    ldap_attr_full_name: str = "cn"
    ldap_attr_email: str = "mail"
    ldap_use_ssl: bool = False
    # 目录不允许匿名搜索时，先用该账号 bind 再查人
    ldap_search_bind_dn: str = ""
    ldap_search_bind_password: str = ""

    @field_validator("secret_key")
    @classmethod
    def _ensure_secret_key(cls, v: str) -> str:
        """未提供密钥时自动生成（仅适用于开发环境，生产环境必须显式配置）。"""
        return v or secrets.token_urlsafe(48)

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        """把相对路径的 SQLite URL 锚定到项目根目录，并确保目录存在。

        默认值 ``sqlite:///./data/app.db`` 是相对当前工作目录解析的 —— 从 IDE、
        计划任务或任意目录启动时都会变成另一个库文件（或直接报
        ``unable to open database file``）。这里统一转成绝对路径并自动建目录。
        """
        match = _SQLITE_PATH_RE.match(v)
        if not match:
            return v

        raw_path = match.group("path")
        if not raw_path or raw_path.startswith(":memory:"):
            # 内存库：保持原样，不做任何路径处理
            return v

        path = Path(raw_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)

        driver = match.group("driver") or ""
        return f"sqlite{driver}:///{path.as_posix()}"

    @field_validator("report_deadline_weekday", "report_finalize_weekday")
    @classmethod
    def _check_weekday(cls, v: int) -> int:
        if not 1 <= v <= 7:
            raise ValueError("weekday 必须在 1(周一) 到 7(周日) 之间")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的 CORS 配置解析为列表。"""
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def sso_provider_label(self) -> str:
        """登录页展示用的统一身份认证名称。"""
        return self.auth_sso_label or "统一身份认证"


@lru_cache
def get_settings() -> Settings:
    """获取全局单例配置（进程内缓存，避免重复读取 .env）。"""
    return Settings()


settings = get_settings()
