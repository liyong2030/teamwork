"""统计看板接口。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from app.core.deps import CurrentUserDep, DbSession
from app.models.organization import Department
from app.schemas.stats import ExportRequest
from app.services import exporter, permission, rollcall_service, stats_service
from app.services.auth_service import normalize_week_start
from app.utils.download import content_disposition

router = APIRouter(prefix="/stats", tags=["统计看板"])


def _visible_department_ids(db: DbSession, user: Any, week_start: dt.date) -> list[int]:
    """当前用户在指定周可见的部门（已发生的名册部门 ∩ 权限范围）。"""
    ws = normalize_week_start(week_start)
    dept_ids = rollcall_service.department_ids_of_week(db, ws)
    return permission.visible_department_ids(user, dept_ids)


@router.get("/overview", summary="统计概览")
def overview(
    db: DbSession,
    user: CurrentUserDep,
    week_start: dt.date | None = None,
    department_id: int | None = None,
) -> dict[str, Any]:
    """总体概览卡片数据。"""
    ws = normalize_week_start(week_start)
    rollcall_service.ensure_roll_call(db, ws)
    if department_id is not None:
        permission.assert_can_view_department(user, department_id)
        dept_ids = [department_id]
    else:
        dept_ids = _visible_department_ids(db, user, ws)
    return stats_service.overview(db, week_start=ws, department_ids=dept_ids)


@router.get("/departments", summary="部门横向对比")
def by_department(
    db: DbSession,
    user: CurrentUserDep,
    week_start: dt.date | None = None,
) -> list[dict[str, Any]]:
    ws = normalize_week_start(week_start)
    rollcall_service.ensure_roll_call(db, ws)
    dept_ids = _visible_department_ids(db, user, ws)
    return stats_service.by_department(db, week_start=ws, department_ids=dept_ids)


@router.get("/trend", summary="近 N 周趋势")
def trend(
    db: DbSession,
    user: CurrentUserDep,
    weeks: int = Query(12, ge=1, le=52),
    department_id: int | None = None,
) -> list[dict[str, Any]]:
    dept_ids = None
    if department_id is not None:
        permission.assert_can_view_department(user, department_id)
        dept_ids = [department_id]
    elif not user.is_superuser:
        dept_ids = list(set(user.department_ids) | set(user.leader_department_ids)) or None
    return stats_service.trend(db, weeks=weeks, department_ids=dept_ids)


@router.get("/people", summary="个人明细")
def people(
    db: DbSession,
    user: CurrentUserDep,
    week_start: dt.date | None = None,
    department_id: int | None = None,
) -> list[dict[str, Any]]:
    """逐个成员的提交状态明细，含连续未交周数。"""
    ws = normalize_week_start(week_start)
    rollcall_service.ensure_roll_call(db, ws)
    if department_id is not None:
        permission.assert_can_view_department(user, department_id)
        return stats_service.people(db, week_start=ws, department_id=department_id)

    dept_ids = _visible_department_ids(db, user, ws)
    rows: list[dict[str, Any]] = []
    for dept_id in dept_ids:
        rows.extend(stats_service.people(db, week_start=ws, department_id=dept_id))
    return rows


@router.get("/snapshots", summary="定版快照")
def snapshots(
    db: DbSession,
    user: CurrentUserDep,
    week_start: dt.date | None = None,
    department_id: int | None = None,
) -> list[dict[str, Any]]:
    """已定版（冻结）的历史统计结果。"""
    ws = normalize_week_start(week_start)
    if department_id is not None:
        permission.assert_can_view_department(user, department_id)
    return stats_service.snapshots(db, ws, department_id)


@router.post("/export", summary="导出统计结果")
def export_stats(payload: ExportRequest, db: DbSession, user: CurrentUserDep) -> Response:
    """导出 Excel / CSV，口径与看板完全一致。"""
    ws = normalize_week_start(payload.week_start)
    rollcall_service.ensure_roll_call(db, ws)

    if payload.department_id is not None:
        permission.assert_can_view_department(user, payload.department_id)
        dept_ids = [payload.department_id]
    elif user.is_superuser:
        dept_ids = None
    else:
        dept_ids = list(set(user.department_ids) | set(user.leader_department_ids))

    content, filename, media_type = exporter.export_report(
        db,
        week_start=ws,
        department_id=payload.department_id,
        department_ids=dept_ids,
        fmt=payload.fmt,
        dimension="department" if payload.department_id is None else "people",
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.get("/my-history", summary="我的历史提交记录")
def my_history(
    db: DbSession,
    user: CurrentUserDep,
    weeks: int = Query(12, ge=1, le=52),
) -> list[dict[str, Any]]:
    """当前用户近 N 周的提交状态。"""
    from app.services import report_service
    from app.utils.week import recent_week_starts, week_label

    result = []
    for ws in recent_week_starts(weeks):
        report = report_service.get_user_report(db, user.id, ws)
        if report is None:
            from app.models.enums import ReportStatus

            status = ReportStatus.MISSING.value
            submitted_at = None
            valid = False
            report_id = None
        else:
            status = report.status.value
            submitted_at = report.submitted_at
            valid = report.is_valid
            report_id = report.id
        result.append(
            {
                "week_start": ws,
                "week_label": week_label(ws),
                "status": status,
                "status_label": report_service.STATUS_LABELS.get(status, status),
                "submitted_at": submitted_at,
                "is_valid": valid,
                "report_id": report_id,
            }
        )
    result.reverse()
    return result


@router.get("/departments/options", summary="可选部门列表")
def department_options(db: DbSession, user: CurrentUserDep) -> list[dict[str, Any]]:
    rows = db.execute(select(Department).order_by(Department.sort_order)).scalars().all()
    visible = permission.visible_department_ids(user, [d.id for d in rows])
    return [{"id": d.id, "name": d.name} for d in rows if d.id in visible and d.is_active]
