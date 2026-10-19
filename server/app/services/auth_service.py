"""认证与用户服务：登录、令牌、改密、重置、用户创建。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    AppError,
    AuthError,
    SSORequiredError,
    ValidationError,
    WeakPasswordError,
)
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_temp_password,
    hash_password,
    needs_rehash,
    validate_password_strength,
    verify_password,
)
from app.models.enums import LeaveStatus
from app.models.organization import Department, DepartmentMember, LeaveRequest, User
from app.utils.week import (
    ensure_date,
    localnow,
    utcnow,
    week_end_of,
    week_start_of,
)

logger = get_logger(__name__)


# ----------------------------------------------------------------------
# 令牌与会话
# ----------------------------------------------------------------------
def load_user_from_payload(db: Session, payload: dict[str, Any]) -> User | None:
    """根据 JWT payload 载入用户；用户不存在或已停用时返回 None。

    若哈希参数已升级，此处顺便完成一次静默重哈希。
    """
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def issue_tokens(user: User) -> dict[str, Any]:
    """生成令牌响应字典。"""
    return {
        "access_token": create_access_token(user.id, user.must_change_password),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "must_change_password": user.must_change_password,
    }


def authenticate(db: Session, username: str, password: str) -> User:
    """校验用户名口令。失败一律抛 ``AuthError``（不区分用户是否存在，防枚举）。"""
    stmt = select(User).where(User.username == username)
    user = db.execute(stmt).scalar_one_or_none()

    # 即使用户不存在也执行一次哈希校验，避免时序侧信道
    dummy_hash = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHRzb21lc2FsdA$RdescudvJCsgt3ub+b+dWRWJTmaaJObG"
    stored = user.hashed_password if (user and user.hashed_password) else dummy_hash
    ok = verify_password(password, stored)

    # 统一身份认证账号不允许走本地口令：否则等于给 IdP 之外的弱口令留了后门。
    # 判定放在口令校验**之后**执行（上面的哈希校验已消除时序差异），
    # 但要在"口令错误"之前返回 —— 否则 SSO 账号没有本地口令，
    # 用户拿 IdP 的密码登录会撞上"用户名或口令错误"，永远拿不到去 IdP 的引导。
    if user is not None and user.is_sso:
        logger.info("本地口令入口拦截 SSO 账号 username=%s", username)
        raise SSORequiredError(
            f"该账号已接入{user.auth_source_label}，请使用统一身份认证登录"
        )

    if not user or not ok:
        logger.warning("登录失败 username=%s", username)
        raise AuthError("用户名或口令错误")
    if not user.is_active:
        raise AuthError("账号已停用，请联系管理员")

    # 更新登录时间；哈希参数升级时静默迁移
    user.last_login_at = utcnow()
    if needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(password)
    db.flush()
    return user


# ----------------------------------------------------------------------
# 密码管理
# ----------------------------------------------------------------------
def change_password(db: Session, user: User, old_password: str, new_password: str) -> None:
    """用户自助修改密码。"""
    if user.is_sso or not user.hashed_password:
        raise AppError("统一身份认证账号没有本地口令；如需改用本地登录请联系管理员解绑")
    if not verify_password(old_password, user.hashed_password):
        raise ValidationError("原密码不正确")
    ok, msg = validate_password_strength(new_password)
    if not ok:
        raise WeakPasswordError(msg)
    if verify_password(new_password, user.hashed_password):
        raise ValidationError("新密码不能与旧密码相同")

    user.hashed_password = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = utcnow()
    db.flush()


def reset_password(db: Session, user: User, new_password: str | None = None) -> str:
    """管理员重置密码，返回新口令（未指定时自动生成随机口令）。

    重置后强制用户下次登录修改密码。
    """
    if user.is_sso:
        raise AppError(
            "该账号使用统一身份认证，重置本地口令无意义；如需转为本地登录请先解绑"
        )
    password = new_password or generate_temp_password()
    if new_password:
        ok, msg = validate_password_strength(password)
        if not ok:
            raise WeakPasswordError(msg)

    user.hashed_password = hash_password(password)
    user.must_change_password = True
    user.password_changed_at = utcnow()
    db.flush()
    return password


# ----------------------------------------------------------------------
# 用户管理
# ----------------------------------------------------------------------
def create_user(db: Session, payload: Any, *, actor_is_admin: bool = False) -> tuple[User, str]:
    """创建用户，返回 (用户对象, 初始口令)。

    口令未显式提供时自动生成满足强度策略的随机口令。注意：**初始口令只在此处返回一次**，
    调用方负责安全地交付给用户，系统不保存明文。
    """
    exists = db.execute(select(User.id).where(User.username == payload.username)).first()
    if exists:
        raise AppError(f"登录名 {payload.username} 已存在")

    raw_password = getattr(payload, "password", None) or generate_temp_password()
    ok, msg = validate_password_strength(raw_password)
    if not ok:
        raise WeakPasswordError(msg)

    user = User(
        username=payload.username,
        full_name=payload.full_name,
        email=getattr(payload, "email", None),
        hashed_password=hash_password(raw_password),
        is_active=getattr(payload, "is_active", True),
        is_superuser=getattr(payload, "is_superuser", False) if actor_is_admin else False,
        must_change_password=True,
        password_changed_at=utcnow(),
    )
    db.add(user)
    db.flush()

    _sync_memberships(
        db,
        user,
        department_ids=getattr(payload, "department_ids", []) or [],
        leader_ids=getattr(payload, "leader_department_ids", []) or [],
    )
    return user, raw_password


def _sync_memberships(
    db: Session, user: User, *, department_ids: list[int], leader_ids: list[int]
) -> None:
    """同步用户与部门的归属关系（幂等）。"""
    existing = {m.department_id: m for m in user.memberships}
    target = set(department_ids)
    target.update(leader_ids)  # 组长身份隐含成员身份

    for dept_id in target:
        link = existing.get(dept_id)
        if link is None:
            db.add(
                DepartmentMember(
                    user_id=user.id,
                    department_id=dept_id,
                    is_leader=dept_id in leader_ids,
                    joined_at=dt.date.today(),
                )
            )
        else:
            link.is_leader = dept_id in leader_ids

    for dept_id, link in existing.items():
        if dept_id not in target:
            db.delete(link)

    db.flush()


def update_user(db: Session, user: User, payload: Any) -> None:
    """更新用户资料与归属部门。"""
    if getattr(payload, "full_name", None) is not None:
        user.full_name = payload.full_name
    if getattr(payload, "email", None) is not None:
        user.email = payload.email
    if getattr(payload, "is_active", None) is not None:
        user.is_active = payload.is_active
    if getattr(payload, "is_superuser", None) is not None:
        user.is_superuser = payload.is_superuser

    dept_ids = getattr(payload, "department_ids", None)
    leader_ids = getattr(payload, "leader_department_ids", None)
    if dept_ids is not None or leader_ids is not None:
        current_ids = user.department_ids
        current_leaders = user.leader_department_ids
        _sync_memberships(
            db,
            user,
            department_ids=dept_ids if dept_ids is not None else current_ids,
            leader_ids=leader_ids if leader_ids is not None else current_leaders,
        )
    db.flush()


# ----------------------------------------------------------------------
# 请假
# ----------------------------------------------------------------------
def list_active_leaves_in_week(
    db: Session, *, user_ids: list[int], week_start: dt.date
) -> dict[int, LeaveRequest]:
    """查询指定用户在某一自然周内已审批通过的请假。

    判定规则：请假区间与本周任意一天相交即视为本周豁免。

    :return: {user_id: LeaveRequest}
    """
    if not user_ids:
        return {}
    ws = ensure_date(week_start)
    we = week_end_of(ws)
    stmt = select(LeaveRequest).where(
        LeaveRequest.user_id.in_(user_ids),
        LeaveRequest.status == LeaveStatus.approved,
        LeaveRequest.start_date <= we,
        LeaveRequest.end_date >= ws,
    )
    result: dict[int, LeaveRequest] = {}
    for leave in db.execute(stmt).scalars().all():
        # 一个用户在本周可能有多段请假，取结束日最晚的一段作为说明
        current = result.get(leave.user_id)
        if current is None or leave.end_date > current.end_date:
            result[leave.user_id] = leave
    return result


def ensure_active_department(db: Session, department_id: int) -> Department:
    """确保部门存在且启用。"""
    dept = db.get(Department, department_id)
    if dept is None:
        raise AppError("部门不存在")
    if not dept.is_active:
        raise AppError("部门已停用")
    return dept


def current_local_date() -> dt.date:
    """当前本地日期（便于测试注入）。"""
    return localnow().date()


def normalize_week_start(value: dt.date | dt.datetime | None) -> dt.date:
    """把任意传入日期归一化为所在周的周一。"""
    if value is None:
        return week_start_of(current_local_date())
    return week_start_of(ensure_date(value))
