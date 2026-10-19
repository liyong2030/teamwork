"""保存草稿的边界：未提交自由保存 / 已提交可暂存但必须留痕 / 定版后一律拒绝。"""

from __future__ import annotations

import datetime as dt

import pytest

from app.core.exceptions import ConflictStateError
from app.models.enums import ReportSection, ReportStatus
from app.schemas.report import ReportItemIn
from app.services import report_generator, report_service
from app.utils.week import LOCAL_TZ, week_start_of

from .conftest import make_user

VALID_ITEMS = [
    ReportItemIn(section=ReportSection.DONE, content="本周完成了核心模块的接口开发与联调"),
    ReportItemIn(section=ReportSection.PLAN, content="下周计划完成灰度发布与压力测试脚本编写"),
]

CHANGED_ITEMS = [
    ReportItemIn(section=ReportSection.DONE, content="补充：接口已联调完成并补充了异常用例覆盖"),
    ReportItemIn(section=ReportSection.PLAN, content="下周计划完成灰度发布与压力测试脚本编写"),
]


@pytest.fixture
def frozen_now(monkeypatch, monday):
    """冻结在本周三 10:00，使首次提交稳定判定为「准时」。"""
    fixed = dt.datetime.combine(monday + dt.timedelta(days=2), dt.time(10, 0), tzinfo=LOCAL_TZ)
    monkeypatch.setattr(report_service, "localnow", lambda: fixed)
    return fixed


def test_draft_saved_freely_before_submit(db, monday) -> None:
    """未提交时反复保存：内容更新、不产生版本、不留痕。"""
    user = make_user(db, "u1")
    report_service.save_draft(db, user=user, week_start=monday, items=VALID_ITEMS)
    db.flush()

    report = report_service.get_user_report(db, user.id, monday)
    assert report is not None
    assert report.status == ReportStatus.DRAFT
    assert report.version == 1
    assert not report.revisions

    report_service.save_draft(db, user=user, week_start=monday, items=CHANGED_ITEMS)
    db.flush()
    assert report.section_items(ReportSection.DONE)[0].content == CHANGED_ITEMS[0].content
    assert report.version == 1  # 草稿阶段不计版本


def test_save_draft_after_submit_keeps_status_and_leaves_trace(db, monday, frozen_now) -> None:
    """已提交后保存草稿：不再报错，内容落库 + 留痕，但提交状态不被改写。"""
    user = make_user(db, "u2")
    report = report_generator.get_or_create_report(db, user=user, week_start=monday)
    report_service.submit_report(db, report=report, items=VALID_ITEMS, actor=user)
    db.flush()
    assert report.status == ReportStatus.ONTIME
    assert report.submitted_at is not None
    version_at_submit = report.version

    # 旧行为会在这一步抛「周报已提交，请使用「修订」功能」
    saved = report_service.save_draft(db, user=user, week_start=monday, items=CHANGED_ITEMS)
    db.flush()

    assert saved.id == report.id
    assert saved.section_items(ReportSection.DONE)[0].content == CHANGED_ITEMS[0].content
    # 提交事实不变：准时就是准时，草稿改动不会把状态洗成别的
    assert saved.status == ReportStatus.ONTIME
    assert saved.submitted_at == report.submitted_at
    # 但内容改动必须留痕，且版本号递增
    assert saved.version == (version_at_submit or 1) + 1
    assert any("保存草稿" in (r.reason or "") for r in saved.revisions)


def test_save_draft_rejected_after_finalize(db) -> None:
    """定版后的周报口径冻结，任何改动都必须拒绝。"""
    old_monday = week_start_of(dt.date.today()) - dt.timedelta(days=56)
    user = make_user(db, "u3")
    report = report_generator.get_or_create_report(db, user=user, week_start=old_monday)
    report.submitted_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    db.flush()

    with pytest.raises(ConflictStateError, match="已定版"):
        report_service.save_draft(db, user=user, week_start=old_monday, items=VALID_ITEMS)
