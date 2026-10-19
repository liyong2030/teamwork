"""项目接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUserDep, DbSession
from app.core.exceptions import AppError, NotFoundError
from app.models.organization import User
from app.models.project import Project, ProjectMember, Task
from app.schemas.common import MessageResponse
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services import audit, permission, project_service, task_service

router = APIRouter(prefix="/projects", tags=["项目管理"])


def _serialize(db: DbSession, project: Project, viewer: User | None = None) -> dict[str, Any]:
    task_total, task_done, overdue = task_service.project_progress(db, project.id, viewer=viewer)
    members = sorted(project.members, key=lambda m: m.id)
    return {
        "id": project.id,
        "name": project.name,
        "code": project.code,
        "description": project.description,
        "department_id": project.department_id,
        "department_name": project.department.name if project.department else None,
        "owner_id": project.owner_id,
        "owner_name": project.owner.full_name if project.owner else None,
        "status": project.status.value,
        "start_date": project.start_date,
        "end_date": project.end_date,
        "sort_order": project.sort_order,
        "created_at": project.created_at,
        "task_total": task_total,
        "task_done": task_done,
        "overdue_count": overdue,
        "member_ids": [m.user_id for m in members],
    }


@router.get("", summary="项目列表")
def list_projects(
    db: DbSession,
    user: CurrentUserDep,
    keyword: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """管理员看全部；其他角色看自己参与的（负责人/成员/归属部门可见）。"""
    stmt = select(Project).order_by(Project.sort_order, Project.id)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        stmt = stmt.where(Project.name.like(pattern) | Project.code.like(pattern))
    if status:
        stmt = stmt.where(Project.status == status)

    rows = db.execute(stmt).scalars().all()
    result = []
    for project in rows:
        if user.is_superuser or permission.can_manage_department(user, project.department_id or -1):
            result.append(project)
            continue
        if project.owner_id == user.id:
            result.append(project)
            continue
        member_ids = [m.user_id for m in project.members]
        if not member_ids:
            member_ids = [
                row[0]
                for row in db.execute(
                    select(Task.id)
                    .where(Task.project_id == project.id, Task.owner_id == user.id)
                    .limit(1)
                ).all()
            ]
        if user.id in member_ids:
            result.append(project)
            continue
        # 参与了该项目任务的人也能看到项目
        participated = db.execute(
            select(Task.id).where(Task.project_id == project.id, Task.owner_id == user.id).limit(1)
        ).first()
        if participated:
            result.append(project)

    return [_serialize(db, p, viewer=user) for p in result[offset : offset + limit]]


@router.get("/next-code", summary="预览下一个项目编号")
def next_project_code(db: DbSession, _user: CurrentUserDep) -> dict[str, str]:
    """仅供前端在新建表单里做占位提示，真正落库时仍会重新生成（避免并发撞号）。"""
    return {"code": project_service.generate_project_code(db)}


@router.post("", response_model=MessageResponse, summary="创建项目")
def create_project(
    payload: ProjectCreate, request: Request, user: CurrentUserDep, db: DbSession
) -> MessageResponse:
    owner_id = payload.owner_id or user.id
    if db.get(User, owner_id) is None:
        raise NotFoundError("项目负责人不存在")

    code = project_service.resolve_project_code(db, payload.code)

    project = Project(
        name=payload.name.strip(),
        code=code,
        description=payload.description,
        department_id=payload.department_id,
        owner_id=owner_id,
        status=payload.status,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    db.add(project)
    db.flush()

    for uid in payload.member_ids:
        db.add(ProjectMember(project_id=project.id, user_id=uid))

    audit.record(
        db,
        action="project.create",
        actor_id=user.id,
        target_type="project",
        target_id=project.id,
        detail={"code": project.code},
        request=request,
    )
    db.commit()
    return MessageResponse(message="项目已创建", id=project.id)


@router.get("/{project_id}", summary="项目详情")
def read_project(project_id: int, db: DbSession, user: CurrentUserDep) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    return _serialize(db, project, viewer=user)


@router.patch("/{project_id}", response_model=MessageResponse, summary="更新项目")
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    request: Request,
    user: CurrentUserDep,
    db: DbSession,
) -> MessageResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    if not permission.can_manage_project(
        user, project.owner_id, project.department_id
    ) and not user.is_superuser:
        raise AppError("无权修改该项目")

    for field_name in (
        "name",
        "code",
        "description",
        "department_id",
        "owner_id",
        "status",
        "start_date",
        "end_date",
    ):
        value = getattr(payload, field_name)
        if value is not None:
            setattr(project, field_name, value)

    if payload.member_ids is not None:
        current = {m.user_id: m for m in project.members}
        for uid in payload.member_ids:
            if uid not in current:
                db.add(ProjectMember(project_id=project.id, user_id=uid))
        for uid, link in current.items():
            if uid not in payload.member_ids:
                db.delete(link)

    audit.record(
        db,
        action="project.update",
        actor_id=user.id,
        target_type="project",
        target_id=project.id,
        detail=payload.model_dump(exclude_none=True),
        request=request,
    )
    db.commit()
    return MessageResponse(message="项目已更新", id=project.id)


@router.get("/{project_id}/board", summary="项目看板")
def project_board(project_id: int, db: DbSession, user: CurrentUserDep) -> list[dict[str, Any]]:
    """看板数据：按状态分列返回任务（仅当前用户可见的任务）。"""
    columns = task_service.board_columns(db, project_id, viewer=user)
    return [
        {"status": status, "title": title, "tasks": [_task_out(t) for t in tasks]}
        for status, title, tasks in columns
    ]


@router.get("/{project_id}/summary", summary="项目统计")
def project_summary(project_id: int, db: DbSession, user: CurrentUserDep) -> dict[str, Any]:
    task_total, task_done, overdue = task_service.project_progress(db, project_id, viewer=user)
    stmt = select(Task.status, func.count(Task.id)).where(Task.project_id == project_id)
    stmt = task_service.apply_task_visibility(stmt, user)
    rows = db.execute(stmt.group_by(Task.status)).all()
    return {
        "project_id": project_id,
        "task_total": task_total,
        "task_done": task_done,
        "overdue_count": overdue,
        "by_status": {status.value: count for status, count in rows},
    }


def _task_out(task: Task) -> dict[str, Any]:
    """任务序列化（与 tasks.router 保持一致，避免重复实现）。"""
    from app.api.v1.tasks import serialize_task

    return serialize_task(task)
