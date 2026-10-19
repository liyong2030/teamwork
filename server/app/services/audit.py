"""审计日志服务 —— 所有关键动作统一记录，便于事后追溯。

约定 action 命名：<域>.<对象>.<动作>，例如 ``task.status.change``、
``report.submit``、``user.password.reset``、``report.finalize``。
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.system import AuditLog
from app.utils.week import utcnow


def record(
    db: Session,
    *,
    action: str,
    actor_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    detail: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    """写入一条审计记录。

    :param actor_id: 操作人；系统定时任务传 None
    :param request: 传入时自动提取 IP 与 User-Agent
    """
    ip = None
    ua = None
    if request is not None:
        ip = request.client.host if request.client else None
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        ua = request.headers.get("user-agent")

    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=ip,
        user_agent=(ua or "")[:255] or None,
        created_at=utcnow(),
    )
    db.add(entry)
    db.flush()
    return entry


def record_batch(
    db: Session,
    *,
    action: str,
    target_ids: list[int],
    actor_id: int | None = None,
    target_type: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """批量写入（用于定时任务的大批量操作，避免逐条 flush 拖慢性能）。"""
    if not target_ids:
        return
    db.add_all(
        [
            AuditLog(
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=tid,
                detail=detail,
                created_at=utcnow(),
            )
            for tid in target_ids
        ]
    )
