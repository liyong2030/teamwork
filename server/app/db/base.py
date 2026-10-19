"""SQLAlchemy 声明式基类与公共列定义。"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from sqlalchemy import BigInteger, DateTime, MetaData
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 统一命名约束，保证 Alembic 生成的迁移在不同数据库间可复用
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


@compiles(BigInteger, "sqlite")
def _compile_big_integer_for_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN202
    """SQLite 上把 BIGINT 编译为 INTEGER。

    SQLite 的自增主键必须是 ``INTEGER PRIMARY KEY``（rowid 别名）；
    若用 BIGINT，插入时不会自动赋值，直接触发 NOT NULL 约束失败。
    PostgreSQL 仍使用原生 BIGINT，不受影响。
    """
    return "INTEGER"


class Base(DeclarativeBase):
    """所有模型的基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def naive_utcnow() -> dt.datetime:
    """统一的"当前时间"生成器：UTC naive datetime，可直接入库。"""
    return dt.datetime.now(tz=dt.timezone.utc).replace(tzinfo=None)


# 通用时间戳列定义，可直接用于 Mapped[...] 之外的场景
CreatedAt = Annotated[
    dt.datetime,
    mapped_column(DateTime(timezone=False), default=naive_utcnow, nullable=False),
]

UpdatedAt = Annotated[
    dt.datetime,
    mapped_column(
        DateTime(timezone=False),
        default=naive_utcnow,
        onupdate=naive_utcnow,
        nullable=False,
    ),
]


class TimestampMixin:
    """通用时间戳混入：created_at / updated_at。"""

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=False), default=naive_utcnow, nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=False),
        default=naive_utcnow,
        onupdate=naive_utcnow,
        nullable=False,
    )
