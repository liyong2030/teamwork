"""周报自动草稿生成测试 —— 覆盖四类并集规则与两个边界约束。"""

from __future__ import annotations

import datetime as dt

import pytest

from app.core.exceptions import ConflictStateError
from app.models.enums import ItemSource, ReportSection, ReportStatus, TaskStatus
from app.models.report import WeeklyReportItem
from app.schemas.report import ReportItemIn
from app.services import report_generator, report_service
from app.utils.week import LOCAL_TZ, week_start_of

from .conftest import (
    log_status,
    make_department,
    make_project,
    make_task,
    make_user,
)
from app.utils.week import to_utc


def _move_task_logs_to_last_week(db, task_id: int, week_start: dt.date) -> None:
    """把任务的初始创建流水挪到上一自然周，避免它被本周的「进行中」规则抢走。"""
    from sqlalchemy import update

    from app.models.project import TaskStatusLog

    last_week_local = dt.datetime.combine(
        week_start - dt.timedelta(days=4), dt.time(10, 0), tzinfo=LOCAL_TZ
    )
    db.execute(
        update(TaskStatusLog)
        .where(TaskStatusLog.task_id == task_id)
        .values(created_at=to_utc(last_week_local))
    )
    db.flush()


def _at(week_start: dt.date, day_offset: int, hour: int = 10) -> dt.datetime:
    """构造本周内某个时刻的 UTC naive 时间戳。"""
    local = dt.datetime.combine(
        week_start + dt.timedelta(days=day_offset), dt.time(hour, 0), tzinfo=LOCAL_TZ
    )
    return to_utc(local)


def test_generate_collects_four_sections(db, monday) -> None:
    dept = make_department(db, "测试部")
    user = make_user(db, "tester", department=dept)
    project = make_project(db, user, code="T-1")

    done = make_task(db, project, user, title="本周完成的任务")
    progress = make_task(db, project, user, title="进行中的任务")
    blocked = make_task(db, project, user, title="被阻塞的任务")
    # 明确落在"下周"区间内（monday+7 ~ monday+13），且创建流水放在上周
    planned = make_task(
        db, project, user, title="下周到期的任务", due_date=monday + dt.timedelta(days=9)
    )
    _move_task_logs_to_last_week(db, planned.id, monday)

    log_status(db, done, TaskStatus.DONE, operator=user, at=_at(monday, 1))
    log_status(db, progress, TaskStatus.IN_PROGRESS, operator=user, at=_at(monday, 1), progress=40)
    log_status(db, blocked, TaskStatus.BLOCKED, operator=user, at=_at(monday, 2), remark="等第三方联调")

    report = report_generator.generate_draft(db, user=user, week_start=monday)

    sections = {
        ReportSection.DONE: [i.content for i in report.section_items(ReportSection.DONE)],
        ReportSection.PROGRESS: [i.content for i in report.section_items(ReportSection.PROGRESS)],
        ReportSection.RISK: [i.content for i in report.section_items(ReportSection.RISK)],
        ReportSection.PLAN: [i.content for i in report.section_items(ReportSection.PLAN)],
    }
    assert any("本周完成的任务" in c for c in sections[ReportSection.DONE])
    assert any("进行中的任务" in c and "40%" in c for c in sections[ReportSection.PROGRESS])
    assert any("被阻塞的任务" in c and "等第三方联调" in c for c in sections[ReportSection.RISK])
    assert any("下周到期的任务" in c for c in sections[ReportSection.PLAN])
    assert all(item.source == ItemSource.AUTO for item in report.items)


def test_each_task_appears_in_only_one_section(db, monday) -> None:
    """同一任务只能出现在优先级最高的一个段落，禁止重复计数。"""
    dept = make_department(db, "测试部")
    user = make_user(db, "tester2", department=dept)
    project = make_project(db, user, code="T-2")

    task = make_task(db, project, user, title="多段冲突任务")
    log_status(db, task, TaskStatus.BLOCKED, operator=user, at=_at(monday, 1))
    log_status(db, task, TaskStatus.IN_PROGRESS, operator=user, at=_at(monday, 2))
    log_status(db, task, TaskStatus.DONE, operator=user, at=_at(monday, 3))

    report = report_generator.generate_draft(db, user=user, week_start=monday)
    task_ids = [i.task_id for i in report.items if i.task_id == task.id]
    assert len(task_ids) == 1
    assert report.section_items(ReportSection.DONE)[0].task_id == task.id


