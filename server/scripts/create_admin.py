"""初始管理员创建脚本。

安全设计：
- **绝不硬编码默认口令**：未指定口令时生成满足策略的随机口令；
- 随机口令打印到控制台 **并** 写入 ``logs/app.log``，要求管理员首次登录后立即修改；
- 已存在同名账号时默认报错退出，``--reset`` 可重置口令。

用法::

    python scripts/create_admin.py                       # 交互式输入用户名/姓名/邮箱
    python scripts/create_admin.py -u admin -n 系统管理员 -e admin@corp.com
    python scripts/create_admin.py -u admin --password 'StrongPass1!'   # 不推荐写在命令行历史里
    python scripts/create_admin.py -u admin --reset      # 重置已有管理员口令
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# 让脚本可以直接以 `python scripts/create_admin.py` 方式运行
_SERVER_ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, _SERVER_ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _venv_guard import ensure_venv  # noqa: E402

ensure_venv()  # 必须在导入三方库之前：缺少依赖时自动切换到 .venv 重新执行

from sqlalchemy import inspect, select  # noqa: E402

from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.core.security import (  # noqa: E402
    generate_temp_password,
    hash_password,
    validate_password_strength,
)
from app.db.init_db import init_db  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models.organization import Department, DepartmentMember, User  # noqa: E402
from app.utils.week import utcnow  # noqa: E402

logger = get_logger("create_admin")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="创建或重置系统管理员账号")
    parser.add_argument("-u", "--username", help="登录名")
    parser.add_argument("-n", "--full-name", dest="full_name", help="姓名")
    parser.add_argument("-e", "--email", help="邮箱")
    parser.add_argument("-p", "--password", help="初始口令（留空则自动生成随机口令）")
    parser.add_argument("--reset", action="store_true", help="重置已存在账号的口令")
    parser.add_argument(
        "--department", help="加入的部门名称（不存在则创建）", default="系统管理部"
    )
    return parser.parse_args()


def main() -> int:
    setup_logging("INFO")
    args = parse_args()

    username = args.username or input("登录名: ").strip()
    if not username:
        print("登录名不能为空")
        return 1

    full_name = args.full_name or input("姓名: ").strip() or username

    email = args.email
    if email is None and sys.stdin.isatty():
        email = input("邮箱（可留空）: ").strip() or None

    raw_password = args.password
    if not raw_password and sys.stdin.isatty() and input("是否手动输入口令？(y/N) ").strip().lower() == "y":
        raw_password = getpass.getpass("口令: ")
        confirm = getpass.getpass("确认口令: ")
        if raw_password != confirm:
            print("两次输入的口令不一致")
            return 1

    if raw_password:
        ok, msg = validate_password_strength(raw_password)
        if not ok:
            print(f"口令不符合策略：{msg}")
            return 1
    else:
        raw_password = generate_temp_password()

    # 首次运行时数据库可能还是空的，这里兜底建表 + 写入默认配置（幂等）
    if not inspect(engine).has_table("users"):
        print("[init] 未检测到数据表，正在初始化数据库…")
        init_db()
        print("[init] 数据库初始化完成")

    with SessionLocal() as db:
        existing = db.execute(select(User).where(User.username == username)).scalar_one_or_none()

        if existing is not None and not args.reset:
            print(f"用户 {username} 已存在。如需重置口令请加 --reset 参数")
            return 1

        if existing is not None:
            existing.hashed_password = hash_password(raw_password)
            existing.must_change_password = True
            existing.password_changed_at = utcnow()
            existing.is_superuser = True
            existing.is_active = True
            user = existing
            action = "重置"
        else:
            user = User(
                username=username,
                full_name=full_name,
                email=email,
                hashed_password=hash_password(raw_password),
                is_superuser=True,
                is_active=True,
                must_change_password=True,
                password_changed_at=utcnow(),
            )
            db.add(user)
            db.flush()
            action = "创建"

            dept = db.execute(
                select(Department).where(Department.name == args.department)
            ).scalar_one_or_none()
            if dept is None:
                dept = Department(name=args.department, sort_order=0, is_active=True)
                db.add(dept)
                db.flush()
            db.add(DepartmentMember(user_id=user.id, department_id=dept.id, is_leader=True))

        db.commit()

    tips = f"""
[管理员账号已{action}]
  登录名：{username}
  姓  名：{full_name}
  邮  箱：{email or '未设置'}
  初始口令：{raw_password}

  请妥善保存该口令并尽快登录修改（首次登录强制改密）。
"""
    print(tips)
    logger.warning("[create_admin] 已%s管理员 %s，初始口令已生成（请妥善保管）", action, username)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
