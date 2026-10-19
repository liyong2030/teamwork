"""认证接口：登录、刷新令牌、登出、改密、当前用户信息。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from app.core.config import settings
from app.core.deps import CurrentUserDep, DbSession
from app.core.exceptions import AuthError
from app.core.security import decode_token
from app.schemas.auth import (
    ChangePasswordRequest,
    CurrentUser,
    LoginRequest,
    RefreshRequest,
    SSOLoginRequest,
    TokenResponse,
)
from app.schemas.common import MessageResponse
from app.services import audit, auth_service, sso_service

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=TokenResponse, summary="登录")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> dict[str, Any]:
    """用户名 + 口令登录，返回 Access / Refresh 令牌。

    Refresh 令牌同时写入 HttpOnly Cookie（SameSite=Lax），前端可选择只用 body 中的结果。
    """
    user = auth_service.authenticate(db, payload.username, payload.password)
    tokens = auth_service.issue_tokens(user)

    audit.record(
        db,
        action="auth.login",
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
        request=request,
    )
    db.commit()

    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        samesite="lax",
        secure=settings.app_env == "prod",
        max_age=settings.refresh_token_expire_days * 86400,
    )
    return tokens


@router.get("/sso/config", summary="统一身份认证配置")
def sso_config() -> dict[str, Any]:
    """登录页据此判断是否展示统一身份认证入口（**不含任何密钥**）。"""
    return sso_service.public_config()


@router.post("/sso/login", response_model=TokenResponse, summary="统一身份认证登录")
def sso_login(
    payload: SSOLoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> dict[str, Any]:
    """账号 + 口令由后端代理提交给 IdP 校验，通过即签发本系统令牌。

    与 ``POST /auth/login`` 的差别只在校验方：本地哈希 vs 统一身份认证系统。
    登录后的令牌、权限、会话完全一样。
    """
    user = sso_service.authenticate_via_sso(
        db, username=payload.username, password=payload.password, request=request
    )
    tokens = auth_service.issue_tokens(user)

    audit.record(
        db,
        action="auth.login.sso.token",
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
        request=request,
    )
    db.commit()

    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        samesite="lax",
        secure=settings.app_env == "prod",
        max_age=settings.refresh_token_expire_days * 86400,
    )
    return tokens


@router.post("/refresh", response_model=TokenResponse, summary="刷新令牌")
def refresh(payload: RefreshRequest, db: DbSession) -> dict[str, Any]:
    """用 Refresh 令牌换取新的令牌对。"""
    data = decode_token(payload.refresh_token, expected_type="refresh")
    if data is None:
        from app.core.exceptions import AuthError

        raise AuthError("刷新令牌无效或已过期")

    user = auth_service.load_user_from_payload(db, data)
    if user is None:
        from app.core.exceptions import AuthError

        raise AuthError("用户不存在或已停用")
    return auth_service.issue_tokens(user)


@router.get("/me", response_model=CurrentUser, summary="当前登录用户")
def read_me(user: CurrentUserDep) -> dict[str, Any]:
    """返回当前用户的完整上下文（含部门与组长身份）。"""
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "is_superuser": user.is_superuser,
        "must_change_password": user.must_change_password,
        "department_ids": user.department_ids,
        "leader_department_ids": user.leader_department_ids,
        "is_department_leader": bool(user.leader_department_ids),
        "auth_source": user.auth_source,
        "is_sso": user.is_sso,
    }


@router.post("/change-password", response_model=MessageResponse, summary="修改密码")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: CurrentUserDep,
    db: DbSession,
) -> MessageResponse:
    auth_service.change_password(db, user, payload.old_password, payload.new_password)
    audit.record(
        db,
        action="user.password.change",
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
        request=request,
    )
    db.commit()
    return MessageResponse(message="密码修改成功，请重新登录")


@router.post("/logout", response_model=MessageResponse, summary="登出")
def logout(request: Request, user: CurrentUserDep, db: DbSession) -> MessageResponse:
    """服务端无状态，登出仅记录审计；前端负责丢弃本地令牌。"""
    audit.record(db, action="auth.logout", actor_id=user.id, target_type="user", target_id=user.id, request=request)
    db.commit()
    return MessageResponse(message="已登出")


@router.get("/password-policy", summary="查询口令策略")
def password_policy() -> dict[str, Any]:
    """供前端渲染口令强度提示。"""

    return {
        "min_length": settings.password_min_length,
        "require_classes": 3,
        "description": (
            f"口令至少 {settings.password_min_length} 位，"
            f"且需包含大写、小写、数字、符号中的至少三类，不能含空格"
        ),
    }
