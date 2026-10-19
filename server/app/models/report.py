"""周报域模型：点名名册、周报、条目、修订留痕、定版统计快照。"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import ItemSource, ReportSection, ReportStatus


class WeeklyRollCall(Base, TimestampMixin):
    """周报点名名册 —— 「应提交人数」的不可变依据。

    每周一 00:00 由定时任务生成。生成后即使人员调岗/离职，本周分母保持不变。
    """

    __tablename__ = "weekly_roll_calls"
    __table_args__ = (
        UniqueConstraint(
            "week_start", "user_id", "department_id", name="uq_roll_calls_week_user_dept"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    week_start: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    week_no: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    exempt_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    exempt_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(lazy="selectin")
    department: Mapped["Department"] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RollCall {self.week_start} user={self.user_id}>"


class WeeklyReport(Base, TimestampMixin):
    """周报主表。一人一周一份（唯一约束 user_id + week_start）。"""

    __tablename__ = "weekly_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "week_start", name="uq_weekly_reports_user_week"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    week_start: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    week_no: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, native_enum=False, length=16),
        default=ReportStatus.DRAFT,
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    submitted_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    last_edited_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    submitted_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    proxy_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    reviewed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    review_comment: Mapped[str | None] = mapped_column(String(500), nullable=True)

    is_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    invalid_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(
        back_populates="weekly_reports", foreign_keys=[user_id], lazy="selectin"
    )
    submitted_by: Mapped[Optional["User"]] = relationship(foreign_keys=[submitted_by_id])
    items: Mapped[list["WeeklyReportItem"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="WeeklyReportItem.sort_order",
        lazy="selectin",
    )
    revisions: Mapped[list["WeeklyReportRevision"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )

    @property
    def is_locked(self) -> bool:
        """是否已提交（提交后内容锁定，修改需走修订留痕）。"""
        return self.submitted_at is not None

    def section_items(self, section: ReportSection) -> list["WeeklyReportItem"]:
        """取指定段落的条目。"""
        return [item for item in self.items if item.section == section]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<WeeklyReport user={self.user_id} week={self.week_start}>"


class WeeklyReportItem(Base, TimestampMixin):
    """周报条目（四段结构下的一条内容），可关联任务。"""

    __tablename__ = "weekly_report_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("weekly_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section: Mapped[ReportSection] = mapped_column(
        Enum(ReportSection, native_enum=False, length=16), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[ItemSource] = mapped_column(
        Enum(ItemSource, native_enum=False, length=16),
        default=ItemSource.MANUAL,
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    report: Mapped["WeeklyReport"] = relationship(back_populates="items")
    task: Mapped[Optional["Task"]] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ReportItem report={self.report_id} section={self.section.value}>"


class WeeklyReportRevision(Base):
    """周报修订快照（每次提交后修改留痕，版本号递增）。"""

    __tablename__ = "weekly_report_revisions"
    __table_args__ = (
        UniqueConstraint("report_id", "version", name="uq_report_revisions_report_version"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("weekly_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    editor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=lambda: dt.datetime.now(tz=dt.timezone.utc).replace(tzinfo=None),
    )

    report: Mapped["WeeklyReport"] = relationship(back_populates="revisions")
    editor: Mapped["User"] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Revision report={self.report_id} v{self.version}>"


class WeeklyStatSnapshot(Base):
    """周报定版统计快照。

    周一 09:30 定时任务生成的**冻结结果**：历史数据永不被后续补交回填修改。
    """

    __tablename__ = "weekly_stat_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "week_start", "department_id", name="uq_stat_snapshots_week_dept"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    week_start: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True
    )

    required_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    submitted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ontime_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    late_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    makeup_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    by_proxy_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    finalized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    computed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=lambda: dt.datetime.now(tz=dt.timezone.utc).replace(tzinfo=None),
    )

    department: Mapped["Department"] = relationship(lazy="selectin")

    @property
    def ontime_rate(self) -> float:
        """准时率 = 准时数 / 应提交数（分母固定，不因补交变化）。"""
        if self.required_count <= 0:
            return 0.0
        return round(self.ontime_count / self.required_count * 100, 2)

    @property
    def submit_rate(self) -> float:
        """提交率 = (准时 + 迟到 + 补交 + 代交) / 应提交数。"""
        if self.required_count <= 0:
            return 0.0
        return round(self.submitted_count / self.required_count * 100, 2)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StatSnapshot week={self.week_start} dept={self.department_id}>"
