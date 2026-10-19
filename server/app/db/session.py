"""数据库引擎与会话管理。

同步 SQLAlchemy + 同步路由函数的组合：FastAPI 会把同步 ``def`` 路由放入线程池执行，
不会阻塞事件循环，同时避免 async ORM 在 SQLite 下的兼容问题。
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine: Engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    future=True,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if settings.is_sqlite else {},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,  # 提交后仍可读取已加载属性，避免 DetachedInstanceError
    future=True,
)


# SQLite 需显式开启外键约束
if settings.is_sqlite:

    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖项：请求生命周期内的数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """给定时任务 / 脚本使用的会话上下文，异常回滚、正常提交、始终关闭。"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
