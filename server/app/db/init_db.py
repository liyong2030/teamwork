"""数据库初始化：建表、写入默认配置与默认部门。

注意：**不在此处创建任何默认账号**。初始管理员一律通过
``python scripts/create_admin.py`` 生成，禁止硬编码默认口令。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.base import Base
from app.db.session import engine
from app.models.organization import Department
from app.models.system import SystemSetting

logger = get_logger(__name__)

DEFAULT_SETTINGS: list[tuple[str, object, str]] = [
    ("report.deadline_weekday", 5, "周报截止日（1=周一 … 5=周五）"),
    ("report.deadline_time", "18:00", "周报截止时间"),
    ("report.finalize_weekday", 1, "周报定版日（下周几）"),
    ("report.finalize_time", "09:30", "周报定版时间"),
    ("report.valid_min_chars", 20, "有效周报最少字数（本周工作总结 + 下周工作计划）"),
    (
        "notify.reminder_points",
        ["fri_1000", "fri_1700", "sun_2000", "mon_0830"],
        "启用的提醒时点",
    ),
    ("notify.email_enabled", True, "邮件提醒总开关"),
]


def _stamp_alembic_head() -> None:
    """``create_all`` 建出的库没有版本记录，登记为 head 以免后续迁移重复建表。

    这是 ``python tw.py init`` 之后直接 ``tw.py migrate`` 报
    ``table users already exists`` 的根因修复：建表即登记版本。
    失败只告警不中断——初始化本身已经成功，版本可稍后用
    ``python tw.py migrate`` 补齐。
    """
    try:
        from alembic import command
        from alembic.config import Config

        server_root = Path(__file__).resolve().parents[2]
        cfg = Config(str(server_root / "alembic.ini"))
        cfg.set_main_option("script_location", str(server_root / "alembic"))
        command.stamp(cfg, "head")
        logger.info("已登记 Alembic 版本为 head")
    except Exception as exc:  # pragma: no cover - 兜底，不应影响建表结果
        logger.warning("登记 Alembic 版本失败（可稍后执行 python tw.py migrate 补齐）：%s", exc)


def create_all_tables() -> None:
    """开发环境一键建表（生产请用 Alembic 迁移）。"""
    Base.metadata.create_all(bind=engine)
    logger.info("已同步全部数据表")

    # 已存在版本记录说明是迁移建库，不要覆盖
    if "alembic_version" not in inspect(engine).get_table_names():
        _stamp_alembic_head()


def seed_defaults(db: Session) -> None:
    """写入默认系统配置与示例部门（幂等）。"""
    for key, value, description in DEFAULT_SETTINGS:
        exists = db.execute(select(SystemSetting).where(SystemSetting.key == key)).first()
        if exists:
            continue
        db.add(SystemSetting(key=key, value=value, description=description))

    if not db.execute(select(Department).limit(1)).first():
        db.add(Department(name="未分组", sort_order=0, is_active=True))
        logger.info("已创建默认部门：未分组")

    db.flush()
    logger.info("默认配置初始化完成")


def init_db() -> None:
    """完整初始化：建表 + 种子数据。"""
    create_all_tables()
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        seed_defaults(db)
        db.commit()
