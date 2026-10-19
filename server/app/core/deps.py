"""FastAPI 依赖注入：数据库会话、当前登录用户、角色守卫。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AuthError, ForbiddenError
from app.core.security import decode_token
from app.db.session import SessionLocal, get_db
from app.models.organization import User
from app.services.auth_service import load_user_from_payload

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,
    scheme_name="JWT",
)

DbSession = Annotated[Session, Depends(get_db)]


def get_optional_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: DbSession,
) -> User | None:
    """解析当前用户，未携带令牌或令牌无效时返回 None（供可选登录接口使用）。"""
    if not token:
        return None
    payload = decode_token(token, expected_type="access")
    if payload is None:
        return None
    user = load_user_from_payload(db, payload)
    request.state.current_user = user
    return user


OptionalUserDep = Annotated[User | None, Depends(get_optional_user)]


def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: DbSession,
) -> User:
    """获取当前登录用户，未认证或令牌失效返回 401。"""
    if not token:
        raise AuthError("未提供访问令牌")
    payload = decode_token(token, expected_type="access")
    if payload is None:
        raise AuthError("访问令牌无效或已过期")
    user = load_user_from_payload(db, payload)
    if user is None:
        raise AuthError("用户不存在或已停用")
    request.state.current_user = user
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_superuser(user: CurrentUserDep) -> User:
    """管理员守卫。"""
    if not user.is_superuser:
        raise ForbiddenError("需要系统管理员权限")
    return user


def require_leader_or_admin(user: CurrentUserDep) -> User:
    """组长（任意部门）或管理员守卫。"""
    if not (user.is_superuser or user.leader_department_ids):
        raise ForbiddenError("需要部门组长或管理员权限")
    return user


SuperUserDep = Annotated[User, Depends(require_superuser)]
LeaderDep = Annotated[User, Depends(require_leader_or_admin)]


def job_session() -> Session:
    """定时任务专用的独立会话（不建议在请求上下文使用）。"""
    return SessionLocal()
