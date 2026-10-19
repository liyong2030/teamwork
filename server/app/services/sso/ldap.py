"""LDAP / AD 适配器：simple bind 认证。

两种模式，按配置自动选择：
1. **直接 bind**（推荐，最省事）：用 ``ldap_bind_dn_template`` 把登录名拼成 DN
   （如 ``uid={username},ou=people,dc=example,dc=com`` 或 AD 的 ``{username}@corp.com``），
   bind 成功即认证通过。
2. **先查后 bind**：目录 DN 不规则时，用 ``ldap_search_bind_dn`` 先查到条目 DN，
   再用该 DN + 用户口令 bind。

属性取值：``ldap_user_filter`` 支持 ``{username}`` 占位；姓名/邮箱字段可配。
``external_id`` 取条目的 DN —— 它在目录内唯一且稳定，
比 sAMAccountName 更适合做绑定键（人员改名不会导致绑定失效）。
"""

from __future__ import annotations

from typing import Any

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


class LDAPProvider(SSOProvider):
    source = AuthSource.LDAP
    provider_id = "ldap"

    def __init__(self, settings: Any) -> None:
        super().__init__(settings)
        self.server_uri = settings.ldap_server_uri or ""
        self.bind_dn_template = settings.ldap_bind_dn_template or ""
        self.base_dn = settings.ldap_base_dn or ""
        self.user_filter = settings.ldap_user_filter or "(uid={username})"
        self.attr_username = settings.ldap_attr_username or "uid"
        self.attr_full_name = settings.ldap_attr_full_name or "cn"
        self.attr_email = settings.ldap_attr_email or "mail"
        self.use_ssl = bool(settings.ldap_use_ssl)
        self.search_bind_dn = settings.ldap_search_bind_dn or ""
        self.search_bind_password = settings.ldap_search_bind_password or ""

    def _validate_config(self) -> None:
        gaps = _missing({"ldap_server_uri": self.server_uri})
        if not self.bind_dn_template and not self.base_dn:
            gaps.append("ldap_bind_dn_template / ldap_base_dn")
        if gaps:
            raise SSOMisconfiguredError(f"LDAP 配置缺失：{', '.join(gaps)}")

    def _server(self):  # noqa: ANN202
        try:
            from ldap3 import Server
        except ImportError as exc:  # pragma: no cover - 依赖缺失属部署问题
            raise SSOUnavailableError("未安装 ldap3，无法使用 LDAP 认证") from exc
        return Server(self.server_uri, use_ssl=self.use_ssl, connect_timeout=self.timeout)

    def verify(self, username: str, password: str) -> IdentityResult | None:
        self._validate_config()
        try:
            from ldap3 import Connection, SAFE_SYNC
        except ImportError as exc:  # pragma: no cover
            raise SSOUnavailableError("未安装 ldap3，无法使用 LDAP 认证") from exc

        if not password:
            # 空口令往往能匿名 bind 成功，必须显式拒绝
            return None

        if self.bind_dn_template:
            user_dn = self.bind_dn_template.format(username=username)
            conn = Connection(
                self._server(), user=user_dn, password=password,
                client_strategy=SAFE_SYNC, receive_timeout=self.timeout,
            )
            try:
                if not _safe_bind(conn):
                    logger.info("LDAP bind 失败 username=%s", username)
                    return None
                return self._identity_from_bound_conn(conn, username, user_dn)
            finally:
                _safe_unbind(conn)

        # 先查后 bind
        entry_dn = self._search_user_dn(username)
        if entry_dn is None:
            return None
        conn = Connection(
            self._server(), user=entry_dn, password=password,
            client_strategy=SAFE_SYNC, receive_timeout=self.timeout,
        )
        try:
            if not _safe_bind(conn):
                logger.info("LDAP bind 失败 dn=%s", entry_dn)
                return None
            return self._identity_from_bound_conn(conn, username, entry_dn)
        finally:
            _safe_unbind(conn)

    def _search_user_dn(self, username: str) -> str | None:
        from ldap3 import Connection, SAFE_SYNC, SUBTREE

        search_filter = self.user_filter.format(username=username)
        conn = Connection(
            self._server(),
            user=self.search_bind_dn or None,
            password=self.search_bind_password or None,
            client_strategy=SAFE_SYNC,
            receive_timeout=self.timeout,
        )
        try:
            if not _safe_bind(conn):
                raise SSOUnavailableError("LDAP 搜索账号 bind 失败，请检查 ldap_search_bind_dn")
            conn.search(
                self.base_dn,
                search_filter,
                search_scope=SUBTREE,
                attributes=[self.attr_username, self.attr_full_name, self.attr_email],
            )
            entries = conn.entries or []
            if not entries:
                logger.info("LDAP 未找到用户 username=%s", username)
                return None
            if len(entries) > 1:
                logger.warning(
                    "LDAP 查询命中 %s 个条目，取第一个：username=%s", len(entries), username
                )
            return str(entries[0].entry_dn)
        finally:
            _safe_unbind(conn)

    def _identity_from_bound_conn(self, conn, username: str, dn: str) -> IdentityResult:  # noqa: ANN001
        """bind 已成功，补一次自查询拿姓名/邮箱（失败不影响认证结果）。"""
        full_name: str | None = None
        email: str | None = None
        try:
            from ldap3 import SUBTREE

            conn.search(
                dn,
                "(objectClass=*)",
                search_scope=SUBTREE,
                attributes=[self.attr_full_name, self.attr_email, self.attr_username],
            )
            if conn.entries:
                attrs = conn.entries[0]
                full_name = _first_attr(attrs, self.attr_full_name)
                email = _first_attr(attrs, self.attr_email)
        except Exception as exc:  # noqa: BLE001 - 属性补全失败不应阻断登录
            logger.warning("LDAP 属性读取失败（忽略）：%s", exc)

        return IdentityResult(
            external_id=dn,
            username=username,
            full_name=full_name or username,
            email=email,
            raw={"dn": dn},
        )

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "server_uri": self.server_uri,
            "base_dn": self.base_dn or None,
            "user_filter": self.user_filter,
            "bind_dn_template": self.bind_dn_template or None,
            "use_ssl": self.use_ssl,
            # 搜索账号口令不回传
            "search_bind_dn": self.search_bind_dn or None,
        }

    def health_check(self) -> tuple[bool, str]:
        try:
            self._validate_config()
        except SSOMisconfiguredError as exc:
            return False, str(exc)
        try:
            from ldap3 import Connection, SAFE_SYNC
        except ImportError:
            return False, "未安装 ldap3"
        conn = Connection(self._server(), client_strategy=SAFE_SYNC, receive_timeout=self.timeout)
        try:
            ok = _safe_open(conn)
            return (True, f"已连通 {self.server_uri}") if ok else (False, "无法建立连接")
        finally:
            _safe_unbind(conn)


def _safe_bind(conn) -> bool:  # noqa: ANN001
    """bind 并把 ldap3 的连接异常统一转成 SSO 语义。"""
    try:
        return bool(conn.bind())
    except Exception as exc:  # noqa: BLE001 - ldap3 异常类型庞杂
        raise SSOUnavailableError(f"LDAP 连接失败：{exc}") from exc


def _safe_open(conn) -> bool:  # noqa: ANN001
    try:
        return bool(conn.open())
    except Exception:  # noqa: BLE001
        return False


def _safe_unbind(conn) -> None:  # noqa: ANN001
    try:
        conn.unbind()
    except Exception:  # noqa: BLE001,S110
        pass


def _first_attr(entry, attr: str) -> str | None:  # noqa: ANN001
    try:
        value = getattr(entry, attr, None)
    except Exception:  # noqa: BLE001
        return None
    if value is None:
        return None
    raw = getattr(value, "value", value)
    if isinstance(raw, (list, tuple)):
        return str(raw[0]) if raw else None
    return str(raw) if raw is not None else None
