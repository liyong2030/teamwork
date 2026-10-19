"""自然周与时间口径测试 —— 这是全部统计的地基，必须严丝合缝。"""

from __future__ import annotations

import datetime as dt

from app.utils.week import (
    classify_submission,
    deadline_of,
    ensure_date,
    finalize_of,
    iso_year_week,
    localnow,
    next_week_start,
    previous_week_start,
    today_local,
    week_end_of,
    week_label,
    week_start_of,
)


def test_week_start_is_monday() -> None:
    # 2026-10-18 是周日
    assert week_start_of(dt.date(2026, 10, 18)) == dt.date(2026, 10, 12)
    assert week_start_of(dt.date(2026, 10, 12)) == dt.date(2026, 10, 12)
    assert week_start_of(dt.date(2026, 10, 17)) == dt.date(2026, 10, 12)


def test_week_end_is_sunday() -> None:
    assert week_end_of(dt.date(2026, 10, 12)) == dt.date(2026, 10, 18)


def test_prev_next_week() -> None:
    ws = dt.date(2026, 10, 12)
    assert previous_week_start(ws) == dt.date(2026, 10, 5)
    assert next_week_start(ws) == dt.date(2026, 10, 19)


def test_deadline_is_friday_1800() -> None:
    deadline = deadline_of(dt.date(2026, 10, 12))
    assert deadline.weekday() == 4  # 周五
    assert (deadline.hour, deadline.minute) == (18, 0)
    assert deadline.date() == dt.date(2026, 10, 16)


def test_finalize_is_next_monday_0930() -> None:
    finalize = finalize_of(dt.date(2026, 10, 12))
    assert finalize.date() == dt.date(2026, 10, 19)
    assert finalize.weekday() == 0  # 周一
    assert (finalize.hour, finalize.minute) == (9, 30)


def test_classify_ontime_late_after_finalize() -> None:
    ws = dt.date(2026, 10, 12)
    assert classify_submission(ws, None) == "after_finalize"
    # 周五 17:59 之前 → 准时
    ontime = dt.datetime(2026, 10, 16, 17, 59, tzinfo=deadline_of(ws).tzinfo)
    assert classify_submission(ws, ontime) == "ontime"
    # 周五 18:01 → 迟到
    late = dt.datetime(2026, 10, 16, 18, 1, tzinfo=deadline_of(ws).tzinfo)
    assert classify_submission(ws, late) == "late"
    # 周一 09:30 整 → 迟到（临界含等号）
    edge = dt.datetime(2026, 10, 19, 9, 30, tzinfo=deadline_of(ws).tzinfo)
    assert classify_submission(ws, edge) == "late"
    # 周一 09:31 → 定版后
    after = dt.datetime(2026, 10, 19, 9, 31, tzinfo=deadline_of(ws).tzinfo)
    assert classify_submission(ws, after) == "after_finalize"


def test_iso_week_and_label() -> None:
    year, week_no = iso_year_week(dt.date(2026, 10, 12))
    assert (year, week_no) == dt.date(2026, 10, 15).isocalendar()[0:2]
    label = week_label(dt.date(2026, 10, 12))
    assert "2026-10-12" in label and "2026-10-18" in label


def test_date_normalization_helpers() -> None:
    assert ensure_date(dt.date(2026, 1, 5)) == dt.date(2026, 1, 5)
    assert ensure_date(dt.datetime(2026, 1, 5, 8, 30)) == dt.date(2026, 1, 5)
    assert today_local() == localnow().date()
