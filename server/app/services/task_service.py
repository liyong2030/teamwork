"""任务服务：CRUD、看板排序、状态机流转（含流水写入）。

铁律：**状态与进度的任何变更都必须走 `change_status`**，只有这里会写
``task_status_logs`` 流水。流水是周报自动草稿的唯一数据源，漏写即数据失真。
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import AppError, NotFoundError
from app.models.enums import TaskStatus
from app.models.organization import DepartmentMember, User
from app.models.project import Project, Task, TaskCollaborator, TaskStatusLog
from app.utils.week import localnow, today_local, utcnow


# ----------------------------------------------------------------------
# 读取
# ----------------------------------------------------------------------
def get_task(db: Session, task_id: int, *, for_update: bool = False) -> Task:
    """按 ID 取任务，不存在抛 404。"""
    stmt = select(Task).where(Task.id == task_id)
    stmt = stmt.options(
        selectinload(Task.collaborator_links).selectinload(TaskCollaborator.user),
        selectinload(Task.owner),
        selectinload(Task.project),
    )
    if for_update:
        stmt = stmt.with_for_update()
    task = db.execute(stmt).scalar_one_or_none()
    if task is None:
        raise NotFoundError("任务不存在")
    return task


def visible_task_clause(user: User | None):
    """任务可见性过滤条件（SQL 表达式），管理员返回 ``None`` 表示不加限制。

    口径（与《需求规格说明书》一致）：
    - 管理员：全部可见；
    - 组长：本部门成员负责的任务 + 归属本部门项目的任务；
    - 普通成员：**仅负责人为自己或协作人包含自己的任务**。
    """
    if user is None or user.is_superuser:
        return None

    conditions = [
        Task.owner_id == user.id,
        Task.id.in_(
            select(TaskCollaborator.task_id).where(TaskCollaborator.user_id == user.id)
        ),
    ]

    leader_dept_ids = set(user.leader_department_ids)
    if leader_dept_ids:
        # 管辖部门成员负责的任务
        conditions.append(
            Task.owner_id.in_(
                select(DepartmentMember.user_id).where(
                    DepartmentMember.department_id.in_(leader_dept_ids)
                )
            )
        )
        # 归属管辖部门的项目下的任务
        conditions.append(
            Task.project_id.in_(
                select(Project.id).where(Project.department_id.in_(leader_dept_ids))
            )
        )

    return or_(*conditions)


def apply_task_visibility(stmt, user: User | None):
    """把可见性条件附加到查询上（管理员原样返回）。"""
    clause = visible_task_clause(user)
    if clause is None:
        return stmt
    return stmt.where(clause)


def list_tasks(
    db: Session,
    *,
    project_id: int | None = None,
    owner_id: int | None = None,
    participant_id: int | None = None,
    status: TaskStatus | None = None,
    keyword: str | None = None,
    only_mine_open: bool = False,
    viewer: User | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[Task], int]:
    """任务列表查询（带分页与可见性过滤）。

    :param viewer: 当前登录用户；传入后只返回其可见的任务
    """
    stmt = (
        select(Task)
        .options(
            selectinload(Task.collaborator_links),
            selectinload(Task.owner),
            selectinload(Task.project),
        )
        .order_by(Task.sort_order, Task.id)
    )
    stmt = apply_task_visibility(stmt, viewer)
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    if owner_id is not None:
        stmt = stmt.where(Task.owner_id == owner_id)
    if participant_id is not None:
        stmt = stmt.where(
            or_(
                Task.owner_id == participant_id,
                Task.id.in_(
                    select(TaskCollaborator.task_id).where(
                        TaskCollaborator.user_id == participant_id
                    )
                ),
            )
        )
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        stmt = stmt.where(Task.title.like(pattern))
    if only_mine_open:
        stmt = stmt.where(Task.status.notin_([TaskStatus.DONE, TaskStatus.CANCELLED]))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    tasks = list(db.execute(stmt.limit(limit).offset(offset)).scalars().all())
    return tasks, total


def board_columns(
    db: Session, project_id: int, viewer: User | None = None
) -> list[tuple[str, str, list[Task]]]:
    """项目看板：按状态分组返回（仅当前用户可见的任务）。"""
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")

    tasks, _ = list_tasks(db, project_id=project_id, viewer=viewer, limit=1000)
    grouped: dict[str, list[Task]] = {s.value: [] for s in TaskStatus}
    for task in tasks:
        grouped.setdefault(task.status.value, []).append(task)

    labels = {
        TaskStatus.TODO.value: "待办",
        TaskStatus.IN_PROGRESS.value: "进行中",
        TaskStatus.BLOCKED.value: "已阻塞",
        TaskStatus.DONE.value: "已完成",
        TaskStatus.CANCELLED.value: "已取消",
    }
    return [(s.value, labels[s.value], grouped.get(s.value, [])) for s in TaskStatus]


# ----------------------------------------------------------------------
# 写入
# ----------------------------------------------------------------------
def create_task(db: Session, payload: Any, actor: User) -> Task:
    """创建任务。未指定负责人时默认落到创建人头上。"""
    owner_id = payload.owner_id or actor.id
    owner = db.get(User, owner_id)
    if owner is None:
        raise AppError("负责人不存在")

    max_order = db.execute(
        select(func.coalesce(func.max(Task.sort_order), 0)).where(
            Task.project_id == payload.project_id
        )
    ).scalar_one()

    task = Task(
        project_id=payload.project_id,
        title=payload.title.strip(),
        description=payload.description,
        owner_id=owner_id,
        priority=payload.priority,
        status=getattr(payload, "status", TaskStatus.TODO),
        start_date=payload.start_date,
        due_date=payload.due_date,
        estimated_hours=payload.estimated_hours,
        checklist=[item.model_dump() for item in payload.checklist],
        tags=payload.tags,
        sort_order=max_order + 1,
        created_by=actor.id,
    )
    db.add(task)
    db.flush()

    if payload.collaborator_ids:
        set_collaborators(db, task, payload.collaborator_ids)

    # 初始状态也写一条流水，保证后续周报能识别出"本周新建的任务"
    db.add(
        TaskStatusLog(
            task_id=task.id,
            from_status=None,
            to_status=task.status,
            from_progress=None,
            to_progress=task.progress,
            operator_id=actor.id,
            remark="创建任务",
            created_at=utcnow(),
        )
    )
    db.flush()
    return task


def update_task(db: Session, task: Task, payload: Any, actor: User) -> Task:
    """更新任务字段（不含状态流转）。"""
    if payload.title is not None:
        task.title = payload.title.strip()
    if payload.description is not None:
        task.description = payload.description
    if payload.owner_id is not None:
        new_owner = db.get(User, payload.owner_id)
        if new_owner is None:
            raise AppError("负责人不存在")
        task.owner_id = payload.owner_id
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.start_date is not None:
        task.start_date = payload.start_date
    if payload.due_date is not None:
        task.due_date = payload.due_date
    if payload.estimated_hours is not None:
        task.estimated_hours = payload.estimated_hours
    if payload.actual_hours is not None:
        task.actual_hours = payload.actual_hours
    if payload.tags is not None:
        task.tags = payload.tags
    if payload.checklist is not None:
        task.checklist = [item.model_dump() for item in payload.checklist]
    if payload.collaborator_ids is not None:
        set_collaborators(db, task, payload.collaborator_ids)
    if payload.progress is not None and payload.progress != task.progress:
        change_status(
            db,
            task=task,
            actor=actor,
            to_status=task.status,
            progress=payload.progress,
            remark="进度更新",
        )
    db.flush()
    return task


def set_collaborators(db: Session, task: Task, user_ids: Iterable[int]) -> None:
    """全量覆盖协作人。"""
    wanted = {uid for uid in user_ids if uid != task.owner_id}  # 负责人不重复作为协作人
    current = {link.user_id: link for link in task.collaborator_links}

    for uid in wanted - set(current):
        db.add(TaskCollaborator(task_id=task.id, user_id=uid))
    for uid in set(current) - wanted:
        db.delete(current[uid])
    db.flush()


def change_status(
    db: Session,
    *,
    task: Task,
    actor: User,
    to_status: TaskStatus,
    progress: int | None = None,
    remark: str | None = None,
    created_at: dt.datetime | None = None,
) -> TaskStatusLog:
    """任务状态流转的唯一入口 —— 写主表 + 写流水。

    :param progress: 目标进度；省略时按状态自动推断（done→100，todo→0）
    :param created_at: 供测试/补数据指定流水时间，缺省取当前 UTC
    """
    from_status = task.status
    from_progress = task.progress

    if progress is None:
        if to_status == TaskStatus.DONE:
            progress = 100
        elif to_status == TaskStatus.TODO:
            progress = 0

    task.status = to_status
    if progress is not None:
        task.progress = int(progress)
    if to_status == TaskStatus.DONE and task.completed_at is None:
        task.completed_at = utcnow()
    if to_status != TaskStatus.DONE:
        task.completed_at = None

    log = TaskStatusLog(
        task_id=task.id,
        from_status=from_status,
        to_status=to_status,
        from_progress=from_progress,
        to_progress=task.progress,
        operator_id=actor.id,
        remark=remark,
        created_at=created_at or utcnow(),
    )
    db.add(log)
    db.flush()
    return log


def move_task(
    db: Session, task: Task, actor: User, to_status: TaskStatus, before_id: int | None
) -> Task:
    """看板拖拽：调整状态与列内位置。"""
    tasks_in_column = list(
        db.execute(
            select(Task)
            .where(Task.project_id == task.project_id, Task.status == to_status)
            .order_by(Task.sort_order, Task.id)
        )
        .scalars()
        .all()
    )
    ordered = [t for t in tasks_in_column if t.id != task.id]
    insert_at = len(ordered)
    if before_id:
        for index, item in enumerate(ordered):
            if item.id == before_id:
                insert_at = index
                break
    ordered.insert(insert_at, task)

    for index, item in enumerate(ordered):
        item.sort_order = index

    if task.status != to_status:
        # 状态变更必须走统一入口，保证流水不丢
        change_status(db, task=task, actor=actor, to_status=to_status, remark="看板拖拽")
    else:
        db.flush()
    return task


def toggle_checklist(db: Session, task: Task, index: int, done: bool) -> Task:
    """勾选/取消检查清单项。JSON 字段需整体赋值后写回。"""
    items = list(task.checklist or [])
    if index >= len(items):
        raise AppError("检查项不存在")
    items[index]["done"] = done
    task.checklist = items
    db.flush()
    return task


def recent_logs(db: Session, task_id: int, limit: int = 50) -> list[TaskStatusLog]:
    """任务的最近状态流水。"""
    return list(
        db.execute(
            select(TaskStatusLog)
            .where(TaskStatusLog.task_id == task_id)
            .order_by(TaskStatusLog.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def project_progress(
    db: Session, project_id: int, viewer: User | None = None
) -> tuple[int, int, int]:
    """项目任务概览：(总数, 已完成数, 逾期数)，按 ``viewer`` 可见范围统计。"""
    stmt = select(Task).where(Task.project_id == project_id)
    stmt = apply_task_visibility(stmt, viewer)
    tasks = list(db.execute(stmt).scalars().all())
    today = today_local()
    done = sum(1 for t in tasks if t.status == TaskStatus.DONE)
    overdue = sum(
        1
        for t in tasks
        if t.due_date
        and t.due_date < today
        and t.status not in (TaskStatus.DONE, TaskStatus.CANCELLED)
    )
    return len(tasks), done, overdue


def ensure_utcnow() -> dt.datetime:
    """暴露当前时间入口，便于测试注入。"""
    return utcnow()


def now_local() -> dt.datetime:
    return localnow()
