"""时区与自然周计算工具 —— 周报所有口径的时间基准唯一入口。

约定：
1. 数据库统一存储 **UTC naive datetime**（不带 tzinfo），在应用层转换；
2. 所有"周"的业务主键是 **`week_start`，即该周周一的本地日期**；
3. 时间比较一律在 aware datetime（本地时区）上进行，避免 naive/aware 混用报错。
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from app.core.config import settings

LOCAL_TZ = ZoneInfo(settings.tz)


# ----------------------------------------------------------------------
# 基础时间函数
# ----------------------------------------------------------------------
def utcnow() -> dt.datetime:
    """当前 UTC 时间（naive，直接入库）。"""
    return dt.datetime.now(tz=dt.timezone.utc).replace(tzinfo=None)


def localnow() -> dt.datetime:
    """当前本地时间（aware）。"""
    return dt.datetime.now(tz=LOCAL_TZ)


def today_local() -> dt.date:
    """当前本地日期。"""
    return localnow().date()


def to_local(moment: dt.datetime) -> dt.datetime:
    """数据库 UTC naive 时间 → 本地 aware 时间。"""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=dt.timezone.utc).astimezone(LOCAL_TZ)
    return moment.astimezone(LOCAL_TZ)


def to_utc(moment: dt.datetime) -> dt.datetime:
    """任意 aware 时间 → UTC naive 时间（入库用）。"""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=LOCAL_TZ).astimezone(dt.timezone.utc).replace(tzinfo=None)
    return moment.astimezone(dt.timezone.utc).replace(tzinfo=None)


def ensure_date(value: dt.date | dt.datetime) -> dt.date:
    """把 date / datetime 归一化为 date。"""
    if isinstance(value, dt.datetime):
        return value.date()
    return value


# ----------------------------------------------------------------------
# 自然周计算
# ----------------------------------------------------------------------
def week_start_of(day: dt.date | dt.datetime) -> dt.date:
    """取任意一天所在自然周的周一。"""
    day = ensure_date(day)
    return day - dt.timedelta(days=day.weekday())


def current_week_start() -> dt.date:
    """当前所在自然周的周一。"""
    return week_start_of(today_local())


def previous_week_start(week_start: dt.date) -> dt.date:
    """上一自然周的周一。"""
    return ensure_date(week_start) - dt.timedelta(days=7)


def next_week_start(week_start: dt.date) -> dt.date:
    """下一自然周的周一。"""
    return ensure_date(week_start) + dt.timedelta(days=7)


def week_end_of(week_start: dt.date) -> dt.date:
    """自然周的周日。"""
    return ensure_date(week_start) + dt.timedelta(days=6)


def iso_year_week(week_start: dt.date) -> tuple[int, int]:
    """返回 ISO 年与周序号（取该周的周四保证跨年正确）。"""
    thursday = ensure_date(week_start) + dt.timedelta(days=3)
    iso = thursday.isocalendar()
    return iso[0], iso[1]


def parse_time(text: str) -> dt.time:
    """解析 HH:MM 字符串。"""
    hour, minute = text.split(":")[:2]
    return dt.time(int(hour), int(minute))


def week_range_local(week_start: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """自然周的 [周一 00:00:00, 周日 23:59:59.999999]（本地 aware）。"""
    start = dt.datetime.combine(ensure_date(week_start), dt.time.min, tzinfo=LOCAL_TZ)
    end = dt.datetime.combine(week_end_of(week_start), dt.time.max, tzinfo=LOCAL_TZ)
    return start, end


def week_range_utc(week_start: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """自然周区间（UTC naive，用于直接对数据库列做 BETWEEN）。"""
    start, end = week_range_local(week_start)
    return to_utc(start), to_utc(end)


def deadline_of(week_start: dt.date) -> dt.datetime:
    """本周周报提交的**准时截止时刻**（本地 aware）：默认周五 18:00。"""
    day = ensure_date(week_start) + dt.timedelta(days=settings.report_deadline_weekday - 1)
    return dt.datetime.combine(day, parse_time(settings.report_deadline_time), tzinfo=LOCAL_TZ)


def finalize_of(week_start: dt.date) -> dt.datetime:
    """本周周报的**定版时刻**（本地 aware）：默认下周一 09:30。"""
    day = (
        ensure_date(week_start)
        + dt.timedelta(days=7)
        + dt.timedelta(days=settings.report_finalize_weekday - 1)
    )
    return dt.datetime.combine(day, parse_time(settings.report_finalize_time), tzinfo=LOCAL_TZ)


def is_week_finalized(week_start: dt.date, now: dt.datetime | None = None) -> bool:
    """该周是否已到定版时刻。"""
    moment = now or localnow()
    if moment.tzinfo is None:
        moment = to_local(moment)
    return moment > finalize_of(week_start)


def classify_submission(
    week_start: dt.date, submitted_at: dt.datetime | None
) -> str:
    """根据提交时刻判定周报状态（不含缺交/代交）。

    :return: ``ontime`` | ``late`` | ``after_finalize``
    """
    if submitted_at is None:
        return "after_finalize"
    moment = submitted_at if submitted_at.tzinfo else to_local(submitted_at)
    deadline = deadline_of(week_start)
    finalize = finalize_of(week_start)
    if moment <= deadline:
        return "ontime"
    if moment <= finalize:
        return "late"
    return "after_finalize"


def week_label(week_start: dt.date) -> str:
    """人类可读的周标签：``2026-10-19 ~ 2026-10-25（第43周）``。"""
    ws = ensure_date(week_start)
    year, week_no = iso_year_week(ws)
    return f"{ws.isoformat()} ~ {week_end_of(ws).isoformat()}（第{week_no}周）"


def recent_week_starts(count: int, end_week: dt.date | None = None) -> list[dt.date]:
    """生成最近 count 个自然周的周一列表（升序），用于趋势图。"""
    last = ensure_date(end_week) if end_week else current_week_start()
    return [last - dt.timedelta(days=7 * i) for i in range(count - 1, -1, -1)]
