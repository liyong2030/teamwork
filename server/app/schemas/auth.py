"""认证与用户相关 Schema。"""

from __future__ import annotations

import datetime as dt
import re

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    """登录入参。"""

    username: str
    password: str


class TokenResponse(BaseModel):
    """登录成功响应。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    """管理员重置密码。"""

    new_password: str | None = None  # 留空则系统自动生成


class ResetPasswordResponse(BaseModel):
    message: str = "密码已重置"
    temp_password: str


class CurrentUser(ORMModel):
    """当前登录用户上下文。"""

    id: int
    username: str
    full_name: str
    email: str | None = None
    is_superuser: bool = False
    must_change_password: bool = False
    department_ids: list[int] = []
    leader_department_ids: list[int] = []
    is_department_leader: bool = False
    auth_source: str = "local"
    is_sso: bool = False

    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    username: str
    full_name: str
    email: str | None = None

    @field_validator("username")
    @classmethod
    def _check_username(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", v):
            raise ValueError("登录名需为 3-64 位字母、数字、下划线、点或短横线")
        return v


class UserCreate(UserBase):
    password: str | None = None  # 留空则自动生成随机初始口令
    department_ids: list[int] = []
    leader_department_ids: list[int] = []
    is_superuser: bool = False
    is_active: bool = True


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    department_ids: list[int] | None = None
    leader_department_ids: list[int] | None = None
    is_superuser: bool | None = None
    is_active: bool | None = None


class UserOut(ORMModel):
    id: int
    username: str
    full_name: str
    email: str | None = None
    is_active: bool
    is_superuser: bool
    must_change_password: bool
    last_login_at: dt.datetime | None = None
    created_at: dt.datetime
    department_ids: list[int] = []
    leader_department_ids: list[int] = []
    department_names: list[str] = []
    auth_source: str = "local"
    auth_source_label: str = "本地口令"
    external_id: str | None = None
    is_sso: bool = False


class LoginHistoryOut(ORMModel):
    id: int
    action: str
    ip_address: str | None = None
    created_at: dt.datetime


class LeaveRequestCreate(BaseModel):
    start_date: dt.date
    end_date: dt.date
    reason: str | None = None

    @field_validator("end_date")
    @classmethod
    def _check_range(cls, v: dt.date, info) -> dt.date:
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("结束日期不能早于开始日期")
        return v


class LeaveRequestOut(ORMModel):
    id: int
    user_id: int
    start_date: dt.date
    end_date: dt.date
    reason: str | None = None
    status: str
    approver_id: int | None = None
    decided_at: dt.datetime | None = None
    created_at: dt.datetime
    username: str | None = None
    full_name: str | None = None


class LeaveDecideRequest(BaseModel):
    approved: bool
    comment: str | None = None


class EmailTestRequest(BaseModel):
    to_email: EmailStr


class SSOLoginRequest(LoginRequest):
    """统一身份认证登录入参（与本地登录同构：账号 + 口令）。"""


class SSOBindRequest(BaseModel):
    """管理员为既有账号手动绑定 IdP 标识。"""

    source: str
    external_id: str
