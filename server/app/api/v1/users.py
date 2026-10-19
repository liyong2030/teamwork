"""用户管理接口（管理员专用）与请假申请的读取辅助。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.core.deps import CurrentUserDep, DbSession, SuperUserDep
from app.core.exceptions import AppError, NotFoundError
from app.models.organization import Department, User
from app.schemas.auth import (
    ResetPasswordResponse,
    SSOBindRequest,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.schemas.common import MessageResponse, Page
from app.services import audit, auth_service, permission, sso_service

router = APIRouter(prefix="/users", tags=["用户管理"])


def _serialize(db: DbSession, user: User) -> dict[str, Any]:
    dept_names = [
        db.get(Department, dept_id).name
        for dept_id in user.department_ids
        if db.get(Department, dept_id)
    ]
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "must_change_password": user.must_change_password,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
        "department_ids": user.department_ids,
        "leader_department_ids": user.leader_department_ids,
        "department_names": dept_names,
        "auth_source": user.auth_source,
        "auth_source_label": user.auth_source_label,
        "external_id": user.external_id,
        "is_sso": user.is_sso,
    }


@router.get("", response_model=Page[UserOut], summary="用户列表")
def list_users(
    db: DbSession,
    _admin: SuperUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
    department_id: int | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    stmt = select(User).order_by(User.id)
    if keyword:
        stmt = stmt.where(
            User.full_name.like(f"%{keyword.strip()}%")
            | User.username.like(f"%{keyword.strip()}%")
        )
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    if department_id is not None:
        from app.models.organization import DepartmentMember

        stmt = stmt.where(
            User.id.in_(
                select(DepartmentMember.user_id).where(
                    DepartmentMember.department_id == department_id
                )
            )
        )

    total = len(db.execute(stmt).scalars().all())
    rows = (
        db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    )
    return {"items": [_serialize(db, u) for u in rows], "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=ResetPasswordResponse, summary="创建用户")
def create_user(
    payload: UserCreate,
    request: Request,
    admin: SuperUserDep,
    db: DbSession,
) -> dict[str, Any]:
    """创建用户。未指定口令时自动生成随机初始口令，**仅在此响应中返回一次**。"""
    user, raw_password = auth_service.create_user(db, payload, actor_is_admin=True)
    audit.record(
        db,
        action="user.create",
        actor_id=admin.id,
        target_type="user",
        target_id=user.id,
        detail={"username": user.username},
        request=request,
    )
    db.commit()
    return {"message": "用户已创建，初始口令请妥善转达", "temp_password": raw_password}


@router.get("/{user_id}", response_model=UserOut, summary="用户详情")
def read_user(user_id: int, db: DbSession, _admin: SuperUserDep) -> dict[str, Any]:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    return _serialize(db, user)


@router.patch("/{user_id}", response_model=UserOut, summary="更新用户")
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    admin: SuperUserDep,
    db: DbSession,
) -> dict[str, Any]:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    if user.id == admin.id and payload.is_superuser is False:
        raise AppError("不能取消自己的管理员权限")

    auth_service.update_user(db, user, payload)
    audit.record(
        db,
        action="user.update",
        actor_id=admin.id,
        target_type="user",
        target_id=user.id,
        detail=payload.model_dump(exclude_none=True),
        request=request,
    )
    db.commit()
    return _serialize(db, user)


@router.post("/{user_id}/reset-password", response_model=ResetPasswordResponse, summary="重置密码")
def reset_password(
    user_id: int,
    request: Request,
    admin: SuperUserDep,
    db: DbSession,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """管理员重置用户密码，返回新口令并强制用户下次登录修改。"""
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    new_password = (payload or {}).get("new_password") if payload else None
    temp = auth_service.reset_password(db, user, new_password)
    audit.record(
        db,
        action="user.password.reset",
        actor_id=admin.id,
        target_type="user",
        target_id=user.id,
        request=request,
    )
    db.commit()
    return {"message": "密码已重置，请转告用户并在下次登录后修改", "temp_password": temp}


@router.delete("/{user_id}", response_model=MessageResponse, summary="停用用户")
def deactivate_user(
    user_id: int, request: Request, admin: SuperUserDep, db: DbSession
) -> MessageResponse:
    """离职/停用：**软删除**，保留全部历史数据，不物理删除记录。"""
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    if user.id == admin.id:
        raise AppError("不能停用自己")
    user.is_active = False
    audit.record(
        db,
        action="user.deactivate",
        actor_id=admin.id,
        target_type="user",
        target_id=user.id,
        request=request,
    )
    db.commit()
    return MessageResponse(message="用户已停用")


@router.post("/{user_id}/sso-bind", response_model=MessageResponse, summary="绑定统一身份")
def bind_sso(
    user_id: int,
    payload: SSOBindRequest,
    request: Request,
    admin: SuperUserDep,
    db: DbSession,
) -> MessageResponse:
    """管理员为既有账号绑定 IdP 标识。

    这是**超级管理员账号**接入统一身份的唯一途径（自动绑定会跳过它们，
    以保留 IdP 故障时的本地应急通道）。
    """
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    sso_service.bind_external(
        db, user=user, source=payload.source, external_id=payload.external_id, actor=admin
    )
    audit.record(
        db,
        action="user.sso.bind",
        actor_id=admin.id,
        target_type="user",
        target_id=user.id,
        detail={"source": payload.source, "external_id": payload.external_id},
        request=request,
    )
    db.commit()
    return MessageResponse(message=f"已绑定{payload.source}身份，该账号将使用统一身份认证登录")


@router.post(
    "/{user_id}/sso-unbind",
    response_model=ResetPasswordResponse,
    summary="解绑统一身份",
)
def unbind_sso(
    user_id: int,
    request: Request,
    admin: SuperUserDep,
    db: DbSession,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """解绑后恢复本地口令登录，返回随机初始口令（**只返回一次**）并强制改密。"""
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    new_password = (payload or {}).get("new_password") if payload else None
    temp = sso_service.unbind_sso(db, user=user, actor=admin, new_password=new_password)
    audit.record(
        db,
        action="user.sso.unbind",
        actor_id=admin.id,
        target_type="user",
        target_id=user.id,
        request=request,
    )
    db.commit()
    return {"message": "已解绑统一身份，请转告用户使用新口令登录并修改", "temp_password": temp}


@router.get("/me/profile", summary="我的资料")
def my_profile(user: CurrentUserDep, db: DbSession) -> dict[str, Any]:
    """当前用户查看/编辑自己的资料（不含敏感字段）。"""
    return _serialize(db, user)


@router.patch("/me/profile", response_model=MessageResponse, summary="更新我的资料")
def update_my_profile(
    payload: dict[str, Any], request: Request, user: CurrentUserDep, db: DbSession
) -> MessageResponse:
    """仅允许修改邮箱与姓名，其余字段（部门、角色）需管理员操作。"""
    allowed = {"full_name", "email"}
    unknown = set(payload) - allowed
    if unknown:
        raise AppError(f"不允许修改字段：{', '.join(sorted(unknown))}")
    if "full_name" in payload:
        user.full_name = payload["full_name"]
    if "email" in payload:
        user.email = payload["email"]
    audit.record(
        db,
        action="user.profile.update",
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
        detail=payload,
        request=request,
    )
    db.commit()
    return MessageResponse(message="资料已更新")
