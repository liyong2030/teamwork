"""数据库结构升级（Alembic），带**存量库基线自动识别**。

背景
----
开发 / 试用阶段常用 ``create_all``（``tw.py init``、``create_admin``）直接建表，
这类库里没有 ``alembic_version`` 记录。之后再执行 ``alembic upgrade head`` 时，
Alembic 会认为"从零开始"，重建已存在的表并报
``table users already exists``。

本脚本的做法：

1. 库里已有版本记录 → 正常 ``upgrade head``；
2. 空库 → 正常 ``upgrade head``（走完整迁移建表）；
3. 有表但无版本记录 → 与当前模型做结构比对：
   - 结构已是最新 → 直接 ``stamp head``（只登记版本，不改表）；
   - 结构落后 → 先 ``stamp <初始版本>`` 打基线，再 ``upgrade head`` 补齐。

用法::

    python scripts/migrate.py            # 升级到最新版
    python scripts/migrate.py stamp head # 手动登记版本（应急）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parent.parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from _venv_guard import ensure_venv  # noqa: E402

ensure_venv()  # 直接用系统 Python 运行时自动切到 .venv 重新执行

from alembic import command  # noqa: E402
from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models import *  # noqa: E402,F403  注册全部模型，保证结构比对完整


def _alembic_config() -> Config:
    """构造 Alembic 配置（显式锚定 alembic.ini 与迁移脚本目录）。"""
    cfg = Config(str(SERVER_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    return cfg


def _base_revision(cfg: Config) -> str | None:
    """迁移链上最老的 revision（down_revision 为空的那个）。"""
    script = ScriptDirectory.from_config(cfg)
    base: str | None = None
    for rev in script.walk_revisions():  # head -> base
        base = rev.revision
    return base


def _head_revision(cfg: Config) -> str | None:
    return ScriptDirectory.from_config(cfg).get_current_head()


def _current_revision() -> str | None:
    """读取 alembic_version，表不存在时返回 None。"""
    insp = inspect(engine)
    if "alembic_version" not in insp.get_table_names():
        return None
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    return row[0] if row else None


def _has_business_tables() -> bool:
    """是否已存在业务表（区分"空库"与"存量库"）。"""
    existing = set(inspect(engine).get_table_names())
    return bool(existing & set(Base.metadata.tables.keys()))


def _schema_diff() -> list:
    """当前库结构与模型定义的差异列表，空列表表示完全一致。"""
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        return compare_metadata(ctx, Base.metadata)


def upgrade(target: str = "head") -> int:
    cfg = _alembic_config()
    current = _current_revision()

    if current:
        print(f"[migrate] 当前版本 {current}，升级到 {target}")
        command.upgrade(cfg, target)
        print("[migrate] 已是最新版本")
        return 0

    if not _has_business_tables():
        print("[migrate] 空数据库，执行全部迁移建表")
        command.upgrade(cfg, target)
        return 0

    diff = _schema_diff()
    if not diff:
        head = _head_revision(cfg)
        print(f"[migrate] 存量库结构与当前模型一致，登记版本为 {head}（不改动表结构）")
        command.stamp(cfg, str(head))
        command.upgrade(cfg, target)
        print("[migrate] 完成")
        return 0

    base = _base_revision(cfg)
    print(
        f"[migrate] 检测到未登记版本的存量库，结构与模型存在 {len(diff)} 处差异；\n"
        f"          以初始版本 {base} 打基线，再补齐后续迁移"
    )
    command.stamp(cfg, str(base))
    command.upgrade(cfg, target)
    print("[migrate] 完成")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="数据库结构升级（Alembic）")
    parser.add_argument(
        "action",
        nargs="?",
        default="upgrade",
        choices=["upgrade", "stamp", "current"],
        help="upgrade=升级到最新版（默认） / stamp=手动登记版本 / current=查看当前版本",
    )
    parser.add_argument("revision", nargs="?", default="head", help="stamp 时使用的版本号，默认 head")
    args = parser.parse_args()

    cfg = _alembic_config()
    if args.action == "stamp":
        command.stamp(cfg, args.revision)
        print(f"[migrate] 已将版本登记为 {args.revision}")
        return 0
    if args.action == "current":
        print(f"[migrate] 当前版本：{_current_revision() or '（未登记）'}")
        return 0
    return upgrade(args.revision if args.revision != "head" else "head")


if __name__ == "__main__":
    raise SystemExit(main())
