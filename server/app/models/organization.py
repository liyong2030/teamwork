"""组织域模型：部门、用户、部门成员关系、请假。"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import AuthSource, LeaveStatus, _AUTH_SOURCE_LABELS


class Department(Base, TimestampMixin):
    """部门 / 小组。"""

    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("name", "parent_id", name="uq_departments_name_parent"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    leader_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    memberships: Mapped[list["DepartmentMember"]] = relationship(
        back_populates="department", cascade="all, delete-orphan", lazy="selectin"
    )
    projects: Mapped[list["Project"]] = relationship(back_populates="department")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Department {self.id}:{self.name}>"


class User(Base, TimestampMixin):
    """用户。

    禁止物理删除，离职仅置 ``is_active = False``，保留全部历史数据。
    """

    __tablename__ = "users"
    __table_args__ = (
        # 同一 IdP 内的用户标识唯一；本地账号 external_id 为 NULL，不受此约束影响
        UniqueConstraint("auth_source", "external_id", name="uq_users_auth_source_external_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # SSO 账号没有本地口令（为 None），本地登录入口必须拒绝
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ---- 统一身份认证 ----
    auth_source: Mapped[str] = mapped_column(
        String(16), default=AuthSource.LOCAL.value, nullable=False, index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    password_changed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    last_login_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    memberships: Mapped[list["DepartmentMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    owned_projects: Mapped[list["Project"]] = relationship(
        back_populates="owner", foreign_keys="Project.owner_id"
    )
    owned_tasks: Mapped[list["Task"]] = relationship(
        back_populates="owner", foreign_keys="Task.owner_id"
    )
    leave_requests: Mapped[list["LeaveRequest"]] = relationship(
        back_populates="user", foreign_keys="LeaveRequest.user_id"
    )
    weekly_reports: Mapped[list["WeeklyReport"]] = relationship(
        back_populates="user", foreign_keys="WeeklyReport.user_id"
    )

    @property
    def is_sso(self) -> bool:
        """是否统一身份认证账号（此类账号不能用本地口令登录）。"""
        return self.auth_source != AuthSource.LOCAL.value

    @property
    def auth_source_label(self) -> str:
        return _AUTH_SOURCE_LABELS.get(self.auth_source, self.auth_source)

    @property
    def department_ids(self) -> list[int]:
        """所属部门 ID 列表。"""
        return [m.department_id for m in self.memberships]

    @property
    def leader_department_ids(self) -> list[int]:
        """担任组长的部门 ID 列表。"""
        return [m.department_id for m in self.memberships if m.is_leader]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.id}:{self.username}>"


class DepartmentMember(Base, TimestampMixin):
    """部门成员关联（支持一人多部门 / 跨部门虚拟组）。"""

    __tablename__ = "department_members"
    __table_args__ = (
        UniqueConstraint("user_id", "department_id", name="uq_department_members_user_dept"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_leader: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    joined_at: Mapped[dt.date] = mapped_column(Date, nullable=False, default=dt.date.today)

    user: Mapped["User"] = relationship(back_populates="memberships")
    department: Mapped["Department"] = relationship(back_populates="memberships")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DepartmentMember dept={self.department_id} user={self.user_id}>"


class LeaveRequest(Base, TimestampMixin):
    """请假申请。

    仅 ``status = approved`` 的记录参与"应提交人数"扣减。
    """

    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[LeaveStatus] = mapped_column(
        Enum(LeaveStatus, native_enum=False, length=16),
        default=LeaveStatus.pending,
        nullable=False,
        index=True,
    )
    approver_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    user: Mapped["User"] = relationship(
        back_populates="leave_requests", foreign_keys=[user_id], lazy="selectin"
    )
    approver: Mapped[Optional["User"]] = relationship(foreign_keys=[approver_id], lazy="selectin")

    def covers_date(self, day: dt.date) -> bool:
        """判断该请假是否覆盖指定日期。"""
        return self.start_date <= day <= self.end_date

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LeaveRequest {self.user_id} {self.start_date}~{self.end_date}>"
