"""周报接口：草稿生成、提交、修订、代提交、审阅、查询。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from app.core.deps import CurrentUserDep, DbSession
from app.core.exceptions import ConflictStateError, ForbiddenError, NotFoundError
from app.models.organization import DepartmentMember, User
from app.schemas.common import MessageResponse
from app.schemas.report import (
    GenerateDraftRequest,
    ProxySubmitRequest,
    ReportItemIn,
    ReviewRequest,
    SaveDraftRequest,
    SubmitReportRequest,
)
from app.services import audit, permission, report_generator, report_service
from app.services.auth_service import normalize_week_start
from app.utils.download import content_disposition
from app.utils.week import is_week_finalized

router = APIRouter(prefix="/reports", tags=["周报"])


@router.get("/my-week-status", summary="我的本周状态")
def my_week_status(
    db: DbSession,
    user: CurrentUserDep,
    week_start: dt.date | None = None,
) -> dict[str, Any]:
    """「我的周报」卡片：截止/定版时刻、当前状态、是否还能编辑。"""
    return report_service.my_week_status(
        db, user=user, week_start=normalize_week_start(week_start)
    )


@router.post("/generate", summary="生成周报草稿")
def generate_draft(
    payload: GenerateDraftRequest,
    request: Request,
    user: CurrentUserDep,
    db: DbSession,
) -> dict[str, Any]:
    """按本周任务自动生成草稿。

    - 数据切片锁定在本自然周，补交时也不会混入下周一变更；
    - ``force=true`` 会清空旧的自动生成条目后重建，人工条目保留；
    - 周报已提交时不可再生成（需先走修订）。
    """
    ws = normalize_week_start(payload.week_start)
    if is_week_finalized(ws):
        raise ConflictStateError("本周已定版，无法自动生成草稿，请使用补交流程")

    report = report_generator.generate_draft(
        db, user=user, week_start=ws, force=payload.force
    )
    audit.record(
        db,
        action="report.generate",
        actor_id=user.id,
        target_type="weekly_report",
        target_id=report.id,
        detail={"week_start": ws.isoformat(), "force": payload.force},
        request=request,
    )
    db.commit()
    return report_service.serialize_report(db, report)


@router.get("/mine", summary="我的周报列表")
def my_reports(
    db: DbSession,
    user: CurrentUserDep,
    limit: int = Query(30, ge=1, le=200),
) -> list[dict[str, Any]]:
    rows, _ = report_service.list_reports(db, user_id=user.id, limit=limit)
    return [report_service.serialize_report(db, r) for r in rows]


@router.get("/mine/{week_start}", summary="我的指定周周报")
def my_report_of_week(
    week_start: dt.date, db: DbSession, user: CurrentUserDep
) -> dict[str, Any]:
    ws = normalize_week_start(week_start)
    report = report_service.get_user_report(db, user.id, ws)
    if report is None:
        report = report_generator.get_or_create_report(db, user=user, week_start=ws)
        db.commit()
    return report_service.serialize_report(db, report)


@router.post("/draft", summary="保存草稿")
def save_draft(
    payload: SaveDraftRequest, user: CurrentUserDep, db: DbSession
) -> dict[str, Any]:
    report = report_service.save_draft(
        db, user=user, week_start=payload.week_start, items=payload.items
    )
    db.commit()
    return report_service.serialize_report(db, report)


@router.post("/submit", summary="提交本周周报")
def submit_my_report(
    payload: SubmitReportRequest,
    request: Request,
    user: CurrentUserDep,
    db: DbSession,
) -> dict[str, Any]:
    """提交当前用户本周周报。

    首次提交按时刻判定 准时 / 迟到 / 补交；已提交过则为**修订**，版本号 +1，
    **状态不因修订而改变**。
    """
    ws = normalize_week_start(payload.week_start)
    report = report_service.get_or_create_report(db, user=user, week_start=ws)
    if report.is_locked and not payload.reason:
        raise ConflictStateError("周报已提交，修改请填写修改原因后再次提交（将生成新版本）")

    items = [ReportItemIn.model_validate(i.model_dump()) for i in payload.items]
    report = report_service.submit_report(
        db, report=report, items=items, actor=user, reason=payload.reason
    )
    audit.record(
        db,
        action="report.submit",
        actor_id=user.id,
        target_type="weekly_report",
        target_id=report.id,
        detail={"week_start": ws.isoformat(), "status": report.status.value},
        request=request,
    )
    db.commit()
    return report_service.serialize_report(db, report)


@router.post("/proxy", summary="代提交周报")
def proxy_submit(
    payload: ProxySubmitRequest,
    request: Request,
    user: CurrentUserDep,
    db: DbSession,
) -> dict[str, Any]:
    """组长/管理员代成员周报，状态记为 ``by_proxy``，独立计数。"""
    target = db.get(User, payload.user_id)
    if target is None:
        raise NotFoundError("用户不存在")
    permission.assert_can_proxy(user, target)

    ws = normalize_week_start(payload.week_start)
    report = report_service.get_or_create_report(db, user=target, week_start=ws)
    report = report_service.submit_report(
        db,
        report=report,
        items=payload.items,
        actor=user,
        proxy_reason=payload.reason,
        reason=payload.reason,
    )
    audit.record(
        db,
        action="report.proxy_submit",
        actor_id=user.id,
        target_type="weekly_report",
        target_id=report.id,
        detail={"target_user_id": target.id, "week_start": ws.isoformat()},
        request=request,
    )
    db.commit()
    return report_service.serialize_report(db, report)


@router.get("", summary="周报列表（团队/部门）")
def list_reports(
    db: DbSession,
    user: CurrentUserDep,
    week_start: dt.date | None = None,
    user_id: int | None = None,
    department_id: int | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """按权限返回可见周报。普通成员只能看到自己的。"""
    department_members: list[int] | None = None
    specific_user_id = user_id

    if department_id is not None:
        permission.assert_can_view_department(user, department_id)
        department_members = [
            row[0]
            for row in db.execute(
                select(DepartmentMember.user_id).where(
                    DepartmentMember.department_id == department_id
                )
            ).all()
        ]
    elif specific_user_id is not None and specific_user_id != user.id:
        # 查他人：必须是组长/管理员且同部门（在查库之前拦截，避免越权条件先落库）
        target = db.get(User, specific_user_id)
        if target is None:
            raise NotFoundError("用户不存在")
        permission.assert_can_view_report_of(user, target)
    elif not user.is_superuser and not user.leader_department_ids:
        specific_user_id = user.id  # 普通成员仅本人

    rows, _total = report_service.list_reports(
        db,
        week_start=normalize_week_start(week_start) if week_start else None,
        user_id=specific_user_id,
        department_members=department_members,
        status=status,
        limit=limit,
        offset=offset,
    )
    visible = permission.filter_report_ids(user, rows, db)
    return [report_service.serialize_report(db, r) for r in visible]


@router.get("/export", summary="导出我的周报")
def export_my_report(
    week_start: dt.date, user: CurrentUserDep, db: DbSession
) -> Response:
    """导出指定周的个人周报为 Markdown 文本。"""
    ws = normalize_week_start(week_start)
    report = report_service.get_user_report(db, user.id, ws)
    if report is None:
        raise NotFoundError("该周暂无周报")

    data = report_service.serialize_report(db, report)
    # 顺序与页面填写顺序一致：进展 → 总结 → 计划 → 需协调
    section_titles = {
        "progress": "一、本周工作进展",
        "done": "二、本周工作总结",
        "plan": "三、下周工作计划",
        "risk": "四、需协调与帮助",
    }
    lines = [f"# {user.full_name} 周报（{data['week_label']}）", ""]
    for key, title in section_titles.items():
        items = getattr(data["sections"], key)
        lines.append(f"## {title}")
        if items:
            lines.extend(f"- {item.content}" for item in items)
        else:
            lines.append("（无）")
        lines.append("")

    filename = f"周报-{user.username}-{ws.isoformat()}.md"
    return Response(
        content="\n".join(lines).encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.get("/{report_id}", summary="周报详情")
def read_report(
    report_id: int, db: DbSession, user: CurrentUserDep
) -> dict[str, Any]:
    report = report_service.get_report(db, report_id)
    permission.assert_can_view_report(user, report, db)
    return report_service.serialize_report(db, report)


@router.get("/{report_id}/revisions", summary="周报修订历史")
def report_revisions(
    report_id: int, db: DbSession, user: CurrentUserDep
) -> list[dict[str, Any]]:
    report = report_service.get_report(db, report_id)
    permission.assert_can_view_report(user, report, db)
    revisions = report_service.list_revisions(db, report_id)
    return [report_service.serialize_revision(db, rev) for rev in revisions]


@router.get(
    "/{report_id}/revisions/{version}", summary="查看某一版本的快照", response_model=dict
)
def report_revision_detail(
    report_id: int, version: int, db: DbSession, user: CurrentUserDep
) -> dict[str, Any]:
    revisions = report_service.list_revisions(db, report_id)
    for rev in revisions:
        if rev.version == version:
            return report_service.serialize_revision(db, rev)
    raise NotFoundError("该版本不存在")


@router.post("/{report_id}/review", response_model=MessageResponse, summary="审阅周报")
def review_report(
    report_id: int,
    payload: ReviewRequest,
    request: Request,
    user: CurrentUserDep,
    db: DbSession,
) -> MessageResponse:
    """组长审阅。``approved=false`` 表示退回，周报恢复为草稿供成员重填。"""
    report = report_service.get_report(db, report_id)
    report_service.review_report(
        db,
        report=report,
        reviewer=user,
        comment=payload.comment,
        approved=payload.approved,
    )
    audit.record(
        db,
        action="report.review",
        actor_id=user.id,
        target_type="weekly_report",
        target_id=report.id,
        detail={"approved": payload.approved, "comment": payload.comment},
        request=request,
    )
    db.commit()
    return MessageResponse(message="审阅完成", id=report.id)
