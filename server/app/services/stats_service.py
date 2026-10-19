"""统计服务 —— 口径集中实现，禁止在别处重复造轮子。

口径（《需求规格说明书》第 6 章）：
- 应提交人数 = 名册中 ``required=True`` 的人数（含请假豁免后的结果）
- 准时率 = 准时数 / 应提交数（分母固定）
- 提交率 = (准时 + 迟到 + 补交 + 代交) / 应提交数
- **补交永不回填 missing_count**，历史数据可审计
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import ReportStatus
from app.models.organization import Department, User
from app.models.report import WeeklyReport, WeeklyRollCall, WeeklyStatSnapshot
from app.services import rollcall_service
from app.services.auth_service import normalize_week_start
from app.services.report_service import STATUS_LABELS, get_user_report, mark_missing
from app.utils.week import is_week_finalized, localnow, week_label

logger = get_logger(__name__)

# 视为"已提交"的状态集合
SUBMITTED = (
    ReportStatus.ONTIME,
    ReportStatus.LATE,
    ReportStatus.MAKEUP,
    ReportStatus.BY_PROXY,
)


@dataclass
class Counts:
    required: int = 0
    exempt: int = 0
    submitted: int = 0
    ontime: int = 0
    late: int = 0
    makeup: int = 0
    missing: int = 0
    by_proxy: int = 0
    valid: int = 0


def _counts_to_dict(counts: Counts) -> dict[str, int]:
    return {
        "required": counts.required,
        "exempt": counts.exempt,
        "submitted": counts.submitted,
        "ontime": counts.ontime,
        "late": counts.late,
        "makeup": counts.makeup,
        "missing": counts.missing,
        "by_proxy": counts.by_proxy,
        "valid": counts.valid,
    }


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 2)


# ----------------------------------------------------------------------
# 实时统计（尚未定版 / 或管理员想看当前进展时使用）
# ----------------------------------------------------------------------
def compute_department_counts(
    db: Session, week_start: dt.date, department_id: int
) -> Counts:
    """实时计算某部门某周的各项计数。"""
    rows = rollcall_service.roll_call_rows(db, week_start, department_id)
    counts = Counts(required=sum(1 for r in rows if r.required))
    counts.exempt = len(rows) - counts.required

    user_ids = [r.user_id for r in rows if r.required]
    if not user_ids:
        return counts

    reports = {
        r.user_id: r
        for r in db.execute(
            select(WeeklyReport).where(
                WeeklyReport.user_id.in_(user_ids),
                WeeklyReport.week_start == normalize_week_start(week_start),
            )
        )
        .scalars()
        .all()
    }

    for uid in user_ids:
        report = reports.get(uid)
        if report is None or report.submitted_at is None:
            counts.missing += 1
            continue
        counts.submitted += 1
        if report.status == ReportStatus.ONTIME:
            counts.ontime += 1
        elif report.status == ReportStatus.LATE:
            counts.late += 1
        elif report.status == ReportStatus.MAKEUP:
            counts.makeup += 1
        elif report.status == ReportStatus.BY_PROXY:
            counts.by_proxy += 1
        if report.is_valid:
            counts.valid += 1
    return counts


def overview(
    db: Session,
    *,
    week_start: dt.date,
    department_ids: list[int] | None = None,
) -> dict:
    """总体概览（跨部门汇总）。``department_ids=None`` 表示全部部门。"""
    ws = normalize_week_start(week_start)
    if department_ids is None:
        department_ids = db.execute(
            select(WeeklyRollCall.department_id).where(WeeklyRollCall.week_start == ws).distinct()
        ).scalars().all()
        department_ids = sorted(set(department_ids))

    total = Counts()
    for dept_id in department_ids:
        part = compute_department_counts(db, ws, dept_id)
        total.required += part.required
        total.exempt += part.exempt
        total.submitted += part.submitted
        total.ontime += part.ontime
        total.late += part.late
        total.makeup += part.makeup
        total.missing += part.missing
        total.by_proxy += part.by_proxy
        total.valid += part.valid

    data = _counts_to_dict(total)
    data.update(
        {
            "week_start": ws,
            "week_label": week_label(ws),
            "ontime_rate": _rate(total.ontime, total.required),
            "submit_rate": _rate(total.submitted, total.required),
            "missing_rate": _rate(total.missing, total.required),
            "valid_rate": _rate(total.valid, total.submitted),
            "finalized": is_week_finalized(ws, localnow()),
        }
    )
    return data


def by_department(
    db: Session, *, week_start: dt.date, department_ids: list[int] | None = None
) -> list[dict]:
    """部门横向对比。"""
    ws = normalize_week_start(week_start)
    if department_ids is None:
        department_ids = sorted(
            set(
                db.execute(
                    select(WeeklyRollCall.department_id)
                    .where(WeeklyRollCall.week_start == ws)
                    .distinct()
                )
                .scalars()
                .all()
            )
        )

    result = []
    for dept_id in department_ids:
        dept = db.get(Department, dept_id)
        counts = compute_department_counts(db, ws, dept_id)
        row = _counts_to_dict(counts)
        row.update(
            {
                "department_id": dept_id,
                "department_name": dept.name if dept else f"部门#{dept_id}",
                "ontime_rate": _rate(counts.ontime, counts.required),
                "submit_rate": _rate(counts.submitted, counts.required),
            }
        )
        result.append(row)
    result.sort(key=lambda r: (-r["ontime_rate"], r["department_name"]))
    return result


def people(
    db: Session, *, week_start: dt.date, department_id: int | None = None
) -> list[dict]:
    """个人明细（不含补交排序，按状态分组展示）。"""
    ws = normalize_week_start(week_start)
    if department_id is None:
        rows = rollcall_service.roll_call_rows(db, ws)
    else:
        rows = rollcall_service.roll_call_rows(db, ws, department_id)

    user_map = {
        u.id: u
        for u in db.execute(
            select(User).where(User.id.in_({r.user_id for r in rows}))
        )
        .scalars()
        .all()
    } if rows else {}
    dept_map = {
        d.id: d
        for d in db.execute(select(Department)).scalars().all()
    }

    result = []
    for row in rows:
        user = user_map.get(row.user_id)
        report = get_user_report(db, row.user_id, ws)
        if report is not None and report.submitted_at is not None:
            status = report.status.value
            submitted_at = report.submitted_at.isoformat() if report.submitted_at else None
            valid = report.is_valid
        else:
            status = ReportStatus.MISSING.value
            submitted_at = None
            valid = False

        if not row.required:
            # 豁免人员不参与考核，但仍展示在名单里
            status = ReportStatus.MISSING.value

        result.append(
            {
                "user_id": row.user_id,
                "username": user.username if user else "-",
                "full_name": user.full_name if user else "-",
                "department_name": dept_map.get(row.department_id).name
                if dept_map.get(row.department_id)
                else None,
                "required": row.required,
                "exempt_reason": row.exempt_reason,
                "status": status,
                "status_label": "豁免" if not row.required else STATUS_LABELS.get(status, status),
                "submitted_at": submitted_at,
                "is_valid": valid,
                "continuous_missing": 0 if not row.required else continuous_missing(db, row.user_id, ws),
            }
        )
    return result


def continuous_missing(db: Session, user_id: int, week_start: dt.date, *, max_weeks: int = 12) -> int:
    """截至指定周，该用户连续未提交（含未交状态）的周数。

    判定口径：向历史回溯，遇到第一个"已提交"的周即停止。
    """
    ws = normalize_week_start(week_start)
    count = 0
    cursor = ws
    for _ in range(max_weeks):
        report = get_user_report(db, user_id, cursor)
        if report is not None and report.submitted_at is not None:
            break
        if report is None or report.status != ReportStatus.MISSING:
            # 未到定版的周不计入"缺交"
            if not is_week_finalized(cursor, localnow()):
                break
        count += 1
        cursor = cursor - dt.timedelta(days=7)
    return count


# ----------------------------------------------------------------------
# 定版：冻结为不可变快照
# ----------------------------------------------------------------------
def finalize_week(
    db: Session, week_start: dt.date, *, force: bool = False
) -> list[WeeklyStatSnapshot]:
    """周一定版：为每个 department 生成/更新 ``WeeklyStatSnapshot`` 并冻结。

    同时把"未提交"的成员显式写成 ``MISSING`` 状态的周报行，
    以便后续补交能落到同一条记录上。

    :param force: True 时强制重算已定版的快照。
        **默认 False —— 已冻结的快照不会被后续补交改写**，这是历史数据可审计的前提。
    """
    ws = normalize_week_start(week_start)
    department_ids = rollcall_service.department_ids_of_week(db, ws)
    snapshots: list[WeeklyStatSnapshot] = []

    for dept_id in department_ids:
        counts = Counts()
        rows = rollcall_service.roll_call_rows(db, ws, dept_id)
        counts.required = sum(1 for r in rows if r.required)
        counts.exempt = len(rows) - counts.required

        for row in rows:
            if not row.required:
                continue
            user = db.get(User, row.user_id)
            report = get_user_report(db, row.user_id, ws)
            if report is None or report.submitted_at is None:
                counts.missing += 1
                report = mark_missing(db, user=user, week_start=ws)
                continue
            counts.submitted += 1
            if report.status == ReportStatus.ONTIME:
                counts.ontime += 1
            elif report.status == ReportStatus.LATE:
                counts.late += 1
            elif report.status == ReportStatus.MAKEUP:
                counts.makeup += 1
            elif report.status == ReportStatus.BY_PROXY:
                counts.by_proxy += 1
            if report.is_valid:
                counts.valid += 1

        snapshot = db.execute(
            select(WeeklyStatSnapshot).where(
                WeeklyStatSnapshot.week_start == ws,
                WeeklyStatSnapshot.department_id == dept_id,
            )
        ).scalar_one_or_none()
        if snapshot is None:
            snapshot = WeeklyStatSnapshot(week_start=ws, department_id=dept_id)
            db.add(snapshot)
        elif snapshot.finalized and not force:
            snapshots.append(snapshot)
            continue  # 已冻结，拒绝改写（防止补交洗白历史数据）

        snapshot.required_count = counts.required
        snapshot.exempt_count = counts.exempt
        snapshot.submitted_count = counts.submitted
        snapshot.ontime_count = counts.ontime
        snapshot.late_count = counts.late
        snapshot.makeup_count = counts.makeup
        snapshot.missing_count = counts.missing
        snapshot.by_proxy_count = counts.by_proxy
        snapshot.valid_count = counts.valid
        snapshot.finalized = True
        snapshot.computed_at = dt.datetime.now(tz=dt.timezone.utc).replace(tzinfo=None)
        snapshots.append(snapshot)

    db.flush()
    logger.info("已定版 %s 的周报统计，共 %s 个部门", ws.isoformat(), len(snapshots))
    return snapshots


def trend(
    db: Session, *, weeks: int = 12, department_ids: list[int] | None = None
) -> list[dict]:
    """近 N 周趋势，优先读已定版快照，未定版的周回退到实时计算。"""
    from app.utils.week import recent_week_starts

    result = []
    for ws in recent_week_starts(weeks):
        snapshot_rows = (
            db.execute(select(WeeklyStatSnapshot).where(WeeklyStatSnapshot.week_start == ws))
            .scalars()
            .all()
            if department_ids is None
            else db.execute(
                select(WeeklyStatSnapshot).where(
                    WeeklyStatSnapshot.week_start == ws,
                    WeeklyStatSnapshot.department_id.in_(department_ids),
                )
            )
            .scalars()
            .all()
        )
        if snapshot_rows:
            agg = Counts()
            for snap in snapshot_rows:
                agg.required += snap.required_count
                agg.exempt += snap.exempt_count
                agg.submitted += snap.submitted_count
                agg.ontime += snap.ontime_count
                agg.late += snap.late_count
                agg.makeup += snap.makeup_count
                agg.missing += snap.missing_count
                agg.by_proxy += snap.by_proxy_count
                agg.valid += snap.valid_count
        else:
            agg = Counts()
            dept_ids = department_ids or rollcall_service.department_ids_of_week(db, ws)
            for dept_id in dept_ids:
                part = compute_department_counts(db, ws, dept_id)
                agg.required += part.required
                agg.submitted += part.submitted
                agg.ontime += part.ontime
                agg.late += part.late
                agg.makeup += part.makeup
                agg.missing += part.missing
                agg.by_proxy += part.by_proxy
                agg.valid += part.valid

        result.append(
            {
                "week_start": ws,
                "week_label": week_label(ws),
                "required": agg.required,
                "ontime": agg.ontime,
                "late": agg.late,
                "makeup": agg.makeup,
                "missing": agg.missing,
                "by_proxy": agg.by_proxy,
                "ontime_rate": _rate(agg.ontime, agg.required),
                "submit_rate": _rate(agg.submitted, agg.required),
            }
        )
    return result


def snapshots(db: Session, week_start: dt.date, department_id: int | None = None) -> list[dict]:
    """查询某周的定版快照。"""
    ws = normalize_week_start(week_start)
    stmt = select(WeeklyStatSnapshot).where(WeeklyStatSnapshot.week_start == ws)
    if department_id is not None:
        stmt = stmt.where(WeeklyStatSnapshot.department_id == department_id)

    result = []
    for snap in db.execute(stmt).scalars().all():
        dept = db.get(Department, snap.department_id)
        result.append(
            {
                "id": snap.id,
                "week_start": snap.week_start,
                "department_id": snap.department_id,
                "department_name": dept.name if dept else None,
                "required_count": snap.required_count,
                "exempt_count": snap.exempt_count,
                "submitted_count": snap.submitted_count,
                "ontime_count": snap.ontime_count,
                "late_count": snap.late_count,
                "makeup_count": snap.makeup_count,
                "missing_count": snap.missing_count,
                "by_proxy_count": snap.by_proxy_count,
                "valid_count": snap.valid_count,
                "finalized": snap.finalized,
                "computed_at": snap.computed_at,
                "ontime_rate": snap.ontime_rate,
                "submit_rate": snap.submit_rate,
            }
        )
    return result


def total_required(db: Session, week_start: dt.date, department_id: int | None = None) -> int:
    """便捷函数：某周应提交人数。"""
    ws = normalize_week_start(week_start)
    if department_id is not None:
        return len(rollcall_service.required_user_ids(db, ws, department_id))
    return sum(
        len(rollcall_service.required_user_ids(db, ws, d))
        for d in rollcall_service.department_ids_of_week(db, ws)
    )
