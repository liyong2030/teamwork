"""系统接口：通知、审计日志、系统配置、定时任务手动触发。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.config import settings
from app.core.deps import CurrentUserDep, DbSession, SuperUserDep
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.models.system import AuditLog, SystemSetting
from app.schemas.common import MessageResponse
from app.schemas.auth import EmailTestRequest
from app.services import notifier, sso_service
from app.tasks import jobs
from app.utils.week import utcnow

router = APIRouter(prefix="/system", tags=["系统"])
logger = get_logger(__name__)


@router.get("/notifications", summary="我的通知")
def my_notifications(
    db: DbSession,
    user: CurrentUserDep,
    unread_only: bool = False,
    limit: int = Query(30, ge=1, le=200),
) -> list[dict[str, Any]]:
    from sqlalchemy import select

    stmt = _notifications_stmt(user.id, unread_only, limit)
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": n.id,
            "title": n.title,
            "content": n.content,
            "channel": n.channel.value,
            "link": n.link,
            "is_read": n.is_read,
            "created_at": n.created_at,
        }
        for n in rows
    ]


def _notifications_stmt(user_id: int, unread_only: bool, limit: int):
    """构造通知查询语句。"""
    from sqlalchemy import select

    from app.models.system import Notification

    stmt = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return stmt


@router.get("/notifications/unread-count", summary="未读通知数")
def unread_count(db: DbSession, user: CurrentUserDep) -> dict[str, int]:
    from sqlalchemy import func, select

    from app.models.system import Notification

    count = db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.is_read.is_(False)
        )
    ).scalar_one()
    return {"count": count}


@router.post("/notifications/{notification_id}/read", response_model=MessageResponse)
def mark_read(
    notification_id: int, user: CurrentUserDep, db: DbSession
) -> MessageResponse:
    from sqlalchemy import select

    from app.models.system import Notification

    from app.core.exceptions import NotFoundError

    notification = db.execute(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    ).scalar_one_or_none()
    if notification is None:
        raise NotFoundError("通知不存在")
    notification.is_read = True
    db.commit()
    return MessageResponse(message="已标记为已读")


@router.get("/settings", summary="系统配置")
def read_settings(db: DbSession, _admin: SuperUserDep) -> list[dict[str, Any]]:
    rows = db.execute(select(SystemSetting).order_by(SystemSetting.key)).scalars().all()
    return [
        {"key": s.key, "value": s.value, "description": s.description, "updated_at": s.updated_at}
        for s in rows
    ]


@router.put("/settings/{key}", response_model=MessageResponse, summary="更新配置")
def update_setting(
    key: str,
    payload: dict[str, Any],
    request: Request,
    admin: SuperUserDep,
    db: DbSession,
) -> MessageResponse:
    """更新单个配置项，入参形如 ``{"value": ...}``。"""
    if "value" not in payload:
        raise AppError("请求体需包含 value 字段")

    setting = db.execute(
        _setting_stmt(key)
    ).scalar_one_or_none()
    if setting is None:
        setting = SystemSetting(key=key, value=payload["value"])
        db.add(setting)
    else:
        setting.value = payload["value"]
    setting.updated_by = admin.id
    setting.updated_at = utcnow()

    from app.services import audit

    audit.record(
        db,
        action="system.setting.update",
        actor_id=admin.id,
        target_type="system_setting",
        detail={"key": key, "value": payload["value"]},
        request=request,
    )
    db.commit()
    return MessageResponse(message="配置已更新")


def _setting_stmt(key: str):
    from sqlalchemy import select

    return select(SystemSetting).where(SystemSetting.key == key)


@router.get("/audit-logs", summary="审计日志")
def audit_logs(
    db: DbSession,
    _admin: SuperUserDep,
    action: str | None = None,
    actor_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    from sqlalchemy import select

    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)

    rows = db.execute(stmt.limit(limit).offset(offset)).scalars().all()
    return [
        {
            "id": log.id,
            "actor_id": log.actor_id,
            "actor_name": log.actor.full_name if log.actor else None,
            "action": log.action,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "detail": log.detail,
            "ip_address": log.ip_address,
            "created_at": log.created_at,
        }
        for log in rows
    ]


@router.post("/jobs/{job_id}/run", response_model=MessageResponse, summary="手动触发定时任务")
def run_job(job_id: str, request: Request, _admin: SuperUserDep, db: DbSession) -> MessageResponse:
    """排障用：手动跑一次提醒/定版任务。

    可选 job_id：``roll_call`` / ``finalize`` / ``remind_fri_1000`` /
    ``remind_fri_1700`` / ``remind_sun_2000`` / ``remind_mon_0830``
    """
    from sqlalchemy import select

    valid = {
        "roll_call": lambda: jobs.job_generate_roll_call(),
        "finalize": jobs.job_finalize,
        "remind_fri_1000": lambda: jobs.job_remind("fri_1000"),
        "remind_fri_1700": lambda: jobs.job_remind("fri_1700"),
        "remind_sun_2000": lambda: jobs.job_remind("sun_2000"),
        "remind_mon_0830": lambda: jobs.job_remind("mon_0830"),
    }
    func = valid.get(job_id)
    if func is None:
        raise AppError(f"未知任务：{job_id}")

    func()
    from app.services import audit

    audit.record(
        db,
        action="system.job.run",
        actor_id=_admin.id,
        target_type="job",
        detail={"job_id": job_id},
        request=request,
    )
    db.commit()
    return MessageResponse(message=f"任务 {job_id} 已执行")


@router.get("/sso/status", summary="统一身份认证自检")
def sso_status(_admin: SuperUserDep) -> dict[str, Any]:
    """管理员排查 IdP 配置：连通性、生效中的协议与非敏感配置项。

    **不返回任何密钥**，也不发起真实认证（避免把管理员口令送到 IdP）。
    """
    return sso_service.status_for_admin()


@router.post("/email/test", response_model=MessageResponse, summary="邮件连通性测试")
def test_email(
    payload: EmailTestRequest, admin: SuperUserDep, db: DbSession
) -> MessageResponse:
    """向指定邮箱发送一封测试邮件，用于验证 SMTP 配置是否正确。"""
    if not settings.email_enabled:
        raise AppError("邮件服务未启用（EMAIL_ENABLED=false）")
    try:
        notifier.send_email(
            payload.to_email,
            "邮件服务连通性测试",
            "这是一封来自团队协作管理系统的测试邮件。收到即代表 SMTP 配置正确。",
        )
    except RuntimeError as exc:
        raise AppError(str(exc)) from exc
    except Exception as exc:  # SMTP 抛的异常类型较杂，统一转换
        logger.warning("邮件测试失败: %s", exc)
        raise AppError(f"邮件发送失败：{exc}") from exc
    return MessageResponse(message=f"测试邮件已发送至 {payload.to_email}")


@router.get("/info", summary="系统信息")
def system_info(user: CurrentUserDep) -> dict[str, Any]:
    """返回前端需要的运行期信息（不含任何密钥）。"""
    return {
        "app_name": settings.app_name,
        "env": settings.app_env,
        "timezone": settings.tz,
        "deadline": f"周{settings.report_deadline_weekday} {settings.report_deadline_time}",
        "finalize": f"下周{settings.report_finalize_weekday} {settings.report_finalize_time}",
        "valid_min_chars": settings.report_valid_min_chars,
        "scheduler_enabled": settings.scheduler_enabled,
        "email_enabled": settings.email_enabled,
    }
