"""请假接口 —— 周报豁免的唯一依据。

仅 ``approved`` 状态的请假会在生成点名名册时被扣减。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import case, select

from app.core.deps import CurrentUserDep, DbSession
from app.core.exceptions import AppError, ForbiddenError, NotFoundError
from app.models.enums import LeaveStatus
from app.models.organization import LeaveRequest, User
from app.schemas.auth import LeaveDecideRequest, LeaveRequestCreate
from app.schemas.common import MessageResponse
from app.services import audit, permission
from app.utils.week import utcnow

router = APIRouter(prefix="/leaves", tags=["请假"])


def _serialize(leave: LeaveRequest, viewer: User | None = None) -> dict[str, Any]:
    """序列化请假记录。

    附带 ``can_decide`` / ``can_cancel`` 两个动作位，前端据此渲染操作按钮，
    避免在前端重复实现一遍管辖范围判断（两端口径一旦漂移就会出现"按钮点了 403"）。
    """
    owner = leave.user
    can_decide = False
    can_cancel = False
    if viewer is not None:
        can_cancel = (leave.user_id == viewer.id or viewer.is_superuser) and (
            leave.status != LeaveStatus.approved
        )
        can_decide = (
            leave.status == LeaveStatus.pending
            and owner is not None
            and permission.can_decide_leave(viewer, owner)
        )

    return {
        "id": leave.id,
        "user_id": leave.user_id,
        "start_date": leave.start_date,
        "end_date": leave.end_date,
        "reason": leave.reason,
        "status": leave.status.value,
        "approver_id": leave.approver_id,
        "approver_name": leave.approver.full_name if leave.approver else None,
        "decided_at": leave.decided_at,
        "created_at": leave.created_at,
        "username": owner.username if owner else None,
        "full_name": owner.full_name if owner else None,
        "can_decide": can_decide,
        "can_cancel": can_cancel,
    }


@router.post("", response_model=MessageResponse, summary="提交请假")
def create_leave(
    payload: LeaveRequestCreate,
    request: Request,
    user: CurrentUserDep,
    db: DbSession,
) -> MessageResponse:
    leave = LeaveRequest(
        user_id=user.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        reason=payload.reason,
        status=LeaveStatus.pending,
    )
    db.add(leave)
    audit.record(
        db,
        action="leave.create",
        actor_id=user.id,
        target_type="leave_request",
        target_id=leave.id,
        detail={"start": str(payload.start_date), "end": str(payload.end_date)},
        request=request,
    )
    db.commit()
    return MessageResponse(message="请假已提交，等待组长审批", id=leave.id)


@router.get("", summary="请假列表")
def list_leaves(
    db: DbSession,
    user: CurrentUserDep,
    user_id: int | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    """管理员/组长看管辖范围；普通成员只能看自己的。

    组长返回的结果里同时包含本部门成员的申请，配合 ``can_decide`` 可直接渲染审批操作。
    """
    # 待审批的排在最前，其余按提交时间倒序（审批场景下更符合直觉）
    pending_first = case((LeaveRequest.status == LeaveStatus.pending, 0), else_=1)
    stmt = select(LeaveRequest).order_by(pending_first, LeaveRequest.created_at.desc())
    if user_id:
        stmt = stmt.where(LeaveRequest.user_id == user_id)
    if status:
        stmt = stmt.where(LeaveRequest.status == status)

    rows = db.execute(stmt.limit(limit)).scalars().all()
    result = []
    for leave in rows:
        if user.is_superuser or leave.user_id == user.id:
            result.append(leave)
            continue
        owner = db.get(User, leave.user_id)
        if owner and set(user.leader_department_ids) & set(owner.department_ids):
            result.append(leave)
    return [_serialize(l, viewer=user) for l in result]


@router.get("/{leave_id}", summary="请假详情")
def read_leave(leave_id: int, db: DbSession, user: CurrentUserDep) -> dict[str, Any]:
    leave = db.get(LeaveRequest, leave_id)
    if leave is None:
        raise NotFoundError("请假记录不存在")
    if not (user.is_superuser or leave.user_id == user.id):
        owner = db.get(User, leave.user_id)
        if not (owner and set(user.leader_department_ids) & set(owner.department_ids)):
            raise ForbiddenError("无权查看该请假申请")
    return _serialize(leave, viewer=user)


@router.post("/{leave_id}/decide", response_model=MessageResponse, summary="审批请假")
def decide_leave(
    leave_id: int,
    payload: LeaveDecideRequest,
    request: Request,
    user: CurrentUserDep,
    db: DbSession,
) -> MessageResponse:
    """组长/管理员审批本部门成员的请假。审批通过后即时影响后续生成的点名名册。"""
    leave = db.get(LeaveRequest, leave_id)
    if leave is None:
        raise NotFoundError("请假记录不存在")
    owner = db.get(User, leave.user_id)
    if owner is None:
        raise NotFoundError("申请人不存在")
    permission.assert_can_decide_leave(user, owner)

    if leave.status != LeaveStatus.pending:
        raise AppError("该请假已审批，无法重复处理")

    leave.status = LeaveStatus.approved if payload.approved else LeaveStatus.rejected
    leave.approver_id = user.id
    leave.decided_at = utcnow()

    audit.record(
        db,
        action="leave.decide",
        actor_id=user.id,
        target_type="leave_request",
        target_id=leave.id,
        detail={"approved": payload.approved, "comment": payload.comment},
        request=request,
    )
    db.commit()
    return MessageResponse(message="审批完成", id=leave.id)


@router.delete("/{leave_id}", response_model=MessageResponse, summary="撤回请假")
def cancel_leave(
    leave_id: int, request: Request, user: CurrentUserDep, db: DbSession
) -> MessageResponse:
    leave = db.get(LeaveRequest, leave_id)
    if leave is None:
        raise NotFoundError("请假记录不存在")
    if leave.user_id != user.id and not user.is_superuser:
        raise AppError("只能撤回自己的请假申请")
    if leave.status == LeaveStatus.approved:
        raise AppError("已审批通过的请假不能撤回，请联系组长作废")

    db.delete(leave)
    audit.record(
        db,
        action="leave.cancel",
        actor_id=user.id,
        target_type="leave_request",
        target_id=leave_id,
        request=request,
    )
    db.commit()
    return MessageResponse(message="请假已撤回")


@router.get("/week/{week_start}", summary="某周豁免名单")
def week_exemptions(
    week_start: dt.date, db: DbSession, user: CurrentUserDep
) -> list[dict[str, Any]]:
    """返回该周因请假被豁免的成员，便于组长核对点名名册。"""
    from app.services.auth_service import list_active_leaves_in_week
    from app.utils.week import ensure_date, week_end_of, week_start_of

    ws = week_start_of(ensure_date(week_start))
    leaves = list_active_leaves_in_week(
        db,
        user_ids=[u.id for u in db.execute(select(User)).scalars().all()],
        week_start=ws,
    )
    result = []
    for uid, leave in leaves.items():
        owner = db.get(User, uid)
        if owner is None:
            continue
        if not (user.is_superuser or set(user.leader_department_ids) & set(owner.department_ids)):
            continue
        result.append(
            {
                "user_id": uid,
                "full_name": owner.full_name,
                "leave_id": leave.id,
                "start_date": leave.start_date,
                "end_date": leave.end_date,
                "reason": leave.reason,
                "week_end": week_end_of(ws).isoformat(),
            }
        )
    return result
