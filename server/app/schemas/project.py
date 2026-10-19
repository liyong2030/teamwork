"""项目与任务相关 Schema。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TaskPriority, TaskStatus
from app.schemas.common import ORMModel


class ProjectBase(BaseModel):
    name: str
    code: str | None = None
    """项目编号。**留空则由后端自动生成**（``PRJ-2026-001``）。"""

    description: str | None = None
    department_id: int | None = None
    owner_id: int | None = None
    status: str = "active"
    start_date: dt.date | None = None
    end_date: dt.date | None = None


class ProjectCreate(ProjectBase):
    member_ids: list[int] = []


class ProjectUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    description: str | None = None
    department_id: int | None = None
    owner_id: int | None = None
    status: str | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    member_ids: list[int] | None = None


class ProjectOut(ORMModel):
    id: int
    name: str
    code: str
    description: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    owner_id: int | None = None
    owner_name: str | None = None
    status: str
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    sort_order: int = 0
    created_at: dt.datetime
    task_total: int = 0
    task_done: int = 0
    overdue_count: int = 0
    member_ids: list[int] = []

    model_config = ConfigDict(from_attributes=True)


class ChecklistItem(BaseModel):
    text: str
    done: bool = False


class TaskBase(BaseModel):
    title: str
    project_id: int
    description: str | None = None
    owner_id: int | None = None
    collaborator_ids: list[int] = []
    priority: TaskPriority = TaskPriority.P2
    start_date: dt.date | None = None
    due_date: dt.date | None = None
    estimated_hours: float | None = None
    tags: list[str] = []
    checklist: list[ChecklistItem] = []

    @field_validator("due_date")
    @classmethod
    def _check_due(cls, v: dt.date | None, info) -> dt.date | None:
        start = info.data.get("start_date")
        if v and start and v < start:
            raise ValueError("截止日不能早于开始日")
        return v


class TaskCreate(TaskBase):
    status: TaskStatus = TaskStatus.TODO


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    owner_id: int | None = None
    collaborator_ids: list[int] | None = None
    priority: TaskPriority | None = None
    start_date: dt.date | None = None
    due_date: dt.date | None = None
    progress: int | None = Field(None, ge=0, le=100)
    estimated_hours: float | None = None
    actual_hours: float | None = None
    tags: list[str] | None = None
    checklist: list[ChecklistItem] | None = None


class TaskStatusChangeRequest(BaseModel):
    """任务状态变更。所有变更都写 ``task_status_logs`` 流水。"""

    to_status: TaskStatus
    progress: int | None = Field(None, ge=0, le=100)
    remark: str | None = None


class TaskMoveRequest(BaseModel):
    """看板拖拽：同时调整状态与列内排序。"""

    to_status: TaskStatus
    before_id: int | None = None  # 插入到该任务之前；为空表示放到列末尾


class ChecklistToggleRequest(BaseModel):
    index: int = Field(ge=0)
    done: bool


class TaskOut(ORMModel):
    id: int
    project_id: int
    project_name: str | None = None
    project_code: str | None = None
    title: str
    description: str | None = None
    owner_id: int | None = None
    owner_name: str | None = None
    collaborator_ids: list[int] = []
    priority: str
    status: str
    start_date: dt.date | None = None
    due_date: dt.date | None = None
    progress: int = 0
    estimated_hours: float | None = None
    actual_hours: float | None = None
    checklist: list[dict[str, Any]] = []
    tags: list[str] = []
    sort_order: int = 0
    is_overdue: bool = False
    completed_at: dt.datetime | None = None
    created_at: dt.datetime
    updated_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


class BoardColumn(ORMModel):
    """看板的一列。"""

    status: str
    title: str
    tasks: list[TaskOut] = []


class TaskStatusLogOut(ORMModel):
    id: int
    task_id: int
    from_status: str | None = None
    to_status: str
    from_progress: int | None = None
    to_progress: int | None = None
    operator_id: int
    operator_name: str | None = None
    remark: str | None = None
    created_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)