def test_carry_over_from_last_week_plan(db, monday) -> None:
    """上周写下周计划的任务未完成时应顺延到本周。"""
    dept = make_department(db, "测试部")
    user = make_user(db, "tester3", department=dept)
    project = make_project(db, user, code="T-3")

    task = make_task(db, project, user, title="跨周任务")
    _move_task_logs_to_last_week(db, task.id, monday)

    prev_start = monday - dt.timedelta(days=7)
    prev_report = report_generator.get_or_create_report(db, user=user, week_start=prev_start)
    db.add(
        WeeklyReportItem(
            report_id=prev_report.id,
            section=ReportSection.PLAN,
            content="计划完成跨周任务",
            task_id=task.id,
            source=ItemSource.MANUAL,
            sort_order=0,
        )
    )
    db.flush()

    report = report_generator.generate_draft(db, user=user, week_start=monday)
    plan_texts = [i.content for i in report.section_items(ReportSection.PLAN)]
    assert any("跨周任务" in text and "顺延" in text for text in plan_texts)


def test_collaborator_also_gets_the_task(db, monday) -> None:
    """协作人的周报草稿里也应出现该任务。"""
    dept = make_department(db, "测试部")
    owner = make_user(db, "owner", department=dept)
    partner = make_user(db, "partner", department=dept)
    project = make_project(db, owner, code="T-4")

    from app.models.project import TaskCollaborator

    task = make_task(db, project, owner, title="协作任务")
    db.add(TaskCollaborator(task_id=task.id, user_id=partner.id))
    log_status(db, task, TaskStatus.DONE, operator=owner, at=_at(monday, 1))
    db.flush()

    report = report_generator.generate_draft(db, user=partner, week_start=monday)
    assert any("协作任务" in i.content for i in report.section_items(ReportSection.DONE))


def test_force_regenerate_keeps_manual_items(db, monday) -> None:
    """force 重建时只清理自动条目，人工补充的内容必须保留。"""
    dept = make_department(db, "测试部")
    user = make_user(db, "tester5", department=dept)
    project = make_project(db, user, code="T-5")

    task = make_task(db, project, user, title="自动任务")
    log_status(db, task, TaskStatus.DONE, operator=user, at=_at(monday, 1))

    report = report_generator.generate_draft(db, user=user, week_start=monday)
    db.add(
        WeeklyReportItem(
            report_id=report.id,
            section=ReportSection.RISK,
            content="我手写的一条风险",
            task_id=None,
            source=ItemSource.MANUAL,
            sort_order=99,
        )
    )
    db.flush()

    report = report_generator.generate_draft(db, user=user, week_start=monday, force=True)
    manuals = [i for i in report.items if i.source == ItemSource.MANUAL]
    assert len(manuals) == 1
    assert manuals[0].content == "我手写的一条风险"
    # 自动条目不会因为 force 而翻倍
    autos = [i for i in report.items if i.source == ItemSource.AUTO and i.task_id == task.id]
    assert len(autos) == 1


def test_cannot_generate_after_submit(db, monday) -> None:
    """提交后周报锁定，再生成草稿必须报错，强制走修订流程。"""
    dept = make_department(db, "测试部")
    user = make_user(db, "tester6", department=dept)
    project = make_project(db, user, code="T-6")
    make_task(db, project, user, title="任务")

    report = report_service.submit_report(
        db,
        report=report_generator.get_or_create_report(db, user=user, week_start=monday),
        items=[
            ReportItemIn(
                section=ReportSection.DONE, content="本周完成了核心模块的开发与联调工作"
            ),
            ReportItemIn(
                section=ReportSection.PLAN, content="下周推进灰度发布方案并完成压力测试脚本"
            ),
        ],
        actor=user,
    )
    assert report.is_locked

    with pytest.raises(ConflictStateError):
        report_generator.generate_draft(db, user=user, week_start=monday)


def test_data_slice_does_not_leak_next_monday_changes(db, monday) -> None:
    """数据切片不变性：生成时刻在下周一，内容仍只含本自然周的事实。"""
    dept = make_department(db, "测试部")
    user = make_user(db, "tester7", department=dept)
    project = make_project(db, user, code="T-7")

    task = make_task(db, project, user, title="周一才完成的任务")
    # 该流水落在下周一，超出本自然周范围，不应出现在草稿里
    log_status(db, task, TaskStatus.DONE, operator=user, at=_at(monday, 7, hour=10))

    report = report_generator.generate_draft(db, user=user, week_start=monday)
    assert not [i for i in report.section_items(ReportSection.DONE) if i.task_id == task.id]


def test_one_report_per_user_per_week(db, monday) -> None:
    dept = make_department(db, "测试部")
    user = make_user(db, "tester8", department=dept)
    first = report_generator.get_or_create_report(db, user=user, week_start=monday)
    second = report_generator.get_or_create_report(db, user=user, week_start=monday)
    assert first.id == second.id
