"""周报服务：草稿保存、提交、修订留痕、代提交、审阅、序列化。

状态口径（《需求规格说明书》6.2）：
- ``ONTIME`` 准时  ：提交时刻 ≤ 周五 18:00
- ``LATE`` 迟到    ：周五 18:00 之后 ~ 下周一 09:30
- ``MISSING`` 未交 ：定版时仍无提交记录（由定时任务写入）
- ``MAKEUP`` 补交  ：定版之后才提交，**独立计数，不回填 missing**
- ``BY_PROXY`` 代交：由组长/管理员代提交，优先级最高
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import ConflictStateError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.models.enums import ItemSource, ReportSection, ReportStatus
from app.models.organization import User
from app.models.report import WeeklyReport, WeeklyReportItem, WeeklyReportRevision
from app.schemas.report import ReportItemIn, ReportSections
from app.services import permission
from app.services.report_generator import get_or_create_report, normalize_week_start
from app.utils.week import (
    classify_submission,
    deadline_of,
    finalize_of,
    is_week_finalized,
    localnow,
    to_local,
    utcnow,
    week_label,
)

logger = get_logger(__name__)

STATUS_LABELS = {
    ReportStatus.DRAFT.value: "草稿",
    ReportStatus.ONTIME.value: "准时提交",
    ReportStatus.LATE.value: "迟到提交",
    ReportStatus.MAKEUP.value: "补交",
    ReportStatus.MISSING.value: "未提交",
    ReportStatus.BY_PROXY.value: "代提交",
}

SUBMITTED_STATUSES = {
    ReportStatus.ONTIME,
    ReportStatus.LATE,
    ReportStatus.MAKEUP,
    ReportStatus.BY_PROXY,
}


# ----------------------------------------------------------------------
# 读取
# ----------------------------------------------------------------------
def get_report(db: Session, report_id: int) -> WeeklyReport:
    report = db.execute(
        select(WeeklyReport)
        .options(selectinload(WeeklyReport.items), selectinload(WeeklyReport.user))
        .where(WeeklyReport.id == report_id)
    ).scalar_one_or_none()
    if report is None:
        raise NotFoundError("周报不存在")
    return report


def get_user_report(db: Session, user_id: int, week_start: dt.date) -> WeeklyReport | None:
    return db.execute(
        select(WeeklyReport)
        .options(selectinload(WeeklyReport.items))
        .where(WeeklyReport.user_id == user_id, WeeklyReport.week_start == week_start)
    ).scalar_one_or_none()


def list_reports(
    db: Session,
    *,
    week_start: dt.date | None = None,
    user_id: int | None = None,
    department_members: list[int] | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[WeeklyReport], int]:
    """周报列表（调用方需已在外部完成权限过滤）。"""
    stmt = (
        select(WeeklyReport)
        .options(selectinload(WeeklyReport.items), selectinload(WeeklyReport.user))
        .order_by(WeeklyReport.week_start.desc(), WeeklyReport.id.desc())
    )
    if week_start is not None:
        stmt = stmt.where(WeeklyReport.week_start == week_start)
    if user_id is not None:
        stmt = stmt.where(WeeklyReport.user_id == user_id)
    if department_members is not None:
        stmt = stmt.where(WeeklyReport.user_id.in_(department_members))
    if status:
        stmt = stmt.where(WeeklyReport.status == status)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = list(db.execute(stmt.limit(limit).offset(offset)).scalars().all())
    return rows, total


# ----------------------------------------------------------------------
# 写入
# ----------------------------------------------------------------------
def _replace_items(db: Session, report: WeeklyReport, items: Iterable[ReportItemIn]) -> None:
    """整段替换周报条目（保持段内顺序）。"""
    for old in list(report.items):
        db.delete(old)
    db.flush()

    counter: dict[str, int] = {}
    new_items = []
    for item in items:
        content = (item.content or "").strip()
        if not content:
            continue
        section = ReportSection(item.section)
        order = counter.get(section.value, 0)
        counter[section.value] = order + 1
        new_items.append(
            WeeklyReportItem(
                report_id=report.id,
                section=section,
                content=content,
                task_id=item.task_id,
                source=ItemSource.MANUAL if item.source == "manual" else ItemSource.AUTO,
                sort_order=order,
            )
        )
    if new_items:
        db.add_all(new_items)
    db.flush()


def save_draft(
    db: Session, *, user: User, week_start: dt.date | None, items: list[ReportItemIn]
) -> WeeklyReport:
    """保存草稿。

    未提交前可反复保存，不写版本；**已提交但未定版**时同样允许暂存改动，
    但必须写一条修订留痕并保留已生效的提交状态（准时/迟到不因改动而改变），
    后续再点「提交周报」即形成正式修订版本。

    唯一拒绝的场景是**本周已定版**：定版意味着统计口径冻结，任何改动都会污染历史报表。
    """
    ws = normalize_week_start(week_start)
    report = get_or_create_report(db, user=user, week_start=ws)

    if report.is_locked:
        if is_week_finalized(report.week_start, localnow()):
            raise ConflictStateError("本周周报已定版，无法再修改内容，如需更正请联系管理员")
        # 修订暂存：内容落库 + 留痕，状态与「已提交」事实不变
        _replace_items(db, report, items)
        report.last_edited_at = utcnow()
        report.version = (report.version or 1) + 1
        _write_revision(db, report, editor_id=user.id, reason="保存草稿（修订暂存）")
        _refresh_validity(report)
        db.flush()
        db.refresh(report)
        return report

    _replace_items(db, report, items)
    report.last_edited_at = utcnow()
    _refresh_validity(report)
    db.flush()
    db.refresh(report)
    return report


def submit_report(
    db: Session,
    *,
    report: WeeklyReport,
    items: list[ReportItemIn] | None = None,
    actor: User | None = None,
    proxy_reason: str | None = None,
    reason: str | None = None,
) -> WeeklyReport:
    """提交周报（含代提交）。

    首次提交时判定状态并写 v1 快照；已提交过则为**修订**，版本号 +1，状态不变。
    """
    if items is not None:
        _replace_items(db, report, items)

    _refresh_validity(report)

    is_proxy = actor is not None and actor.id != report.user_id
    if is_proxy:
        permission.assert_can_proxy(actor, db.get(User, report.user_id))
        report.submitted_by_id = actor.id
        report.proxy_reason = proxy_reason

    pre_status = report.status
    first_submit = report.submitted_at is None
    now_utc = utcnow()
    now_local = localnow()

    if first_submit:
        report.submitted_at = now_utc
        report.status = _decide_status(
            week_start=report.week_start,
            now_local=now_local,
            is_proxy=is_proxy,
            pre_status=pre_status,
        )
    else:
        # 修订：版本号 +1，但**保留已生效的提交状态**（准时/迟到不因修订而改变）
        report.version = (report.version or 1) + 1

    report.last_edited_at = now_utc
    _write_revision(db, report, editor_id=(actor.id if actor else report.user_id), reason=reason)
    db.flush()
    db.refresh(report)
    return report


def _decide_status(
    *,
    week_start: dt.date,
    now_local: dt.datetime,
    is_proxy: bool,
    pre_status: ReportStatus,
) -> ReportStatus:
    """判定首次提交的状态。代提交优先级最高；已判定为缺交的一律记为补交。"""
    if is_proxy:
        return ReportStatus.BY_PROXY
    if pre_status == ReportStatus.MISSING:
        return ReportStatus.MAKEUP
    kind = classify_submission(week_start, now_local)
    return {
        "ontime": ReportStatus.ONTIME,
        "late": ReportStatus.LATE,
    }.get(kind, ReportStatus.MAKEUP)


def _write_revision(
    db: Session, report: WeeklyReport, *, editor_id: int, reason: str | None = None
) -> WeeklyReportRevision:
    """写入版本快照（任何时候修改内容都留痕）。"""
    version = report.version or 1
    snapshot = {
        "week_start": report.week_start.isoformat(),
        "status": report.status.value,
        "version": version,
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at else None,
        "sections": {
            section.value: [
                {"content": item.content, "task_id": item.task_id, "source": item.source.value}
                for item in report.section_items(section)
            ]
            for section in ReportSection
        },
    }
    revision = WeeklyReportRevision(
        report_id=report.id,
        version=version,
        snapshot=snapshot,
        editor_id=editor_id,
        reason=reason,
        created_at=utcnow(),
    )
    db.add(revision)
    db.flush()
    return revision


def review_report(
    db: Session, *, report: WeeklyReport, reviewer: User, comment: str | None, approved: bool
) -> WeeklyReport:
    """组长审阅。"""
    target = db.get(User, report.user_id)
    permission.assert_can_proxy(reviewer, target)
    report.reviewed_by_id = reviewer.id
    report.reviewed_at = utcnow()
    report.review_comment = comment
    if not approved and report.status != ReportStatus.MISSING:
        # 退回：恢复为草稿，允许本人重新编辑
        report.status = ReportStatus.DRAFT
        report.submitted_at = None
        report.version = (report.version or 1) + 1
    db.flush()
    return report


def list_revisions(db: Session, report_id: int) -> list[WeeklyReportRevision]:
    return list(
        db.execute(
            select(WeeklyReportRevision)
            .where(WeeklyReportRevision.report_id == report_id)
            .order_by(WeeklyReportRevision.version.desc())
        )
        .scalars()
        .all()
    )


def mark_missing(db: Session, *, user: User, week_start: dt.date) -> WeeklyReport:
    """定版任务调用：把未提交的周报显式标记为 MISSING。"""
    report = get_or_create_report(db, user=user, week_start=week_start)
    if report.submitted_at is None:
        report.status = ReportStatus.MISSING
    db.flush()
    return report


# ----------------------------------------------------------------------
# 有效性与序列化
# ----------------------------------------------------------------------
def _refresh_validity(report: WeeklyReport) -> None:
    """刷新「有效周报」判定。

    关键段落为 ``done``（本周工作总结）与 ``plan``（下周工作计划），
    二者合计非空且达到最少字数才算有效。
    """
    from app.core.config import settings

    chars = 0
    for section in (ReportSection.DONE, ReportSection.PLAN):
        chars += sum(len(item.content.strip()) for item in report.section_items(section))
    if chars <= 0:
        report.is_valid = False
        report.invalid_reason = "「本周工作总结」与「下周工作计划」均为空"
        return
    if chars < settings.report_valid_min_chars:
        report.is_valid = False
        report.invalid_reason = f"关键段落仅 {chars} 字，低于 {settings.report_valid_min_chars} 字要求"
        return
    report.is_valid = True
    report.invalid_reason = None


def char_count(report: WeeklyReport) -> int:
    """周报关键段落（done 本周工作总结 + plan 下周工作计划）字数，与有效性判定一致。"""
    total = 0
    for section in (ReportSection.DONE, ReportSection.PLAN):
        total += sum(len(item.content.strip()) for item in report.section_items(section))
    return total


def serialize_report(db: Session, report: WeeklyReport) -> dict[str, Any]:
    """把 ORM 对象转换为前端需要的字典（含派生字段）。"""
    from app.schemas.report import ReportItemOut

    owner = report.user or db.get(User, report.user_id)
    proxy = db.get(User, report.submitted_by_id) if report.submitted_by_id else None

    def to_item_out(item: WeeklyReportItem) -> ReportItemOut:
        return ReportItemOut(
            id=item.id,
            report_id=item.report_id,
            section=item.section.value,
            content=item.content,
            task_id=item.task_id,
            task_title=item.task.title if item.task else None,
            source=item.source.value,
            sort_order=item.sort_order,
        )

    sections = ReportSections(
        done=[to_item_out(i) for i in report.section_items(ReportSection.DONE)],
        progress=[to_item_out(i) for i in report.section_items(ReportSection.PROGRESS)],
        risk=[to_item_out(i) for i in report.section_items(ReportSection.RISK)],
        plan=[to_item_out(i) for i in report.section_items(ReportSection.PLAN)],
    )

    return {
        "id": report.id,
        "user_id": report.user_id,
        "username": owner.username if owner else None,
        "full_name": owner.full_name if owner else None,
        "week_start": report.week_start,
        "week_label": week_label(report.week_start),
        "year": report.year,
        "week_no": report.week_no,
        "status": report.status.value,
        "status_label": STATUS_LABELS.get(report.status.value, report.status.value),
        "version": report.version,
        "submitted_at": report.submitted_at,
        "last_edited_at": report.last_edited_at,
        "submitted_by_id": report.submitted_by_id,
        "submitted_by_name": proxy.full_name if proxy else None,
        "proxy_reason": report.proxy_reason,
        "reviewed_by_id": report.reviewed_by_id,
        "reviewed_at": report.reviewed_at,
        "review_comment": report.review_comment,
        "is_valid": report.is_valid,
        "invalid_reason": report.invalid_reason,
        "is_locked": report.is_locked,
        "items": [to_item_out(i) for i in report.items],
        "sections": sections,
        "char_count": char_count(report),
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }


def serialize_revision(db: Session, revision: WeeklyReportRevision) -> dict[str, Any]:
    editor = db.get(User, revision.editor_id)
    return {
        "id": revision.id,
        "report_id": revision.report_id,
        "version": revision.version,
        "snapshot": revision.snapshot,
        "editor_id": revision.editor_id,
        "editor_name": editor.full_name if editor else None,
        "reason": revision.reason,
        "created_at": revision.created_at,
    }


def _humanize_local(moment: dt.datetime) -> str:
    """把带时区的时刻渲染为面向用户展示的本地时间串。

    输出形如 ``2026-10-23 18:00``：精确到分钟，不带秒与 ``+08:00`` 后缀，
    避免前端直接展示 ISO 串时出现 ``18:00:00+08:00`` 这类冗余信息。
    """
    return to_local(moment).strftime("%Y-%m-%d %H:%M")


def my_week_status(db: Session, *, user: User, week_start: dt.date | None = None) -> dict[str, Any]:
    """「我的周报」卡片：当前周状态、截止与定版时刻、是否还能编辑。"""
    ws = normalize_week_start(week_start)
    report = get_user_report(db, user.id, ws)
    deadline = deadline_of(ws)
    finalize = finalize_of(ws)
    now = localnow()

    finalized = is_week_finalized(ws, now)
    status = report.status.value if report else ReportStatus.DRAFT.value
    has_report = report is not None and report.submitted_at is not None

    return {
        "week_start": ws,
        "week_label": week_label(ws),
        # 面向用户展示：统一为「YYYY-MM-DD HH:mm」本地时间，不带秒与时区后缀
        "deadline_at": _humanize_local(deadline),
        "finalize_at": _humanize_local(finalize),
        "deadline_passed": now > deadline,
        "has_report": has_report,
        "report_id": report.id if report else None,
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "submitted_at": report.submitted_at.isoformat() if report and report.submitted_at else None,
        # 定版后无法再生成/普通编辑，只能走补交流程
        "can_edit": not finalized or (report is not None and report.status == ReportStatus.MISSING),
        "can_generate": not finalized,
    }
