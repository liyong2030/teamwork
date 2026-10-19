"""统一身份认证登录服务：凭据校验 → 账号解析 → 签发令牌。

账号解析三条路径（按优先级）：
1. **已绑定**：按 ``(auth_source, external_id)`` 命中既有账号；
2. **同名绑定**：IdP 用户名与某个本地账号同名 → 把该账号转为 SSO 账号
   （**超级管理员除外**，那是 IdP 故障时的应急通道，不能被绑定走）；
3. **自动建号**：以上都不中且开启 ``auth_sso_auto_create`` → 建号并落入「未分组」部门。

全程**不同步组织架构**：部门归属、组长身份、角色一律保持本地管理，
IdP 只负责回答"这个人是不是他本人"。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    AppError,
    AuthError,
    SSORequiredError,
    SSOUnavailable,
)
from app.core.logging import get_logger
from app.models.enums import AuthSource
from app.models.organization import Department, DepartmentMember, User
from app.services import audit
from app.services.sso import (
    IdentityResult,
    SSOError,
    SSOProvider,
    SSOMisconfiguredError,
    SSOUnavailableError,
    get_provider,
)
from app.utils.week import utcnow

logger = get_logger(__name__)

DEFAULT_DEPARTMENT_NAME = "未分组"


# ----------------------------------------------------------------------
# 登录主入口
# ----------------------------------------------------------------------
def authenticate_via_sso(
    db: Session,
    *,
    username: str,
    password: str,
    request: Request | None = None,
) -> User:
    """用统一身份认证校验账号密码，成功返回本地 User（不存在则按策略创建/绑定）。"""
    provider = get_provider()
    if provider is None:
        raise AuthError("未启用统一身份认证")

    identity = _verify_with_provider(provider, username, password)
    if identity is None:
        # 与本地登录保持一致的措辞，不区分"账号不存在"，防枚举
        logger.info("统一身份认证失败 username=%s provider=%s", username, provider.provider_id)
        raise AuthError("用户名或口令错误")

    user = resolve_user(db, provider=provider, identity=identity)
    user.last_login_at = utcnow()
    db.flush()

    audit.record(
        db,
        action="auth.login.sso",
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
        detail={
            "provider": provider.provider_id,
            "external_id": identity.external_id,
            "username": identity.username,
        },
        request=request,
    )
    return user


def _verify_with_provider(
    provider: SSOProvider, username: str, password: str
) -> IdentityResult | None:
    """把适配器的异常翻译为对外的 HTTP 语义。"""
    try:
        return provider.verify(username, password)
    except SSOMisconfiguredError as exc:
        logger.error("统一身份认证配置有误：%s", exc)
        raise SSOUnavailable(f"统一身份认证配置有误：{exc}") from exc
    except SSOUnavailableError as exc:
        logger.error("统一身份认证服务不可用：%s", exc)
        raise SSOUnavailable(f"统一身份认证服务暂时不可用：{exc}") from exc
    except SSOError as exc:
        logger.error("统一身份认证失败：%s", exc)
        raise SSOUnavailable(str(exc)) from exc


# ----------------------------------------------------------------------
# 账号解析
# ----------------------------------------------------------------------
def resolve_user(
    db: Session, *, provider: SSOProvider, identity: IdentityResult
) -> User:
    """把 IdP 身份映射到本地账号。"""
    source = provider.source.value

    bound = _find_bound(db, source, identity.external_id)
    if bound is not None:
        return _touch_profile(db, bound, identity)

    same_name = db.execute(
        select(User).where(User.username == identity.username)
    ).scalar_one_or_none()

    if same_name is not None:
        if not settings.auth_sso_bind_existing:
            raise AppError(
                f"本地已存在同名账号「{identity.username}」但未绑定统一身份，请联系管理员处理"
            )
        if same_name.is_superuser:
            # 应急管理员必须始终能用本地口令登录，绝不自动转为 SSO 账号
            raise AppError(
                f"登录名「{identity.username}」是系统管理员账号，"
                f"出于应急通道考虑不会自动绑定统一身份，请联系管理员手动绑定"
            )
        if same_name.is_sso:
            raise AppError(
                f"登录名「{identity.username}」已绑定其他认证来源"
                f"（{same_name.auth_source_label}），请联系管理员处理"
            )
        return _bind_local_user(db, same_name, provider, identity)

    if not settings.auth_sso_auto_create:
        raise AppError(
            f"统一身份认证通过，但本地未登记账号「{identity.username}」，请联系管理员创建"
        )
    return _create_sso_user(db, provider=provider, identity=identity)


def _find_bound(db: Session, source: str, external_id: str) -> User | None:
    return db.execute(
        select(User).where(User.auth_source == source, User.external_id == external_id)
    ).scalar_one_or_none()


def _touch_profile(db: Session, user: User, identity: IdentityResult) -> User:
    """只补全空字段，不覆盖本地已维护的资料。"""
    if not user.is_active:
        raise AuthError("账号已停用，请联系管理员")
    if not user.full_name and identity.full_name:
        user.full_name = identity.full_name
    if not user.email and identity.email:
        user.email = identity.email
    db.flush()
    return user


def _bind_local_user(
    db: Session, user: User, provider: SSOProvider, identity: IdentityResult
) -> User:
    """把既有本地账号转为 SSO 账号：清掉本地口令，禁用本地登录入口。"""
    user.auth_source = provider.source.value
    user.external_id = identity.external_id
    user.hashed_password = None
    user.must_change_password = False
    if identity.full_name:
        user.full_name = identity.full_name
    if identity.email and not user.email:
        user.email = identity.email
    db.flush()
    logger.info(
        "本地账号绑定统一身份 user_id=%s username=%s source=%s",
        user.id,
        user.username,
        provider.source.value,
    )
    return user


def _create_sso_user(
    db: Session, *, provider: SSOProvider, identity: IdentityResult
) -> User:
    """JIT 建号：普通成员、无本地口令、落入「未分组」部门。"""
    if db.execute(select(User.id).where(User.username == identity.username)).first():
        raise AppError(f"登录名「{identity.username}」已被占用，无法自动创建账号")

    user = User(
        username=identity.username,
        full_name=identity.full_name or identity.username,
        email=identity.email,
        hashed_password=None,
        auth_source=provider.source.value,
        external_id=identity.external_id,
        is_active=True,
        is_superuser=False,
        must_change_password=False,
    )
    db.add(user)
    db.flush()

    dept = db.execute(
        select(Department).where(Department.name == DEFAULT_DEPARTMENT_NAME)
    ).scalar_one_or_none()
    if dept is not None:
        db.add(
            DepartmentMember(
                user_id=user.id,
                department_id=dept.id,
                is_leader=False,
                joined_at=dt.date.today(),
            )
        )
        db.flush()

    logger.info(
        "自动创建统一身份账号 user_id=%s username=%s source=%s",
        user.id,
        user.username,
        provider.source.value,
    )
    return user


# ----------------------------------------------------------------------
# 绑定管理
# ----------------------------------------------------------------------
def unbind_sso(db: Session, *, user: User, actor: User, new_password: str | None = None) -> str:
    """管理员解绑统一身份，恢复本地口令登录，返回新口令（只返回一次）。

    解绑后该账号不再走 IdP，需要重新设置本地口令（未指定则随机生成并强制改密）。
    """
    if not user.is_sso:
        raise AppError("该账号本就使用本地口令登录，无需解绑")
    if user.id == actor.id and not actor.is_superuser:
        raise AppError("不能解绑自己的统一身份（会把自己锁在系统外）")

    from app.core.security import (
        generate_temp_password,
        hash_password,
        validate_password_strength,
    )
    from app.core.exceptions import WeakPasswordError

    password = new_password or generate_temp_password()
    if new_password:
        ok, msg = validate_password_strength(password)
        if not ok:
            raise WeakPasswordError(msg)

    user.auth_source = AuthSource.LOCAL.value
    user.external_id = None
    user.hashed_password = hash_password(password)
    user.must_change_password = True
    user.password_changed_at = utcnow()
    db.flush()
    logger.info("管理员解绑统一身份 user_id=%s actor=%s", user.id, actor.id)
    return password


def bind_external(
    db: Session, *, user: User, source: str, external_id: str, actor: User
) -> User:
    """管理员手动为既有账号绑定 IdP 标识（SUPERUSER 也允许，用于应急通道纳管）。"""
    if source not in {item.value for item in AuthSource}:
        raise AppError(f"不支持的认证来源：{source}")
    if source == AuthSource.LOCAL.value:
        raise AppError("绑定来源不能是 local")
    if not external_id:
        raise AppError("external_id 不能为空")

    conflict = _find_bound(db, source, external_id)
    if conflict is not None and conflict.id != user.id:
        raise AppError(
            f"该 IdP 标识已绑定给账号「{conflict.username}」，请先解绑"
        )

    user.auth_source = source
    user.external_id = external_id
    user.hashed_password = None
    user.must_change_password = False
    db.flush()
    logger.info("管理员绑定统一身份 user_id=%s source=%s actor=%s", user.id, source, actor.id)
    return user


def public_config() -> dict[str, Any]:
    """登录页需要的 SSO 公开信息（不含任何密钥）。"""
    provider = get_provider()
    from app.services.sso import provider_choices

    enabled = provider is not None
    info: dict[str, Any] = {
        "enabled": enabled,
        "default": bool(settings.auth_sso_default) and enabled,
        "label": settings.sso_provider_label,
        "provider": provider.provider_id if provider else None,
        "auth_source": provider.source.value if provider else None,
        "choices": provider_choices(),
    }
    if provider is not None:
        info["detail"] = provider.describe()
    return info


def status_for_admin() -> dict[str, Any]:
    """管理员视角的连通性自检（不发起真实认证，只做配置与可达性检查）。"""
    provider = get_provider()
    label = settings.sso_provider_label
    if provider is None:
        return {"enabled": False, "label": label, "message": "未启用统一身份认证"}
    try:
        ok, message = provider.health_check()
    except SSOError as exc:
        ok, message = False, str(exc)
    except Exception as exc:  # noqa: BLE001 - 自检接口不该 500，任何异常都转成结论
        logger.warning("统一身份认证自检异常：%s", exc)
        ok, message = False, f"自检失败：{exc}"
    return {
        "enabled": True,
        "label": label,
        "healthy": ok,
        "message": message,
        "config": provider.describe(),
        "auto_create": settings.auth_sso_auto_create,
        "bind_existing": settings.auth_sso_bind_existing,
        "default": settings.auth_sso_default,
    }
