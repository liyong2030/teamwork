"""部门相关 Schema。"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from app.schemas.common import ORMModel


class DepartmentBase(BaseModel):
    name: str
    parent_id: int | None = None
    leader_id: int | None = None
    sort_order: int = 0
    is_active: bool = True


class DepartmentCreate(DepartmentBase):
    member_ids: list[int] = []


class DepartmentUpdate(BaseModel):
    name: str | None = None
    parent_id: int | None = None
    leader_id: int | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    member_ids: list[int] | None = None
    leader_ids: list[int] | None = None


class DepartmentMemberOut(ORMModel):
    user_id: int
    username: str | None = None
    full_name: str | None = None
    is_leader: bool = False


class DepartmentOut(ORMModel):
    id: int
    name: str
    parent_id: int | None = None
    leader_id: int | None = None
    sort_order: int
    is_active: bool
    created_at: dt.datetime
    member_count: int = 0
    members: list[DepartmentMemberOut] = []

    model_config = ConfigDict(from_attributes=True)


class AssignMemberRequest(BaseModel):
    user_id: int
    is_leader: bool = False
