"""周报自动草稿生成器 —— 本产品的核心算法。

算法口径（《需求规格说明书》FR-REP-02）：
取以下四类任务的**并集**，按负责人 + 协作人分组汇总：

1. 本周内流水变为 DONE 的任务                → ``done`` 本周工作总结
2. 当前 IN_PROGRESS，或本周有流水且未关闭的任务 → ``progress`` 本周工作进展
3. 本周内标记过 BLOCKED 的任务                → ``risk`` 需协调与帮助
4. 未完成且截止日在下周的任务 ＋ 上周 plan 顺延 → ``plan`` 下周工作计划

页面展示顺序为：本周工作进展 → 本周工作总结 → 下周工作计划 → 需协调与帮助。

**数据切片不变性**：无论周五提交还是下周一早上补交，草稿内容一律取
``本自然周（周一 00:00 ~ 周日 23:59:59）`` 的任务流水与周终态，
不混入下周一当天的变更，保证跨周数据可比。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import ConflictStateError
from app.models.enums import ItemSource, ReportSection, TaskStatus
from app.models.organization import User
from app.models.project import Project, Task, TaskCollaborator, TaskStatusLog
from app.models.report import WeeklyReport, WeeklyReportItem
from app.utils.week import (
    ensure_date,
    iso_year_week,
    previous_week_start,
    utcnow,
    week_end_of,
    week_range_utc,
)
from app.services.auth_service import normalize_week_start

# 已关闭状态：不出现在任何草稿段落
CLOSED_STATUSES = {TaskStatus.DONE, TaskStatus.CANCELLED}


@dataclass
class GeneratedContent:
    """一次生成的段落内容。"""

    done: list[tuple[int | None, str]] = field(default_factory=list)
    progress: list[tuple[int | None, str]] = field(default_factory=list)
    risk: list[tuple[int | None, str]] = field(default_factory=list)
    plan: list[tuple[int | None, str]] = field(default_factory=list)


# ----------------------------------------------------------------------
# 对外主入口
# ----------------------------------------------------------------------
def generate_draft(
    db: Session,
    *,
    user: User,
    week_start: dt.date | None = None,
    force: bool = False,
) -> WeeklyReport:
    """为指定用户生成（或增量刷新）本周周报草稿。

    :param force: True 时重建全部 ``source=auto`` 条目（人工条目保留）；
                  False 时为增量合并，仅追加本周新增内容。
    :raises ConflictStateError: 周报已提交时不允许再自动生成（须先走修订流程）
    """
    ws = normalize_week_start(week_start)

    report = get_or_create_report(db, user=user, week_start=ws)
    if report.is_locked:
        raise ConflictStateError("周报已提交并锁定，如需修改请使用「修订」功能")

    content = collect_week_content(db, user=user, week_start=ws)

    if force:
        # 清理旧自动条目，避免重复堆积；人工条目按 sort_order 保留
        kept = [item for item in report.items if item.source == ItemSource.MANUAL]
        for item in list(report.items):
            if item.source == ItemSource.AUTO:
                db.delete(item)
        db.flush()
        report.items = kept

    existing_auto = {
        (item.section, item.task_id)
        for item in report.items
        if item.source == ItemSource.AUTO
    }

    base_order = max((item.sort_order for item in report.items), default=0) + 1
    new_items: list[WeeklyReportItem] = []

    for section_enum, pairs in (
        (ReportSection.DONE, content.done),
        (ReportSection.PROGRESS, content.progress),
        (ReportSection.RISK, content.risk),
        (ReportSection.PLAN, content.plan),
    ):
        for task_id, text in pairs:
            key = (section_enum, task_id)
            if key in existing_auto:
                continue
            new_items.append(
                WeeklyReportItem(
                    report_id=report.id,
                    section=section_enum,
                    content=text,
                    task_id=task_id,
                    source=ItemSource.AUTO,
                    sort_order=base_order,
                )
            )
            existing_auto.add(key)
            base_order += 1

    if new_items:
        db.add_all(new_items)
    report.last_edited_at = utcnow()
    db.flush()
    db.refresh(report)
    return report


def get_or_create_report(db: Session, *, user: User, week_start: dt.date) -> WeeklyReport:
    """取本周周报，不存在则创建空草稿（唯一约束：一人一周一份）。"""
    ws = ensure_date(week_start)
    stmt = select(WeeklyReport).where(
        WeeklyReport.user_id == user.id, WeeklyReport.week_start == ws
    )
    report = db.execute(stmt).scalar_one_or_none()
    if report is not None:
        return report

    year, week_no = iso_year_week(ws)
    report = WeeklyReport(
        user_id=user.id,
        week_start=ws,
        year=year,
        week_no=week_no,
        version=1,
    )
    db.add(report)
    db.flush()
    return report


# ----------------------------------------------------------------------
# 核心取数
# ----------------------------------------------------------------------
def collect_week_content(db: Session, *, user: User, week_start: dt.date) -> GeneratedContent:
    """按四类规则汇总本周与该用户相关的任务，返回可直接渲染的四段内容。"""
    ws = ensure_date(week_start)
    utc_start, utc_end = week_range_utc(ws)

    done_tasks = _tasks_became_done(db, user, utc_start, utc_end)
    risk_tasks = _tasks_blocked_in_week(db, user, utc_start, utc_end)
    progress_tasks = _tasks_in_progress(db, user, utc_start, utc_end)
    plan_tasks = _tasks_due_next_week(db, user, ws)

    # 去重：同一任务只出现在最优先的一个段落
    priority = (
        (ReportSection.DONE, done_tasks),
        (ReportSection.RISK, risk_tasks),
        (ReportSection.PROGRESS, progress_tasks),
        (ReportSection.PLAN, plan_tasks),
    )
    assigned: dict[int, ReportSection] = {}
    for section, tasks in priority:
        for task in tasks:
            if task.id in assigned:
                continue
            assigned[task.id] = section

    project_cache = _load_projects(db, {t.project_id for _section, tasks in priority for t in tasks})
    content = GeneratedContent()

    for task in done_tasks:
        if assigned.get(task.id) is ReportSection.DONE:
            content.done.append(
                (
                    task.id,
                    f"【{_code(project_cache, task.project_id)}】{task.title} —— 已完成",
                )
            )
    for task in risk_tasks:
        if assigned.get(task.id) is ReportSection.RISK:
            reason = _last_remark(db, task.id)
            suffix = f"（{reason}）" if reason else ""
            content.risk.append(
                (
                    task.id,
                    f"【{_code(project_cache, task.project_id)}】{task.title} 本周被标记为阻塞{suffix}",
                )
            )
    for task in progress_tasks:
        if assigned.get(task.id) is ReportSection.PROGRESS:
            content.progress.append(
                (
                    task.id,
                    f"【{_code(project_cache, task.project_id)}】{task.title} —— 进行中，进度 {task.progress}%",
                )
            )
    for task in plan_tasks:
        if assigned.get(task.id) is ReportSection.PLAN:
            due = f"，截止 {task.due_date.isoformat()}" if task.due_date else ""
            content.plan.append(
                (
                    task.id,
                    f"【{_code(project_cache, task.project_id)}】{task.title}{due}",
                )
            )

    content.plan.extend(_carry_over_from_last_week(db, user=user, week_start=ws, assigned=assigned))
    return content


def _participant_condition(user: User):
    """任务参与者条件：负责人或协作人。"""
    collab_sub = select(TaskCollaborator.task_id).where(TaskCollaborator.user_id == user.id)
    return or_(Task.owner_id == user.id, Task.id.in_(collab_sub))


def _tasks_became_done(
    db: Session, user: User, utc_start: dt.datetime, utc_end: dt.datetime
) -> list[Task]:
    """规则 1：本周内流水变为 DONE 的任务。"""
    stmt = (
        select(Task)
        .join(TaskStatusLog, TaskStatusLog.task_id == Task.id)
        .options(selectinload(Task.project))
        .where(
            _participant_condition(user),
            TaskStatusLog.to_status == TaskStatus.DONE,
            TaskStatusLog.created_at >= utc_start,
            TaskStatusLog.created_at <= utc_end,
        )
        .order_by(TaskStatusLog.created_at)
    )
    return _distinct_tasks(db, stmt)


def _tasks_blocked_in_week(
    db: Session, user: User, utc_start: dt.datetime, utc_end: dt.datetime
) -> list[Task]:
    """规则 3：本周内标记过 BLOCKED 的任务。"""
    stmt = (
        select(Task)
        .join(TaskStatusLog, TaskStatusLog.task_id == Task.id)
        .where(
            _participant_condition(user),
            TaskStatusLog.to_status == TaskStatus.BLOCKED,
            TaskStatusLog.created_at >= utc_start,
            TaskStatusLog.created_at <= utc_end,
        )
        .order_by(TaskStatusLog.created_at)
    )
    tasks = _distinct_tasks(db, stmt)
    # 已经解除阻塞且已完成的不重复占用风险段
    return [t for t in tasks if t.status not in CLOSED_STATUSES]


def _tasks_in_progress(
    db: Session, user: User, utc_start: dt.datetime, utc_end: dt.datetime
) -> list[Task]:
    """规则 2：当前 IN_PROGRESS，或本周有流水且仍未关闭的任务。"""
    has_log = (
        select(TaskStatusLog.id)
        .where(
            TaskStatusLog.task_id == Task.id,
            TaskStatusLog.created_at >= utc_start,
            TaskStatusLog.created_at <= utc_end,
        )
        .exists()
    )
    stmt = select(Task).where(
        _participant_condition(user),
        or_(Task.status == TaskStatus.IN_PROGRESS, has_log),
        Task.status.notin_(CLOSED_STATUSES),
    )
    return _distinct_tasks(db, stmt)


def _tasks_due_next_week(db: Session, user: User, week_start: dt.date) -> list[Task]:
    """规则 4a：未完成且截止日在下周的任务。"""
    ws = ensure_date(week_start)
    next_start = ws + dt.timedelta(days=7)
    next_end = week_end_of(next_start)
    stmt = select(Task).where(
        _participant_condition(user),
        Task.status.notin_(CLOSED_STATUSES),
        Task.due_date.isnot(None),
        Task.due_date >= next_start,
        Task.due_date <= next_end,
    )
    return _distinct_tasks(db, stmt)


def _carry_over_from_last_week(
    db: Session, *, user: User, week_start: dt.date, assigned: dict[int, ReportSection]
) -> list[tuple[int | None, str]]:
    """规则 4b：上周「下周计划」里带 task_id、且至今仍未完成的任务，顺延到本周计划。"""
    ws = ensure_date(week_start)
    prev_ws = previous_week_start(ws)
    prev_report = db.execute(
        select(WeeklyReport).where(
            WeeklyReport.user_id == user.id, WeeklyReport.week_start == prev_ws
        )
    ).scalar_one_or_none()
    if prev_report is None:
        return []

    candidates = [
        item.task_id
        for item in prev_report.items
        if item.section == ReportSection.PLAN and item.task_id is not None
    ]
    if not candidates:
        return []

    still_open = list(
        db.execute(
            select(Task).where(
                Task.id.in_(candidates),
                Task.status.notin_(CLOSED_STATUSES),
            )
        )
        .scalars()
        .all()
    )
    result = []
    for task in still_open:
        if task.id in assigned:
            continue
        assigned[task.id] = ReportSection.PLAN
        result.append((task.id, f"{task.title}（上周计划顺延）"))
    return result


# ----------------------------------------------------------------------
# 辅助
# ----------------------------------------------------------------------
def _distinct_tasks(db: Session, stmt) -> list[Task]:
    """执行查询并按 id 去重，保持原有顺序。

    所有传入的语句都以 ``Task`` 作为唯一实体，因此直接用 ``scalars()``；
    join 场景需配合 ``unique()`` 过滤重复主键。
    """
    rows = db.execute(stmt).unique().scalars().all()
    seen: set[int] = set()
    tasks: list[Task] = []
    for task in rows:
        if task.id in seen:
            continue
        seen.add(task.id)
        tasks.append(task)
    return tasks


def _load_projects(db: Session, project_ids: set[int]) -> dict[int, Project]:
    """批量加载项目，避免逐条查询（防 N+1）。"""
    if not project_ids:
        return {}
    rows = db.execute(select(Project).where(Project.id.in_(project_ids))).scalars().all()
    return {p.id: p for p in rows}


def _code(cache: dict[int, Project], project_id: int) -> str:
    project = cache.get(project_id)
    return project.code if project else "未归档"


def _last_remark(db: Session, task_id: int) -> str | None:
    """取该任务最近一条 BLOCKED 流水的备注作为阻塞说明。"""
    log = db.execute(
        select(TaskStatusLog)
        .where(TaskStatusLog.task_id == task_id, TaskStatusLog.to_status == TaskStatus.BLOCKED)
        .order_by(TaskStatusLog.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if log is None or not log.remark:
        return None
    return log.remark[:80]


def effective_plan_task_ids(report: WeeklyReport) -> list[int]:
    """周报 plan 段中关联的任务 ID（文中远期推算用，保持顺序去重）。"""
    seen: set[int] = set()
    ids: list[int] = []
    for item in report.items:
        if item.section == ReportSection.PLAN and item.task_id and item.task_id not in seen:
            seen.add(item.task_id)
            ids.append(item.task_id)
    return ids
