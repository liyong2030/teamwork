"""周报相关 Schema。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import ReportSection, ReportStatus
from app.schemas.common import ORMModel


class ReportItemIn(BaseModel):
    """周报条目入参（四段之一的一条）。"""

    section: ReportSection
    content: str
    task_id: int | None = None
    source: str = "manual"


class ReportItemOut(ORMModel):
    id: int
    report_id: int
    section: str
    content: str
    task_id: int | None = None
    task_title: str | None = None
    source: str
    sort_order: int = 0

    model_config = ConfigDict(from_attributes=True)


class ReportSections(BaseModel):
    """四段结构容器，供前端直接按段渲染。"""

    done: list[ReportItemOut] = []
    progress: list[ReportItemOut] = []
    risk: list[ReportItemOut] = []
    plan: list[ReportItemOut] = []


class GenerateDraftRequest(BaseModel):
    """生成周报草稿。

    ``force`` 为 True 时会用本周任务重新生成全部自动条目（人工条目保留）。
    """

    week_start: dt.date | None = None
    force: bool = False


class SaveDraftRequest(BaseModel):
    week_start: dt.date | None = None
    items: list[ReportItemIn] = []


class SubmitReportRequest(BaseModel):
    week_start: dt.date | None = None
    items: list[ReportItemIn] = []
    reason: str | None = None  # 修订时的修改原因


class ProxySubmitRequest(BaseModel):
    """组长/管理员代提交。"""

    user_id: int
    week_start: dt.date | None = None
    items: list[ReportItemIn] = []
    reason: str


class ReviewRequest(BaseModel):
    """组长审阅。"""

    comment: str | None = None
    approved: bool = True


class ReportOut(ORMModel):
    id: int
    user_id: int
    username: str | None = None
    full_name: str | None = None
    week_start: dt.date
    week_label: str | None = None
    year: int
    week_no: int
    status: str
    status_label: str | None = None
    version: int = 1
    submitted_at: dt.datetime | None = None
    last_edited_at: dt.datetime | None = None
    submitted_by_id: int | None = None
    submitted_by_name: str | None = None
    proxy_reason: str | None = None
    reviewed_by_id: int | None = None
    reviewed_at: dt.datetime | None = None
    review_comment: str | None = None
    is_valid: bool = False
    invalid_reason: str | None = None
    is_locked: bool = False
    items: list[ReportItemOut] = []
    sections: ReportSections | None = None
    char_count: int = 0
    created_at: dt.datetime
    updated_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


class ReportRevisionOut(ORMModel):
    id: int
    report_id: int
    version: int
    snapshot: dict[str, Any] = {}
    editor_id: int
    editor_name: str | None = None
    reason: str | None = None
    created_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


class MyWeekStatus(BaseModel):
    """「我的周报」当前状态卡片。"""

    week_start: dt.date
    week_label: str
    deadline_at: str
    finalize_at: str
    deadline_passed: bool = False
    has_report: bool = False
    report_id: int | None = None
    status: str = ReportStatus.DRAFT.value
    status_label: str = "未填写"
    submitted_at: str | None = None
    can_edit: bool = True
    can_generate: bool = True


class RollCallOut(ORMModel):
    id: int
    week_start: dt.date
    user_id: int
    full_name: str | None = None
    department_id: int
    required: bool = True
    exempt_type: str | None = None
    exempt_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)
