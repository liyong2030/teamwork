"""统计相关 Schema。

口径定义（与《需求规格说明书》第 6 章一致，变更需同步评审）：
- 准时率 = 准时数 / 应提交数（分母固定）
- 提交率 = (准时 + 迟到 + 补交 + 代交) / 应提交数
- 补交永不回填 missing_count
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from app.schemas.common import ORMModel


class StatsQuery(BaseModel):
    """统计查询参数。"""

    week_start: dt.date | None = None
    department_id: int | None = None
    user_id: int | None = None
    weeks: int = 12


class CountBreakdown(BaseModel):
    """各状态计数明细。"""

    required: int = 0
    exempt: int = 0
    submitted: int = 0
    ontime: int = 0
    late: int = 0
    makeup: int = 0
    missing: int = 0
    by_proxy: int = 0
    valid: int = 0


class OverviewOut(CountBreakdown):
    """统计概览（含比率）。"""

    week_start: dt.date | None = None
    week_label: str | None = None
    ontime_rate: float = 0.0
    submit_rate: float = 0.0
    missing_rate: float = 0.0
    valid_rate: float = 0.0
    finalized: bool = False


class DepartmentRowOut(CountBreakdown):
    """部门横向对比行。"""

    department_id: int
    department_name: str
    ontime_rate: float = 0.0
    submit_rate: float = 0.0


class TrendPointOut(BaseModel):
    """趋势图的一个点。"""

    week_start: dt.date
    week_label: str
    required: int = 0
    ontime: int = 0
    late: int = 0
    makeup: int = 0
    missing: int = 0
    by_proxy: int = 0
    ontime_rate: float = 0.0
    submit_rate: float = 0.0


class PersonRowOut(BaseModel):
    """个人明细行。"""

    user_id: int
    username: str
    full_name: str
    department_name: str | None = None
    required: bool = True
    exempt_reason: str | None = None
    status: str = "missing"
    status_label: str = "未提交"
    submitted_at: str | None = None
    is_valid: bool = False
    continuous_missing: int = 0


class SnapshotOut(ORMModel):
    id: int
    week_start: dt.date
    department_id: int
    department_name: str | None = None
    required_count: int = 0
    exempt_count: int = 0
    submitted_count: int = 0
    ontime_count: int = 0
    late_count: int = 0
    makeup_count: int = 0
    missing_count: int = 0
    by_proxy_count: int = 0
    valid_count: int = 0
    finalized: bool = False
    computed_at: dt.datetime
    ontime_rate: float = 0.0
    submit_rate: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class ExportRequest(BaseModel):
    week_start: dt.date | None = None
    department_id: int | None = None
    fmt: str = "xlsx"  # xlsx | csv
