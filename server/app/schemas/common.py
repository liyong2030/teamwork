"""Pydantic v2 出入参 Schema。"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    """支持从 SQLAlchemy 对象直接构造的基类。"""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page(ORMModel, Generic[T]):
    """统一分页响应体。"""

    items: list[T]
    total: int = 0
    page: int = 1
    page_size: int = 20

    @property
    def pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size


class MessageResponse(ORMModel):
    """通用操作结果。"""

    message: str = "操作成功"
    id: int | None = None


class BriefUser(ORMModel):
    """用户简要信息（用于嵌套展示）。"""

    id: int
    username: str
    full_name: str
    email: str | None = None


class BriefDepartment(ORMModel):
    id: int
    name: str


class BriefProject(ORMModel):
    id: int
    name: str
    code: str


class QueryPager(BaseModel):
    """分页查询参数。"""

    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=200)
