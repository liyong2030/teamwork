"""项目域模型：项目、任务、协作人、状态流水。"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import (
    OPEN_TASK_STATUSES,
    ProjectRole,
    ProjectStatus,
    TaskPriority,
    TaskStatus,
)


class Project(Base, TimestampMixin):
    """项目。"""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, native_enum=False, length=16),
        default=ProjectStatus.active,
        nullable=False,
        index=True,
    )
    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    department: Mapped[Optional["Department"]] = relationship(
        back_populates="projects", lazy="selectin"
    )
    owner: Mapped["User"] = relationship(
        back_populates="owned_projects", foreign_keys=[owner_id], lazy="selectin"
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Project {self.id}:{self.code}>"


class ProjectMember(Base, TimestampMixin):
    """项目成员。"""

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[ProjectRole] = mapped_column(
        Enum(ProjectRole, native_enum=False, length=16),
        default=ProjectRole.member,
        nullable=False,
    )

    project: Mapped["Project"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ProjectMember project={self.project_id} user={self.user_id}>"


class Task(Base, TimestampMixin):
    """任务（两级结构中的叶子节点，子任务以 ``checklist`` JSON 承载）。"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, native_enum=False, length=8),
        default=TaskPriority.P2,
        nullable=False,
        index=True,
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False, length=16),
        default=TaskStatus.TODO,
        nullable=False,
        index=True,
    )
    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)
    progress: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    estimated_hours: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    actual_hours: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="tasks", lazy="selectin")
    owner: Mapped["User"] = relationship(
        back_populates="owned_tasks", foreign_keys=[owner_id], lazy="selectin"
    )
    collaborator_links: Mapped[list["TaskCollaborator"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", lazy="selectin"
    )
    status_logs: Mapped[list["TaskStatusLog"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskStatusLog.created_at",
    )

    @property
    def collaborator_ids(self) -> list[int]:
        """协作人 ID 列表。"""
        return [link.user_id for link in self.collaborator_links]

    @property
    def participant_ids(self) -> list[int]:
        """全部参与者（负责人 + 协作人），周报草稿按此分组。"""
        ids = {self.owner_id}
        ids.update(self.collaborator_ids)
        return sorted(ids)

    @property
    def is_overdue(self) -> bool:
        """派生状态：已过截止日且未完成/未取消。**不入库**，由应用层计算。"""
        if self.due_date is None:
            return False
        if self.status not in OPEN_TASK_STATUSES:
            return False
        return self.due_date < dt.date.today()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Task {self.id}:{self.title}>"


class TaskCollaborator(Base, TimestampMixin):
    """任务协作人关联。"""

    __tablename__ = "task_collaborators"
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_task_collaborators_task_user"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    task: Mapped["Task"] = relationship(back_populates="collaborator_links")
    user: Mapped["User"] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TaskCollaborator task={self.task_id} user={self.user_id}>"


class TaskStatusLog(Base):
    """任务状态变更流水 —— 周报自动草稿的**唯一数据源**。

    约束：任何状态或进度变更都必须通过 ``services/task_service.change_status``
    写入本表，禁止绕过服务层直接修改 ``tasks.status``。
    """

    __tablename__ = "task_status_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[TaskStatus | None] = mapped_column(
        Enum(TaskStatus, native_enum=False, length=16), nullable=True
    )
    to_status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False, length=16), nullable=False, index=True
    )
    from_progress: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    to_progress: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    operator_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        index=True,
        default=lambda: dt.datetime.now(tz=dt.timezone.utc).replace(tzinfo=None),
    )

    task: Mapped["Task"] = relationship(back_populates="status_logs")
    operator: Mapped["User"] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TaskStatusLog task={self.task_id} -> {self.to_status.value}>"
