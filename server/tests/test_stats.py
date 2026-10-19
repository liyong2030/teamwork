"""统计口径测试 —— 重点是「补交永不洗白」这条审计底线。"""

from __future__ import annotations

import datetime as dt

import pytest

from app.models.enums import LeaveStatus, ReportSection, ReportStatus
from app.models.organization import LeaveRequest
from app.schemas.report import ReportItemIn
from app.services import report_generator, report_service, rollcall_service, stats_service
from app.utils.week import LOCAL_TZ, week_start_of

from .conftest import make_department, make_project, make_task, make_user

VALID_ITEMS = [
    ReportItemIn(section=ReportSection.DONE, content="本周完成了核心模块的接口开发与联调"),
    ReportItemIn(section=ReportSection.PLAN, content="下周计划完成灰度发布与压力测试脚本编写"),
]


@pytest.fixture
def frozen_now(monkeypatch, monday):
    """把服务层的"当前时间"固定在本周三 10:00，使提交被判定为**准时**。

    提交状态取决于真实时钟，测试必须冻结时间才能保证幂等。
    """
    fixed = dt.datetime.combine(monday + dt.timedelta(days=2), dt.time(10, 0), tzinfo=LOCAL_TZ)
    monkeypatch.setattr(report_service, "localnow", lambda: fixed)
    return fixed


def _seed_team(db, count: int = 3) -> tuple:
    dept = make_department(db, "统计部")
    leader = make_user(db, "leader", department=dept, is_leader=True)
    members = [make_user(db, f"m{i}", department=dept) for i in range(count)]
    return dept, leader, members


def test_roll_call_excludes_approved_leave(db, monday) -> None:
    dept, _leader, members = _seed_team(db, count=3)
    db.add(
        LeaveRequest(
            user_id=members[0].id,
            start_date=monday,
            end_date=monday + dt.timedelta(days=4),
            reason="年假",
            status=LeaveStatus.approved,
        )
    )
    db.flush()

    count = rollcall_service.generate_week_roll_call(db, monday)
    assert count == 4  # leader + 3 members

    rows = rollcall_service.roll_call_rows(db, monday, dept.id)
    required = sorted(r.user_id for r in rows if r.required)
    assert members[0].id not in required
    assert members[1].id in required
    assert members[2].id in required


def test_pending_leave_does_not_exempt(db, monday) -> None:
    """只有 approved 的请假才参与豁免，pending 一律不算。"""
    dept, _leader, members = _seed_team(db, count=1)
    db.add(
        LeaveRequest(
            user_id=members[0].id,
            start_date=monday,
            end_date=monday + dt.timedelta(days=2),
            status=LeaveStatus.pending,
        )
    )
    db.flush()

    rollcall_service.generate_week_roll_call(db, monday)
    rows = rollcall_service.roll_call_rows(db, monday, dept.id)
    target = next(r for r in rows if r.user_id == members[0].id)
    assert target.required is True


def test_counts_before_submit(db, monday) -> None:
    dept, _leader, members = _seed_team(db, count=3)
    rollcall_service.generate_week_roll_call(db, monday)

    counts = stats_service.compute_department_counts(db, monday, dept.id)
    assert counts.required == 4  # leader + 3 members
    assert counts.submitted == 0
    assert counts.missing == 4


def test_overview_rates(db, monday, frozen_now) -> None:
    dept, leader, members = _seed_team(db, count=3)
    rollcall_service.generate_week_roll_call(db, monday)

    for member in members[:2]:
        report = report_generator.get_or_create_report(db, user=member, week_start=monday)
        submitted = report_service.submit_report(db, report=report, items=VALID_ITEMS, actor=member)
        assert submitted.status == ReportStatus.ONTIME
    db.flush()

    data = stats_service.overview(db, week_start=monday, department_ids=[dept.id])
    assert data["required"] == 4  # leader + 3 members
    assert data["ontime"] == 2
    assert data["late"] == 0
    assert data["missing"] == 2
    assert data["ontime_rate"] == 50.0
    assert data["submit_rate"] == 50.0


