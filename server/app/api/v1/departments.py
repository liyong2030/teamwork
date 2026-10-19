"""部门管理接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import delete, select

from app.core.deps import CurrentUserDep, DbSession, SuperUserDep
from app.core.exceptions import AppError, NotFoundError
from app.models.organization import Department, DepartmentMember, User
from app.schemas.common import MessageResponse
from app.schemas.organization import AssignMemberRequest, DepartmentCreate, DepartmentUpdate
from app.services import audit, permission

router = APIRouter(prefix="/departments", tags=["部门管理"])


def _serialize(dept: Department) -> dict[str, Any]:
    members = sorted(
        dept.memberships, key=lambda m: (not m.is_leader, m.user.full_name if m.user else "")
    )
    return {
        "id": dept.id,
        "name": dept.name,
        "parent_id": dept.parent_id,
        "leader_id": dept.leader_id,
        "sort_order": dept.sort_order,
        "is_active": dept.is_active,
        "created_at": dept.created_at,
        "member_count": len(dept.memberships),
        "members": [
            {
                "user_id": m.user_id,
                "username": m.user.username if m.user else None,
                "full_name": m.user.full_name if m.user else None,
                "is_leader": m.is_leader,
            }
            for m in members
        ],
    }


@router.get("", summary="部门列表")
def list_departments(db: DbSession, user: CurrentUserDep) -> list[dict[str, Any]]:
    """管理员看全部；其他人只能看自己所属的部门。"""
    rows = (
        db.execute(select(Department).order_by(Department.sort_order, Department.id))
        .scalars()
        .all()
    )
    all_ids = [d.id for d in rows]
    visible = permission.visible_department_ids(user, all_ids)
    return [_serialize(d) for d in rows if d.id in visible]


@router.post("", response_model=MessageResponse, summary="创建部门")
def create_department(
    payload: DepartmentCreate,
    request: Request,
    admin: SuperUserDep,
    db: DbSession,
) -> MessageResponse:
    exists = db.execute(
        select(Department).where(
            Department.name == payload.name, Department.parent_id == payload.parent_id
        )
    ).first()
    if exists:
        raise AppError("同级下已存在同名部门")

    dept = Department(
        name=payload.name,
        parent_id=payload.parent_id,
        leader_id=payload.leader_id,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    db.add(dept)
    db.flush()

    for uid in payload.member_ids:
        db.add(DepartmentMember(user_id=uid, department_id=dept.id, is_leader=False))

    audit.record(
        db,
        action="department.create",
        actor_id=admin.id,
        target_type="department",
        target_id=dept.id,
        detail={"name": dept.name},
        request=request,
    )
    db.commit()
    return MessageResponse(message="部门已创建", id=dept.id)


@router.patch("/{department_id}", response_model=MessageResponse, summary="更新部门")
def update_department(
    department_id: int,
    payload: DepartmentUpdate,
    request: Request,
    admin: SuperUserDep,
    db: DbSession,
) -> MessageResponse:
    dept = db.get(Department, department_id)
    if dept is None:
        raise NotFoundError("部门不存在")

    for field_name in ("name", "parent_id", "leader_id", "sort_order", "is_active"):
        value = getattr(payload, field_name)
        if value is not None:
            setattr(dept, field_name, value)

    if payload.member_ids is not None:
        current = {m.user_id: m for m in dept.memberships}
        for uid in payload.member_ids:
            if uid not in current:
                db.add(DepartmentMember(user_id=uid, department_id=dept.id, is_leader=False))
        for uid, link in current.items():
            if uid not in payload.member_ids:
                db.delete(link)
    if payload.leader_ids is not None:
        for link in dept.memberships:
            link.is_leader = link.user_id in payload.leader_ids

    audit.record(
        db,
        action="department.update",
        actor_id=admin.id,
        target_type="department",
        target_id=dept.id,
        detail=payload.model_dump(exclude_none=True),
        request=request,
    )
    db.commit()
    return MessageResponse(message="部门已更新", id=dept.id)


@router.delete("/{department_id}", response_model=MessageResponse, summary="停用部门")
def deactivate_department(
    department_id: int, request: Request, admin: SuperUserDep, db: DbSession
) -> MessageResponse:
    """停用部门：停用后其成员不再计入周报应提交名单。"""
    dept = db.get(Department, department_id)
    if dept is None:
        raise NotFoundError("部门不存在")
    dept.is_active = False
    audit.record(
        db,
        action="department.deactivate",
        actor_id=admin.id,
        target_type="department",
        target_id=dept.id,
        request=request,
    )
    db.commit()
    return MessageResponse(message="部门已停用")


@router.post(
    "/{department_id}/members", response_model=MessageResponse, summary="添加/调整部门成员"
)
def assign_member(
    department_id: int,
    payload: AssignMemberRequest,
    request: Request,
    admin: SuperUserDep,
    db: DbSession,
) -> MessageResponse:
    dept = db.get(Department, department_id)
    if dept is None:
        raise NotFoundError("部门不存在")
    if db.get(User, payload.user_id) is None:
        raise NotFoundError("用户不存在")

    link = db.execute(
        select(DepartmentMember).where(
            DepartmentMember.department_id == department_id,
            DepartmentMember.user_id == payload.user_id,
        )
    ).scalar_one_or_none()
    if link is None:
        db.add(
            DepartmentMember(
                user_id=payload.user_id,
                department_id=department_id,
                is_leader=payload.is_leader,
            )
        )
    else:
        link.is_leader = payload.is_leader

    audit.record(
        db,
        action="department.member.assign",
        actor_id=admin.id,
        target_type="department",
        target_id=department_id,
        detail={"user_id": payload.user_id, "is_leader": payload.is_leader},
        request=request,
    )
    db.commit()
    return MessageResponse(message="成员已更新")


@router.delete(
    "/{department_id}/members/{user_id}", response_model=MessageResponse, summary="移除成员"
)
def remove_member(
    department_id: int, user_id: int, request: Request, admin: SuperUserDep, db: DbSession
) -> MessageResponse:
    link = db.execute(
        select(DepartmentMember).where(
            DepartmentMember.department_id == department_id,
            DepartmentMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if link is None:
        raise NotFoundError("该成员不在部门中")
    db.execute(
        delete(DepartmentMember).where(
            DepartmentMember.department_id == department_id,
            DepartmentMember.user_id == user_id,
        )
    )
    audit.record(
        db,
        action="department.member.remove",
        actor_id=admin.id,
        target_type="department",
        target_id=department_id,
        detail={"user_id": user_id},
        request=request,
    )
    db.commit()
    return MessageResponse(message="成员已移除")
