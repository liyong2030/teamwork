"""全局枚举定义。

统一使用 SQLAlchemy ``Enum(PyEnum, native_enum=False)``：
- PostgreSQL / SQLite 行为一致（底层存 VARCHAR）；
- 修改枚举不需要写原生类型迁移（仅需值校验）。
"""

from __future__ import annotations

import enum

__all__ = [
    "TaskStatus",
    "TaskPriority",
    "ProjectStatus",
    "ProjectRole",
    "ReportStatus",
    "ReportSection",
    "ItemSource",
    "LeaveStatus",
    "AuthSource",
    "NotifyChannel",
    "OPEN_TASK_STATUSES",
]


class TaskStatus(str, enum.Enum):
    """任务状态（五态）。"""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(str, enum.Enum):
    """任务优先级 P0–P3。"""

    P0 = "p0"
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"


class ProjectStatus(str, enum.Enum):
    planning = "planning"
    active = "active"
    paused = "paused"
    archived = "archived"


class ProjectRole(str, enum.Enum):
    owner = "owner"
    member = "member"
    viewer = "viewer"


class ReportStatus(str, enum.Enum):
    """周报状态（五态互斥 + 草稿）。"""

    DRAFT = "draft"
    ONTIME = "ontime"
    LATE = "late"
    MAKEUP = "makeup"
    MISSING = "missing"
    BY_PROXY = "by_proxy"


class ReportSection(str, enum.Enum):
    """周报四段结构。"""

    DONE = "done"
    PROGRESS = "progress"
    RISK = "risk"
    PLAN = "plan"


class ItemSource(str, enum.Enum):
    AUTO = "auto"
    MANUAL = "manual"


class LeaveStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class AuthSource(str, enum.Enum):
    """账号的认证来源。

    ``local`` 走本系统口令（Argon2id）；其余来源由统一身份认证系统校验，
    **本地口令登录被禁用**，且用户在 IdP 侧的唯一标识记录在 ``external_id``。

    ``saml`` 目前仅占位：SAML 只能走浏览器跳转（SP-initiated），
    与本项目采用的"后端代理校验"模式不兼容，待二期实现。
    """

    LOCAL = "local"
    CAS = "cas"
    OIDC = "oidc"
    LDAP = "ldap"
    SAML = "saml"

    @property
    def label(self) -> str:
        return _AUTH_SOURCE_LABELS[self.value]


_AUTH_SOURCE_LABELS = {
    "local": "本地口令",
    "cas": "CAS 统一身份认证",
    "oidc": "OIDC 统一身份认证",
    "ldap": "LDAP/AD 目录服务",
    "saml": "SAML 统一身份认证",
}


class NotifyChannel(str, enum.Enum):
    inbox = "inbox"
    email = "email"


# 未完成状态集合：用于"是否逾期"的派生判定
OPEN_TASK_STATUSES = {TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED}