def test_finalize_freezes_and_makeup_never_rewrites_missing(db, monday, frozen_now) -> None:
    """审计底线：定版后补交只增加 makeup，已冻结快照的 missing/ontime 一律不变。"""
    dept, leader, members = _seed_team(db, count=2)
    rollcall_service.generate_week_roll_call(db, monday)

    # 只有第一位成员按时提交
    first = members[0]
    report = report_generator.get_or_create_report(db, user=first, week_start=monday)
    report_service.submit_report(db, report=report, items=VALID_ITEMS, actor=first)
    db.flush()

    snapshots = stats_service.finalize_week(db, monday)
    snapshot = next(s for s in snapshots if s.department_id == dept.id)
    assert snapshot.finalized is True
    assert snapshot.required_count == 3   # leader + 2 members
    assert snapshot.ontime_count == 1
    assert snapshot.missing_count == 2
    assert snapshot.makeup_count == 0

    # 定版之后，第二位成员来补交
    second = members[1]
    late_report = report_generator.get_or_create_report(db, user=second, week_start=monday)
    late_report.status = ReportStatus.MISSING  # 模拟定版任务写入的缺交状态
    db.flush()
    submitted = report_service.submit_report(
        db, report=late_report, items=VALID_ITEMS, actor=second
    )
    assert submitted.status == ReportStatus.MAKEUP

    # 再次触发定版（默认 force=False）不应改写已冻结的快照
    again = stats_service.finalize_week(db, monday)
    snapshot = next(s for s in again if s.department_id == dept.id)
    assert snapshot.missing_count == 2, "缺交数被后续补交洗白了，违反不可审计要求"
    assert snapshot.makeup_count == 0
    assert snapshot.ontime_count == 1

    # 只有显式 force=True 才允许重算（排障/数据订正场景）
    forced = stats_service.finalize_week(db, monday, force=True)
    snapshot = next(s for s in forced if s.department_id == dept.id)
    assert snapshot.missing_count == 1
    assert snapshot.makeup_count == 1
    assert snapshot.submitted_count == 2


def test_proxy_submit_counts_independently(db, monday) -> None:
    dept, leader, members = _seed_team(db, count=1)
    rollcall_service.generate_week_roll_call(db, monday)

    target = members[0]
    report = report_generator.get_or_create_report(db, user=target, week_start=monday)
    report_service.submit_report(
        db, report=report, items=VALID_ITEMS, actor=leader, proxy_reason="成员出差"
    )
    db.flush()

    counts = stats_service.compute_department_counts(db, monday, dept.id)
    assert counts.by_proxy == 1
    assert counts.ontime == 0
    assert counts.submitted == 1


def test_invalid_report_flagged(db, monday) -> None:
    """字数不足的周报应被标记为无效，但仍计入已提交。"""
    dept, _leader, members = _seed_team(db, count=1)
    rollcall_service.generate_week_roll_call(db, monday)

    member = members[0]
    report = report_generator.get_or_create_report(db, user=member, week_start=monday)
    report_service.submit_report(
        db,
        report=report,
        items=[ReportItemIn(section=ReportSection.DONE, content="摸鱼")],
        actor=member,
    )
    db.flush()

    assert report.is_valid is False
    assert report.invalid_reason is not None

    counts = stats_service.compute_department_counts(db, monday, dept.id)
    assert counts.submitted == 1
    assert counts.valid == 0


def test_people_includes_exempt_members(db, monday) -> None:
    dept, leader, members = _seed_team(db, count=2)
    db.add(
        LeaveRequest(
            user_id=members[0].id,
            start_date=monday,
            end_date=monday + dt.timedelta(days=1),
            status=LeaveStatus.approved,
        )
    )
    db.flush()
    rollcall_service.generate_week_roll_call(db, monday)

    rows = stats_service.people(db, week_start=monday, department_id=dept.id)
    exempt = [r for r in rows if not r["required"]]
    assert len(exempt) == 1
    assert exempt[0]["user_id"] == members[0].id
    assert exempt[0]["status_label"] == "豁免"


def test_trend_reads_snapshot_first(db, monday) -> None:
    dept, _leader, members = _seed_team(db, count=1)
    rollcall_service.generate_week_roll_call(db, monday)
    stats_service.finalize_week(db, monday)

    rows = stats_service.trend(db, weeks=4, department_ids=[dept.id])
    assert len(rows) == 4
    current = [r for r in rows if r["week_start"] == monday][0]
    assert current["required"] == 2
    assert current["missing"] == 2
    assert current["ontime_rate"] == 0.0


def test_week_start_is_monday_in_stats(db, monday) -> None:
    """统计入口必须把任意日期对齐到周一，避免跨调用口径漂移。"""
    assert week_start_of(dt.date(2026, 10, 18)) == week_start_of(dt.date(2026, 10, 12))
    dept, _leader, members = _seed_team(db, count=1)
    rollcall_service.generate_week_roll_call(db, monday)
    data = stats_service.overview(db, week_start=monday + dt.timedelta(days=3), department_ids=[dept.id])
    assert data["week_start"] == monday


def test_project_and_task_counters(db, monday) -> None:
    from app.services import task_service

    dept, leader, members = _seed_team(db, count=1)
    project = make_project(db, leader, code="P-9")
    make_task(db, project, members[0], title="A", due_date=dt.date.today() - dt.timedelta(days=1))
    make_task(db, project, members[0], title="B")
    total, done, overdue = task_service.project_progress(db, project.id)
    assert (total, done, overdue) == (2, 0, 1)
