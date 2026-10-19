"""模型包：集中导入所有模型，保证 ``Base.metadata`` 完整，供 Alembic 与建表使用。

注意：本模块必须被 ``app.models`` 下所有文件导入后再被外部引用，
避免出现 "Table xxx is not defined in metadata" 的迁移问题。
"""

from __future__ import annotations

from app.db.base import Base
from app.models.enums import (
    ItemSource,
    LeaveStatus,
    NotifyChannel,
    ProjectRole,
    ProjectStatus,
    ReportSection,
    ReportStatus,
    TaskPriority,
    TaskStatus,
)
from app.models.organization import Department, DepartmentMember, LeaveRequest, User
from app.models.project import (
    Project,
    ProjectMember,
    Task,
    TaskCollaborator,
    TaskStatusLog,
)
from app.models.report import (
    WeeklyReport,
    WeeklyReportItem,
    WeeklyReportRevision,
    WeeklyRollCall,
    WeeklyStatSnapshot,
)
from app.models.system import AuditLog, Notification, SystemSetting

__all__ = [
    # enums
    "ItemSource",
    "LeaveStatus",
    "NotifyChannel",
    "ProjectRole",
    "ProjectStatus",
    "ReportSection",
    "ReportStatus",
    "TaskPriority",
    "TaskStatus",
    # organization
    "Department",
    "DepartmentMember",
    "LeaveRequest",
    "User",
    # project
    "Project",
    "ProjectMember",
    "Task",
    "TaskCollaborator",
    "TaskStatusLog",
    # report
    "WeeklyReport",
    "WeeklyReportItem",
    "WeeklyReportRevision",
    "WeeklyRollCall",
    "WeeklyStatSnapshot",
    # system
    "AuditLog",
    "Notification",
    "SystemSetting",
    # base
    "Base",
]
