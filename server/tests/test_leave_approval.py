"""请假审批权限：组长可批本部门成员、不能批自己的、跨部门与成员越权一律拒绝。"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError
from app.models.enums import LeaveStatus
from app.models.organization import LeaveRequest, User
from app.services import permission

from .conftest import make_department, make_user


def _make_leave(db: Session, user: User, offset: int = 0) -> LeaveRequest:
    start = dt.date.today() + dt.timedelta(days=offset)
    leave = LeaveRequest(
        user_id=user.id,
        start_date=start,
        end_date=start + dt.timedelta(days=2),
        reason="年假",
        status=LeaveStatus.pending,
    )
    db.add(leave)
    db.flush()
    return leave


def _team(db: Session):
    dept = make_department(db, "研发部")
    leader = make_user(db, "leader", department=dept, is_leader=True)
    member = make_user(db, "member", department=dept)
    other_dept = make_department(db, "市场部")
    outsider = make_user(db, "outsider", department=other_dept)
    admin = make_user(db, "admin", is_superuser=True)
    return dept, leader, member, outsider, admin


def test_leader_can_decide_own_member(db: Session) -> None:
    _, leader, member, _, _ = _team(db)
    assert permission.can_decide_leave(leader, member) is True


def test_leader_cannot_decide_self(db: Session) -> None:
    """组长不能审批自己的请假，否则豁免可以自批自销。"""
    _, leader, _, _, _ = _team(db)
    assert permission.can_decide_leave(leader, leader) is False
    with pytest.raises(ForbiddenError, match="不能审批自己的请假申请"):
        permission.assert_can_decide_leave(leader, leader)


def test_leader_cannot_decide_other_department(db: Session) -> None:
    _, leader, _, outsider, _ = _team(db)
    assert permission.can_decide_leave(leader, outsider) is False
    with pytest.raises(ForbiddenError):
        permission.assert_can_decide_leave(leader, outsider)


def test_member_cannot_decide_anything(db: Session) -> None:
    _, _, member, outsider, _ = _team(db)
    assert permission.can_decide_leave(member, outsider) is False
    assert permission.can_decide_leave(member, member) is False


def test_admin_can_decide_anyone_including_self(db: Session) -> None:
    """管理员可批任何人，**含自己**。

    组长被禁止自批是因为其上方还有管理员兜底；管理员已是最高权限，
    若一并禁止，单人部署时会出现"无人可批"的死锁。该操作照常写审计日志。
    """
    _, _, member, outsider, admin = _team(db)
    assert permission.can_decide_leave(admin, member) is True
    assert permission.can_decide_leave(admin, outsider) is True
    assert permission.can_decide_leave(admin, admin) is True


def test_serialized_action_flags(db: Session) -> None:
    """列表序列化必须给出动作位，前端据此渲染按钮（避免按钮点了 403）。"""
    from app.api.v1.leaves import _serialize

    _, leader, member, _, _ = _team(db)
    mine = _make_leave(db, member)
    own = _make_leave(db, leader, offset=5)
    db.flush()

    as_leader = _serialize(mine, viewer=leader)
    assert as_leader["can_decide"] is True
    assert as_leader["can_cancel"] is False  # 别人的申请不能由组长撤回

    as_owner = _serialize(mine, viewer=member)
    assert as_owner["can_decide"] is False
    assert as_owner["can_cancel"] is True  # 自己的可以撤回

    # 已审批通过的不再可撤回，也不再可审批
    mine.status = LeaveStatus.approved
    db.flush()
    again = _serialize(mine, viewer=leader)
    assert again["can_decide"] is False
    assert again["can_cancel"] is False

    # 组长自己的申请：不能自批，但可以撤回
    self_row = _serialize(own, viewer=leader)
    assert self_row["can_decide"] is False
    assert self_row["can_cancel"] is True

    # 管理员自批不在禁止范围内（避免单人部署死锁）
    admin_row = _serialize(own, viewer=make_user(db, "boss", is_superuser=True))
    assert admin_row["can_decide"] is True


def test_approver_name_is_exposed(db: Session) -> None:
    from app.api.v1.leaves import _serialize

    _, leader, member, _, _ = _team(db)
    leave = _make_leave(db, member)
    leave.status = LeaveStatus.approved
    leave.approver_id = leader.id
    leave.decided_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    db.flush()

    row = _serialize(leave, viewer=leader)
    assert row["approver_name"] == leader.full_name
    assert row["full_name"] == member.full_name
