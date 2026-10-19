"""任务接口：列表、看板、CRUD、状态流转、检查清单。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.core.deps import CurrentUserDep, DbSession
from app.core.exceptions import AppError, NotFoundError
from app.models.enums import TaskStatus
from app.models.organization import User
from app.models.project import Project, Task, TaskCollaborator
from app.schemas.common import MessageResponse
from app.schemas.project import (
    ChecklistToggleRequest,
    TaskCreate,
    TaskMoveRequest,
    TaskStatusChangeRequest,
    TaskUpdate,
)
from app.services import audit, permission, task_service

router = APIRouter(prefix="/tasks", tags=["任务管理"])


def serialize_task(task: Task) -> dict[str, Any]:
    """任务 → 前端字典（含派生字段 is_overdue）。"""
    return {
        "id": task.id,
        "project_id": task.project_id,
        "project_name": task.project.name if task.project else None,
        "project_code": task.project.code if task.project else None,
        "title": task.title,
        "description": task.description,
        "owner_id": task.owner_id,
        "owner_name": task.owner.full_name if task.owner else None,
        "collaborator_ids": task.collaborator_ids,
        "priority": task.priority.value,
        "status": task.status.value,
        "start_date": task.start_date,
        "due_date": task.due_date,
        "progress": task.progress,
        "estimated_hours": float(task.estimated_hours) if task.estimated_hours is not None else None,
        "actual_hours": float(task.actual_hours) if task.actual_hours is not None else None,
        "checklist": task.checklist or [],
        "tags": task.tags or [],
        "sort_order": task.sort_order,
        "is_overdue": task.is_overdue,
        "completed_at": task.completed_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


@router.get("", summary="任务列表")
def list_tasks(
    db: DbSession,
    user: CurrentUserDep,
    project_id: int | None = None,
    owner_id: int | None = None,
    participant_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    tasks, _total = task_service.list_tasks(
        db,
        project_id=project_id,
        owner_id=owner_id,
        participant_id=participant_id,
        status=TaskStatus(status) if status else None,
        keyword=keyword,
        viewer=user,
        limit=limit,
        offset=offset,
    )
    return [serialize_task(t) for t in tasks]


@router.get("/mine", summary="我的任务")
def my_tasks(
    db: DbSession,
    user: CurrentUserDep,
    only_open: bool = Query(True, description="仅显示未完成任务"),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    tasks, _ = task_service.list_tasks(
        db, participant_id=user.id, only_mine_open=only_open, viewer=user, limit=limit
    )
    # 按截止日排序（无截止日的排最后）
    tasks.sort(key=lambda t: (t.due_date is None, t.due_date or 0))
    return [serialize_task(t) for t in tasks]


@router.post("", response_model=MessageResponse, summary="创建任务")
def create_task(
    payload: TaskCreate, request: Request, user: CurrentUserDep, db: DbSession
) -> MessageResponse:
    project = db.get(Project, payload.project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    task = task_service.create_task(db, payload, user)
    audit.record(
        db,
        action="task.create",
        actor_id=user.id,
        target_type="task",
        target_id=task.id,
        detail={"title": task.title, "project_id": task.project_id},
        request=request,
    )
    db.commit()
    return MessageResponse(message="任务已创建", id=task.id)


@router.get("/{task_id}", summary="任务详情")
def read_task(task_id: int, db: DbSession, user: CurrentUserDep) -> dict[str, Any]:
    task = task_service.get_task(db, task_id)
    permission.assert_can_view_task(user, task, db)
    return serialize_task(task)


@router.patch("/{task_id}", response_model=MessageResponse, summary="更新任务")
def update_task(
    task_id: int,
    payload: TaskUpdate,
    request: Request,
    user: CurrentUserDep,
    db: DbSession,
) -> MessageResponse:
    task = task_service.get_task(db, task_id)
    permission.assert_can_edit_task(user, task, db)
    task_service.update_task(db, task, payload, user)
    audit.record(
        db,
        action="task.update",
        actor_id=user.id,
        target_type="task",
        target_id=task.id,
        detail=payload.model_dump(exclude_none=True),
        request=request,
    )
    db.commit()
    return MessageResponse(message="任务已更新", id=task.id)


@router.post("/{task_id}/status", response_model=MessageResponse, summary="变更任务状态")
def change_status(
    task_id: int,
    payload: TaskStatusChangeRequest,
    request: Request,
    user: CurrentUserDep,
    db: DbSession,
) -> MessageResponse:
    """状态流转的唯一入口：写主表的同时写 ``task_status_logs`` 流水。"""
    task = task_service.get_task(db, task_id)
    permission.assert_can_edit_task(user, task, db)
    old_status = task.status.value
    task_service.change_status(
        db,
        task=task,
        actor=user,
        to_status=payload.to_status,
        progress=payload.progress,
        remark=payload.remark,
    )
    audit.record(
        db,
        action="task.status.change",
        actor_id=user.id,
        target_type="task",
        target_id=task.id,
        detail={"from": old_status, "to": payload.to_status.value, "remark": payload.remark},
        request=request,
    )
    db.commit()
    return MessageResponse(message="状态已更新", id=task.id)


@router.post("/{task_id}/move", response_model=MessageResponse, summary="看板拖拽移动")
def move_task(
    task_id: int,
    payload: TaskMoveRequest,
    request: Request,
    user: CurrentUserDep,
    db: DbSession,
) -> MessageResponse:
    task = task_service.get_task(db, task_id)
    permission.assert_can_edit_task(user, task, db)
    old_status = task.status.value
    task_service.move_task(db, task, user, payload.to_status, payload.before_id)
    if old_status != payload.to_status.value:
        audit.record(
            db,
            action="task.status.change",
            actor_id=user.id,
            target_type="task",
            target_id=task.id,
            detail={"from": old_status, "to": payload.to_status.value, "via": "board"},
            request=request,
        )
    db.commit()
    return MessageResponse(message="任务已移动", id=task.id)


@router.post("/{task_id}/checklist", response_model=MessageResponse, summary="勾选检查项")
def toggle_checklist(
    task_id: int,
    payload: ChecklistToggleRequest,
    user: CurrentUserDep,
    db: DbSession,
) -> MessageResponse:
    task = task_service.get_task(db, task_id)
    permission.assert_can_edit_task(user, task, db)
    task_service.toggle_checklist(db, task, payload.index, payload.done)
    db.commit()
    return MessageResponse(message="检查项已更新", id=task.id)


@router.delete("/{task_id}", response_model=MessageResponse, summary="取消任务")
def cancel_task(
    task_id: int, request: Request, user: CurrentUserDep, db: DbSession
) -> MessageResponse:
    """软取消：状态置 ``cancelled``，保留历史数据，不物理删除。"""
    task = task_service.get_task(db, task_id)
    permission.assert_can_edit_task(user, task, db)
    old_status = task.status.value
    task_service.change_status(
        db, task=task, actor=user, to_status=TaskStatus.CANCELLED, remark="取消任务"
    )
    audit.record(
        db,
        action="task.cancel",
        actor_id=user.id,
        target_type="task",
        target_id=task.id,
        detail={"from": old_status},
        request=request,
    )
    db.commit()
    return MessageResponse(message="任务已取消", id=task.id)


@router.get("/{task_id}/logs", summary="任务状态流水")
def task_logs(task_id: int, db: DbSession, user: CurrentUserDep) -> list[dict[str, Any]]:
    """按时间倒序返回状态变更记录。"""
    task = task_service.get_task(db, task_id)
    permission.assert_can_view_task(user, task, db)
    logs = task_service.recent_logs(db, task_id)
    operator_ids = {log.operator_id for log in logs}
    names = {
        u.id: u.full_name
        for u in db.execute(select(User).where(User.id.in_(operator_ids))).scalars().all()
    } if operator_ids else {}
    return [
        {
            "id": log.id,
            "task_id": log.task_id,
            "from_status": log.from_status.value if log.from_status else None,
            "to_status": log.to_status.value,
            "from_progress": log.from_progress,
            "to_progress": log.to_progress,
            "operator_id": log.operator_id,
            "operator_name": names.get(log.operator_id),
            "remark": log.remark,
            "created_at": log.created_at,
        }
        for log in logs
    ]


@router.post(
    "/{task_id}/collaborators", response_model=MessageResponse, summary="设置协作人"
)
def set_collaborators(
    task_id: int,
    payload: dict[str, Any],
    user: CurrentUserDep,
    db: DbSession,
) -> MessageResponse:
    """全量覆盖协作人列表，入参形如 ``{"user_ids": [1,2,3]}``。"""
    task = task_service.get_task(db, task_id)
    permission.assert_can_edit_task(user, task, db)
    user_ids = [int(uid) for uid in (payload.get("user_ids") or [])]
    for uid in user_ids:
        if db.get(User, uid) is None:
            raise AppError(f"用户 {uid} 不存在")
    task_service.set_collaborators(db, task, user_ids)
    db.commit()
    return MessageResponse(message="协作人已更新", id=task.id)


@router.get("/collaborators/options", summary="可选成员列表")
def collaborator_options(db: DbSession, _user: CurrentUserDep) -> list[dict[str, Any]]:
    """下拉选人用：返回全部在职成员的简要信息。"""
    users = (
        db.execute(select(User).where(User.is_active.is_(True)).order_by(User.full_name))
        .scalars()
        .all()
    )
    return [
        {"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email}
        for u in users
    ]
