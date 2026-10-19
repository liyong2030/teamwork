"""系统域模型：审计日志、站内通知、系统配置。"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import NotifyChannel


class AuditLog(Base):
    """审计日志：登录、改密、任务状态变更、周报提交/修订/定版、权限变更全留痕。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        index=True,
        default=lambda: dt.datetime.now(tz=dt.timezone.utc).replace(tzinfo=None),
    )

    actor: Mapped[Optional["User"]] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog {self.action} by {self.actor_id}>"


class Notification(Base):
    """站内通知。"""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[NotifyChannel] = mapped_column(
        Enum(NotifyChannel, native_enum=False, length=16),
        default=NotifyChannel.inbox,
        nullable=False,
    )
    link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        index=True,
        default=lambda: dt.datetime.now(tz=dt.timezone.utc).replace(tzinfo=None),
    )

    user: Mapped["User"] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Notification user={self.user_id} {self.title}>"


class SystemSetting(Base):
    """系统配置项（key-value，值为 JSON）。"""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    value: Mapped[dict[str, Any] | list[Any] | str | int | bool] = mapped_column(
        JSON, nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=lambda: dt.datetime.now(tz=dt.timezone.utc).replace(tzinfo=None),
        onupdate=lambda: dt.datetime.now(tz=dt.timezone.utc).replace(tzinfo=None),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SystemSetting {self.key}>"
