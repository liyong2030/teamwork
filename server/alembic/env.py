"""Alembic 迁移环境。

数据库连接串从 ``app.core.config.settings.DATABASE_URL`` 读取，
元数据源为 ``app.db.base.Base.metadata``（已包含全部模型）。
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Engine, engine_from_config, event, pool

from app.core.config import settings
from app.db.base import Base
from app.models import *  # noqa: F401,F403  确保所有模型注册进 metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 用应用配置覆盖 alembic.ini 中的连接串（支持 .env）
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 脚本，不连接数据库。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,  # SQLite 需要 batch 模式才能做 ALTER
    )
    with context.begin_transaction():
        context.run_migrations()


def _disable_sqlite_foreign_keys(connectable: Engine) -> None:
    """SQLite 迁移期间关闭外键约束。

    SQLite 不支持真正的 ALTER，Alembic 的 batch 模式靠「新建临时表 → 复制数据 →
    删除旧表 → 改名」完成结构变更。若此时外键约束处于开启状态（应用运行时
    ``app.db.session`` 会全局打开 ``PRAGMA foreign_keys=ON``），删除被其他表引用的
    旧表会直接报 ``FOREIGN KEY constraint failed``。

    实例级监听器的执行晚于类级监听器，因此可以覆盖应用侧的全局设置。
    """
    if connectable.dialect.name != "sqlite":
        return

    @event.listens_for(connectable, "connect")
    def _fk_off(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()


def run_migrations_online() -> None:
    """在线模式：直接对目标库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    _disable_sqlite_foreign_keys(connectable)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
