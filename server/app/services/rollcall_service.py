"""周报点名名册服务 —— 「应提交人数」的唯一依据。

生成时机：每周一 00:00（由定时任务触发），也可由管理员手动补生成。

规则：
1. 逐个遍历启用中的部门，把在册在职成员写入名册；
2. 本周有 **已审批** 请假（区间与本周相交）的成员 ``required=False``，计入豁免；
3. 名册一旦生成，即使后续人员调岗 / 离职，**本周分母保持不变**。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.organization import Department, DepartmentMember, User
from app.models.report import WeeklyRollCall
from app.services import auth_service
from app.utils.week import (
    ensure_date,
    iso_year_week,
    localnow,
    week_end_of,
)

logger = get_logger(__name__)


def generate_week_roll_call(
    db: Session, week_start: dt.date | None = None, *, overwrite: bool = False
) -> int:
    """生成某一自然周的点名名册。

    :param overwrite: True 时先清除该周既有名册（用于重跑）
    :return: 写入的名册条数
    """
    ws = ensure_date(week_start or auth_service.current_local_date())
    ws = _monday_of(ws)

    if overwrite:
        db.execute(delete(WeeklyRollCall).where(WeeklyRollCall.week_start == ws))
        db.flush()

    existing = {
        (rc.user_id, rc.department_id)
        for rc in db.execute(
            select(WeeklyRollCall).where(WeeklyRollCall.week_start == ws)
        ).scalars()
    }

    year, week_no = iso_year_week(ws)
    we = week_end_of(ws)
    count = 0

    departments = list(
        db.execute(
            select(Department).where(Department.is_active.is_(True)).order_by(Department.sort_order)
        )
        .scalars()
        .all()
    )
    if not departments:
        return 0

    member_rows = list(
        db.execute(
            select(DepartmentMember)
            .where(DepartmentMember.department_id.in_([d.id for d in departments]))
        )
        .scalars()
        .all()
    )
    user_ids = sorted({row.user_id for row in member_rows})
    leaves = auth_service.list_active_leaves_in_week(db, user_ids=user_ids, week_start=ws)
    user_map = {
        user.id: user
        for user in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
    }

    for row in member_rows:
        user = user_map.get(row.user_id)
        if user is None or not user.is_active:
            continue  # 离职人员不进入名册
        key = (row.user_id, row.department_id)
        if key in existing:
            continue

        leave = leaves.get(row.user_id)
        exempt = leave is not None
        db.add(
            WeeklyRollCall(
                week_start=ws,
                year=year,
                week_no=week_no,
                user_id=row.user_id,
                department_id=row.department_id,
                required=not exempt,
                exempt_type="leave" if exempt else None,
                exempt_reason=(
                    f"已审批请假 {leave.start_date.isoformat()} ~ {leave.end_date.isoformat()}"
                    if leave
                    else None
                ),
            )
        )
        existing.add(key)
        count += 1

    db.flush()
    logger.info("生成 %s 周的点名名册，共 %s 条", ws.isoformat(), count)
    return count


def _monday_of(day: dt.date) -> dt.date:
    """把任意日期对齐到所在自然周的周一。"""
    return ensure_date(day) - dt.timedelta(days=ensure_date(day).weekday())


def ensure_roll_call(db: Session, week_start: dt.date) -> int:
    """确保指定周的名册存在；不存在时即时补生成（幂等）。"""
    ws = _monday_of(week_start)
    has = db.execute(
        select(WeeklyRollCall.id).where(WeeklyRollCall.week_start == ws).limit(1)
    ).first()
    if has:
        return 0
    return generate_week_roll_call(db, ws)


def roll_call_rows(
    db: Session, week_start: dt.date, department_id: int | None = None
) -> list[WeeklyRollCall]:
    """查询指定周（可指定部门）的名册条目。"""
    ws = _monday_of(week_start)
    stmt = select(WeeklyRollCall).where(WeeklyRollCall.week_start == ws)
    if department_id is not None:
        stmt = stmt.where(WeeklyRollCall.department_id == department_id)
    return list(db.execute(stmt.order_by(WeeklyRollCall.id)).scalars().all())


def department_ids_of_week(db: Session, week_start: dt.date) -> list[int]:
    """该周名册中出现的全部部门 ID（去重）。"""
    ws = _monday_of(week_start)
    rows = db.execute(
        select(WeeklyRollCall.department_id).where(WeeklyRollCall.week_start == ws).distinct()
    ).all()
    return sorted({row[0] for row in rows})


def required_user_ids(db: Session, week_start: dt.date, department_id: int) -> list[int]:
    """某周某部门需要提交周报的用户 ID。"""
    return [
        rc.user_id for rc in roll_call_rows(db, week_start, department_id) if rc.required
    ]


def now_local() -> dt.datetime:
    """当前本地时间（便于测试注入）。"""
    return localnow()
