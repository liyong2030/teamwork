"""统一身份认证登录：账号解析三条路径 + 本地口令禁用 + 应急管理员保护。

测试全部使用**伪造的 provider**（不连真实 IdP），重点验证本系统的账号策略：
已绑定命中 / 同名绑定 / JIT 建号，以及"SSO 账号不能用本地口令登录"这条底线。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError, AuthError, SSORequiredError
from app.models.enums import AuthSource
from app.models.organization import Department, DepartmentMember, User
from app.services import auth_service, sso_service
from app.services.sso import (
    IdentityResult,
    SSOProvider,
    SSOUnavailableError,
    clear_cache,
)
from app.services.sso.cas import parse_service_response

from .conftest import make_department, make_user


class FakeProvider(SSOProvider):
    """可编程的假 IdP：按预设决定"通过/拒绝/故障"。"""

    source = AuthSource.CAS
    provider_id = "cas"

    def __init__(self, settings: Any, result: IdentityResult | None = None, boom: bool = False):
        super().__init__(settings)
        self.result = result
        self.boom = boom
        self.calls: list[tuple[str, str]] = []

    def verify(self, username: str, password: str) -> IdentityResult | None:
        self.calls.append((username, password))
        if self.boom:
            raise SSOUnavailableError("假 IdP 故障")
        return self.result


def _identity(username: str = "zhangsan", external_id: str | None = None) -> IdentityResult:
    return IdentityResult(
        external_id=external_id or username,
        username=username,
        full_name="张三",
        email="zhangsan@example.com",
    )


@pytest.fixture
def sso_on(monkeypatch):
    """打开 SSO 总开关，并让 registry 返回测试注入的 provider。"""
    monkeypatch.setattr(settings, "auth_sso_enabled", True)
    monkeypatch.setattr(settings, "auth_sso_provider", "cas")
    monkeypatch.setattr(settings, "auth_sso_auto_create", True)
    monkeypatch.setattr(settings, "auth_sso_bind_existing", True)
    clear_cache()
    yield
    clear_cache()


def _install(monkeypatch, provider: FakeProvider) -> None:
    monkeypatch.setattr(sso_service, "get_provider", lambda *a, **k: provider)


# ----------------------------------------------------------------------
# 账号解析
# ----------------------------------------------------------------------
def test_jit_creates_user_in_default_department(db, sso_on, monkeypatch) -> None:
    """IdP 通过且本地无账号 → 自动建号，落「未分组」，无本地口令。"""
    dept = Department(name="未分组", sort_order=0, is_active=True)
    db.add(dept)
    db.flush()
    _install(monkeypatch, FakeProvider(settings, _identity()))

    user = sso_service.authenticate_via_sso(db, username="zhangsan", password="pwd")

    assert user.username == "zhangsan"
    assert user.full_name == "张三"
    assert user.auth_source == AuthSource.CAS.value
    assert user.external_id == "zhangsan"
    assert user.hashed_password is None  # SSO 账号没有本地口令
    assert user.must_change_password is False
    assert user.is_superuser is False
    assert user.department_ids == [dept.id]


def test_existing_local_user_is_bound_and_password_cleared(db, sso_on, monkeypatch) -> None:
    """同名本地账号 → 绑定为 SSO 账号，本地口令清除，部门/角色保留。"""
    dept = make_department(db, "研发部")
    existing = make_user(db, "zhangsan", department=dept, is_leader=True)
    db.flush()
    _install(monkeypatch, FakeProvider(settings, _identity(external_id="idp-9527")))

    user = sso_service.authenticate_via_sso(db, username="zhangsan", password="pwd")

    assert user.id == existing.id  # 复用既有账号，不新建
    assert user.auth_source == AuthSource.CAS.value
    assert user.external_id == "idp-9527"
    assert user.hashed_password is None
    assert user.is_superuser is False
    # 组织架构不动：组长身份与部门归属保持本地管理
    assert user.leader_department_ids == [dept.id]


def test_bound_user_is_matched_by_external_id(db, sso_on, monkeypatch) -> None:
    """已绑定账号按 external_id 命中，即使 IdP 侧改了登录名也不会串号。"""
    user = make_user(db, "oldname")
    user.auth_source = AuthSource.CAS.value
    user.external_id = "idp-9527"
    db.flush()
    _install(
        monkeypatch,
        FakeProvider(settings, _identity(username="newname", external_id="idp-9527")),
    )

    found = sso_service.authenticate_via_sso(db, username="newname", password="pwd")
    assert found.id == user.id


def test_superuser_is_never_auto_bound(db, sso_on, monkeypatch) -> None:
    """应急管理员账号不自动绑定 —— 否则 IdP 故障时就没有任何人能本地登录。"""
    admin = make_user(db, "admin", is_superuser=True)
    db.flush()
    _install(monkeypatch, FakeProvider(settings, _identity(username="admin")))

    with pytest.raises(AppError, match="系统管理员账号"):
        sso_service.authenticate_via_sso(db, username="admin", password="pwd")
    assert admin.auth_source == AuthSource.LOCAL.value


def test_auto_create_disabled_rejects_unknown(db, sso_on, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_sso_auto_create", False)
    _install(monkeypatch, FakeProvider(settings, _identity()))

    with pytest.raises(AppError, match="未登记账号"):
        sso_service.authenticate_via_sso(db, username="zhangsan", password="pwd")


def test_bind_disabled_keeps_local_account(db, sso_on, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_sso_bind_existing", False)
    make_user(db, "zhangsan")
    db.flush()
    _install(monkeypatch, FakeProvider(settings, _identity()))

    with pytest.raises(AppError, match="未绑定统一身份"):
        sso_service.authenticate_via_sso(db, username="zhangsan", password="pwd")


def test_inactive_user_cannot_login(db, sso_on, monkeypatch) -> None:
    user = make_user(db, "zhangsan")
    user.auth_source = AuthSource.CAS.value
    user.external_id = "zhangsan"
    user.is_active = False
    db.flush()
    _install(monkeypatch, FakeProvider(settings, _identity()))

    with pytest.raises(AuthError, match="已停用"):
        sso_service.authenticate_via_sso(db, username="zhangsan", password="pwd")


# ----------------------------------------------------------------------
# 登录结果语义
# ----------------------------------------------------------------------
def test_wrong_credentials_is_auth_error(db, sso_on, monkeypatch) -> None:
    """IdP 说密码错 → 401，措辞与本地登录一致（不区分账号是否存在）。"""
    _install(monkeypatch, FakeProvider(settings, result=None))
    with pytest.raises(AuthError, match="用户名或口令错误"):
        sso_service.authenticate_via_sso(db, username="zhangsan", password="bad")


def test_idp_failure_is_not_auth_error(db, sso_on, monkeypatch) -> None:
    """IdP 挂了必须报 503，绝不能被当成"密码错误"，否则运维无从判断。"""
    from app.core.exceptions import SSOUnavailable

    _install(monkeypatch, FakeProvider(settings, boom=True))
    with pytest.raises(SSOUnavailable):
        sso_service.authenticate_via_sso(db, username="zhangsan", password="pwd")


def test_sso_disabled_rejects_login(db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_sso_enabled", False)
    clear_cache()
    with pytest.raises(AuthError, match="未启用"):
        sso_service.authenticate_via_sso(db, username="zhangsan", password="pwd")


# ----------------------------------------------------------------------
# 本地口令禁用
# ----------------------------------------------------------------------
def test_sso_user_cannot_use_local_password(db) -> None:
    """SSO 账号走本地登录 → 专用错误码，前端据此自动改走 IdP。"""
    user = make_user(db, "zhangsan", password="StrongPass1!")
    user.auth_source = AuthSource.CAS.value
    user.external_id = "zhangsan"
    user.hashed_password = None
    db.flush()

    with pytest.raises(SSORequiredError) as exc:
        auth_service.authenticate(db, "zhangsan", "StrongPass1!")
    assert exc.value.code == "sso_required"


def test_local_user_still_works(db) -> None:
    user = make_user(db, "lisi", password="StrongPass1!")
    db.flush()
    assert auth_service.authenticate(db, "lisi", "StrongPass1!").id == user.id


def test_sso_user_cannot_change_password(db) -> None:
    user = make_user(db, "zhangsan", password="StrongPass1!")
    user.auth_source = AuthSource.CAS.value
    db.flush()
    with pytest.raises(AppError, match="没有本地口令"):
        auth_service.change_password(db, user, "StrongPass1!", "AnotherPass1!")


def test_reset_password_rejected_for_sso_user(db) -> None:
    user = make_user(db, "zhangsan", password="StrongPass1!")
    user.auth_source = AuthSource.CAS.value
    db.flush()
    with pytest.raises(AppError, match="请先解绑"):
        auth_service.reset_password(db, user)


# ----------------------------------------------------------------------
# 绑定管理
# ----------------------------------------------------------------------
def test_admin_bind_and_unbind(db) -> None:
    admin = make_user(db, "admin", is_superuser=True)
    user = make_user(db, "zhangsan", password="StrongPass1!")
    db.flush()

    sso_service.bind_external(
        db, user=user, source="cas", external_id="idp-1", actor=admin
    )
    db.flush()
    assert user.is_sso and user.hashed_password is None

    temp = sso_service.unbind_sso(db, user=user, actor=admin)
    db.flush()
    assert not user.is_sso
    assert user.auth_source == AuthSource.LOCAL.value
    assert user.external_id is None
    assert user.hashed_password and temp
    assert user.must_change_password is True  # 解绑后强制改密


def test_bind_conflict_is_rejected(db) -> None:
    admin = make_user(db, "admin", is_superuser=True)
    a = make_user(db, "a")
    b = make_user(db, "b")
    db.flush()
    sso_service.bind_external(db, user=a, source="cas", external_id="same", actor=admin)
    db.flush()
    with pytest.raises(AppError, match="已绑定给账号"):
        sso_service.bind_external(db, user=b, source="cas", external_id="same", actor=admin)


def test_cannot_unbind_self(db) -> None:
    leader = make_user(db, "leader")
    leader.auth_source = AuthSource.CAS.value
    leader.external_id = "x"
    db.flush()
    with pytest.raises(AppError, match="不能解绑自己"):
        sso_service.unbind_sso(db, user=leader, actor=leader)


# ----------------------------------------------------------------------
# 管理员自检（系统设置页「统一身份认证」卡片的数据源）
# ----------------------------------------------------------------------
def test_admin_status_when_disabled(monkeypatch) -> None:
    """未启用时也要返回登录入口名称，页面才能显示"关着的那个 SSO 叫什么"。"""
    monkeypatch.setattr(settings, "auth_sso_enabled", False)
    monkeypatch.setattr(settings, "auth_sso_label", "企业统一登录")
    clear_cache()

    status = sso_service.status_for_admin()

    assert status["enabled"] is False
    assert status["label"] == "企业统一登录"
    assert "未启用" in status["message"]


def test_admin_status_reports_health_and_switches(db, sso_on, monkeypatch) -> None:
    """启用后返回连通性结论、开关状态与脱敏配置，且不含任何密钥字段。"""
    monkeypatch.setattr(settings, "auth_sso_label", "企业统一登录")
    monkeypatch.setattr(settings, "auth_sso_default", True)
    monkeypatch.setattr(settings, "auth_sso_bind_existing", False)
    _install(monkeypatch, FakeProvider(settings, _identity()))

    status = sso_service.status_for_admin()

    assert status["enabled"] is True
    assert status["healthy"] is True
    assert status["label"] == "企业统一登录"
    assert status["default"] is True
    assert status["bind_existing"] is False
    assert status["auto_create"] is True
    assert status["config"]["provider"] == "cas"
    # 自检只暴露非敏感配置，绝不能把口令/密钥带出来
    assert not {"password", "client_secret", "search_bind_password"} & set(status["config"])


# ----------------------------------------------------------------------
# CAS 响应解析
# ----------------------------------------------------------------------
def test_parse_cas_success() -> None:
    xml = """<cas:serviceResponse xmlns:cas='http://www.yale.edu/tp/cas'>
      <cas:authenticationSuccess>
        <cas:user>zhangsan</cas:user>
        <cas:attributes>
          <cas:mail>zhangsan@example.com</cas:mail>
          <cas:cn>张三</cas:cn>
        </cas:attributes>
      </cas:authenticationSuccess>
    </cas:serviceResponse>"""
    result = parse_service_response(xml, "fallback")
    assert result is not None
    assert result.username == "zhangsan"
    assert result.email == "zhangsan@example.com"
    assert result.full_name == "张三"


def test_parse_cas_failure_returns_none() -> None:
    xml = """<cas:serviceResponse xmlns:cas='http://www.yale.edu/tp/cas'>
      <cas:authenticationFailure code="INVALID_TICKET">票据无效</cas:authenticationFailure>
    </cas:serviceResponse>"""
    assert parse_service_response(xml, "fallback") is None


def test_parse_cas_broken_xml_raises() -> None:
    with pytest.raises(SSOUnavailableError):
        parse_service_response("<not-xml", "fallback")
