"""定时任务实现：点名名册生成、五时点提醒、周一定版。

所有 job 都自行开启独立会话（``session_scope``），请求上下文与 job 互不干扰。
单一调度器实例由 ``scheduler.py`` 持有；多副本部署时需改为独立 worker 进程，
否则每个副本都会重复发送提醒。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.organization import Department, DepartmentMember, User
from app.models.report import WeeklyReport
from app.services import notifier, rollcall_service, stats_service
from app.services.auth_service import normalize_week_start
from app.utils.week import localnow, week_label

logger = get_logger(__name__)

# 提醒相位 → (cron 触发时机说明, 是否抄送组长)
REMINDER_PHASES = {
    "fri_1000": ("周五 10:00 首次提醒", False),
    "fri_1700": ("周五 17:00 截止预警（仅未动笔者）", False),
    "sun_2000": ("周日 20:00 周末催办", False),
    "mon_0830": ("周一 08:30 最后通牒", True),
}


def job_generate_roll_call(week_start: dt.date | None = None) -> None:
    """生成点名名册（周一 00:05 触发）。"""
    with session_scope() as db:
        ws = normalize_week_start(week_start)
        count = rollcall_service.generate_week_roll_call(db, ws)
        logger.info("[定时任务] 点名名册生成完成 week=%s rows=%s", ws, count)


def _pending_users(
    db: Session, week_start: dt.date, *, only_untouched: bool = False
) -> list[User]:
    """某周尚未提交周报的用户。

    :param only_untouched: True 时只返回"连草稿都没动过"的人
    """
    rows = rollcall_service.roll_call_rows(db, week_start)
    user_ids = {row.user_id for row in rows if row.required}
    if not user_ids:
        return []

    submitted = {
        report.user_id
        for report in db.execute(
            select(WeeklyReport).where(
                WeeklyReport.week_start == week_start,
                WeeklyReport.user_id.in_(user_ids),
            )
        )
        .scalars()
        .all()
        if report.submitted_at is not None
    }

    if only_untouched:
        drafted = {
            report.user_id
            for report in db.execute(
                select(WeeklyReport).where(
                    WeeklyReport.week_start == week_start,
                    WeeklyReport.user_id.in_(user_ids),
                )
            )
            .scalars()
            .all()
        }
        # drafted - submitted 表示"写了草稿但没提交"，也算动过笔，不再打扰
        target_ids = user_ids - submitted - drafted
    else:
        target_ids = user_ids - submitted

    if not target_ids:
        return []
    return list(
        db.execute(select(User).where(User.id.in_(target_ids), User.is_active.is_(True)))
        .scalars()
        .all()
    )


def job_remind(phase: str) -> None:
    """周报提交提醒。"""
    description, copy_leader = REMINDER_PHASES.get(phase, (phase, False))
    with session_scope() as db:
        ws = normalize_week_start(None)
        rollcall_service.ensure_roll_call(db, ws)
        only_untouched = phase == "fri_1700"
        users = _pending_users(db, ws, only_untouched=only_untouched)
        if not users:
            logger.info("[定时任务] %s：无人待提醒，跳过", description)
            return

        label = week_label(ws)
        title = f"周报提交提醒（{label}）"
        content = f"您尚未提交 {label} 的周报，请及时填写并提交。"
        count = notifier.notify(
            db,
            users,
            title,
            content,
            link="/reports",
            include_email=True,
        )

        if copy_leader:
            _notify_leaders(db, ws, label)

        logger.info("[定时任务] %s：已通知 %s 人", description, count)


def _notify_leaders(db: Session, week_start: dt.date, label: str) -> None:
    """把未提交名单抄送给各部门组长。"""
    rows = rollcall_service.roll_call_rows(db, week_start)
    leader_rows = list(
        db.execute(
            select(DepartmentMember).where(DepartmentMember.is_leader.is_(True))
        )
        .scalars()
        .all()
    )
    if not leader_rows:
        return

    pending_by_dept: dict[int, list[User]] = {}
    user_ids = {row.user_id for row in rows if row.required}
    if not user_ids:
        return

    submitted = {
        report.user_id
        for report in db.execute(
            select(WeeklyReport).where(
                WeeklyReport.week_start == week_start,
                WeeklyReport.user_id.in_(user_ids),
            )
        )
        .scalars()
        .all()
        if report.submitted_at is not None
    }
    pending_ids = user_ids - submitted
    if not pending_ids:
        return

    pending_users = {
        user.id: user
        for user in db.execute(select(User).where(User.id.in_(pending_ids))).scalars().all()
    }
    for row in rows:
        if row.user_id in pending_ids and pending_users.get(row.user_id):
            pending_by_dept.setdefault(row.department_id, []).append(pending_users[row.user_id])

    leaders = {
        leader.user_id
        for leader in leader_rows
        if leader.department_id in pending_by_dept
    }
    if not leaders:
        return

    leader_users = list(
        db.execute(select(User).where(User.id.in_(leaders))).scalars().all()
    )
    for leader in leader_users:
        dept_ids = leader.leader_department_ids
        names: list[str] = []
        for dept_id in dept_ids:
            names.extend(u.full_name for u in pending_by_dept.get(dept_id, []))
        if not names:
            continue
        dept_names = _department_names(db, dept_ids)
        notifier.notify(
            db,
            [leader],
            f"周报提交催办通知（{label}）",
            f"截至 09:30 定版前，以下成员仍未提交周报：\n"
            f"部门：{dept_names}\n"
            f"成员：{'、'.join(sorted(set(names)))}\n"
            f"共 {len(set(names))} 人，请协助督促。",
            link="/stats",
        )


def _department_names(db: Session, dept_ids: list[int]) -> str:
    if not dept_ids:
        return "-"
    rows = db.execute(select(Department).where(Department.id.in_(dept_ids))).scalars().all()
    return "、".join(d.name for d in rows)


def job_finalize() -> None:
    """周一定版：生成统计快照并推送结算摘要给组长/管理员。"""
    with session_scope() as db:
        # 定版的是**刚结束的那一周**（今天是下周一，所以要回溯 7 天）
        ws = normalize_week_start(None) - dt.timedelta(days=7)
        rollcall_service.ensure_roll_call(db, ws)
        snapshots = stats_service.finalize_week(db, ws)
        if not snapshots:
            logger.info("[定时任务] %s 定版：无名册数据", ws)
            return

        label = week_label(ws)
        total_required = sum(s.required_count for s in snapshots)
        total_ontime = sum(s.ontime_count for s in snapshots)
        rate = round(total_ontime / total_required * 100, 2) if total_required else 0.0

        leaders = list(
            db.execute(
                select(User).where(
                    User.is_superuser.is_(True)
                    | User.id.in_(
                        select(DepartmentMember.user_id).where(
                            DepartmentMember.is_leader.is_(True)
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        notifier.notify(
            db,
            leaders,
            f"{label} 周报统计已定版",
            f"应提交 {total_required} 人，准时 {total_ontime} 人，准时率 {rate}%。\n"
            f"数据已冻结，可在「统计看板」查看详情。",
            link="/stats",
        )
        logger.info(
            "[定时任务] %s 定版完成：应提交 %s，准时率 %s%%", ws, total_required, rate
        )


def run_startup_backfill() -> None:
    """启动时补偿：确保当前周名册存在（防止服务停机错过了周一 00:00）。"""
    with session_scope() as db:
        ws = normalize_week_start(None)
        created = rollcall_service.ensure_roll_call(db, ws)
        if created:
            logger.info("[启动补偿] 已补生成 %s 的点名名册，共 %s 条", ws, created)
        now = localnow()
        logger.info("[启动补偿] 当前本地时间 %s，当前周 %s", now.isoformat(), ws)
