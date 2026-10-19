"""项目统一命令行入口（跨平台）。

避免记住一长串命令，也避免用错解释器导致 ``ModuleNotFoundError``::

    python tw.py init           # 建表 + 写入默认配置（首次必做）
    python tw.py create-admin   # 创建 / 重置管理员账号
    python tw.py migrate        # 升级数据库结构（自动识别存量库基线）
    python tw.py run            # 启动后端服务（默认 http://127.0.0.1:8000）
    python tw.py smoke          # 端到端冒烟自检
    python tw.py test           # 运行单元测试

Windows 下也可直接双击同目录的 ``tw.bat``。

说明：本文件只做"挑解释器 + 转发子命令"，自身不导入任何三方库，
因此即使用系统 Python 运行也能正常工作。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = SERVER_ROOT / "scripts"


def _venv_python() -> Path | None:
    for rel in ("Scripts/python.exe", "bin/python", "bin/python3"):
        candidate = SERVER_ROOT / ".venv" / rel
        if candidate.exists():
            return candidate
    return None


def _env_with_pythonpath() -> dict[str, str]:
    env = dict(os.environ)
    parts = [str(SERVER_ROOT), str(SCRIPTS_DIR)]
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _run(args: list[str]) -> int:
    python = _venv_python() or Path(sys.executable)
    if python != Path(sys.executable):
        print(f"[tw] 使用虚拟环境解释器：{python}", flush=True)
    completed = subprocess.run([str(python), *args], cwd=str(SERVER_ROOT), env=_env_with_pythonpath())
    return completed.returncode


def _ensure_env_file() -> None:
    """首次运行时生成 .env（含随机 SECRET_KEY），避免重启后令牌全部失效。"""
    env_file = SERVER_ROOT / ".env"
    if env_file.exists():
        return
    import secrets

    env_file.write_text(
        "# 由 tw.py 自动生成，可按需修改\n"
        "APP_ENV=dev\n"
        "# SQLite 相对路径会锚定到 server/ 目录；生产环境建议改用 PostgreSQL\n"
        "DATABASE_URL=sqlite:///./data/app.db\n"
        f"SECRET_KEY={secrets.token_urlsafe(48)}\n"
        "SCHEDULER_ENABLED=true\n"
        "EMAIL_ENABLED=false\n",
        encoding="utf-8",
    )
    print(f"[tw] 已生成配置文件：{env_file}")


def main() -> int:
    parser = argparse.ArgumentParser(description="团队协作管理系统 - 命令行入口")
    parser.add_argument(
        "command",
        choices=["init", "create-admin", "run", "smoke", "test", "migrate"],
        help=(
            "init=初始化数据库 / create-admin=创建管理员 / migrate=升级数据库结构"
            "（可加 stamp <版本> / current）/ run=启动服务 / smoke=冒烟自检 / test=单元测试"
        ),
    )
    parser.add_argument("rest", nargs=argparse.REMAINDER, help="透传给子命令的参数")
    args = parser.parse_args()

    _ensure_env_file()

    if args.command == "init":
        return _run(["-c", "from app.db.init_db import init_db; init_db(); print('数据库初始化完成')"])
    if args.command == "migrate":
        return _run([str(SCRIPTS_DIR / "migrate.py"), *args.rest])
    if args.command == "create-admin":
        return _run([str(SCRIPTS_DIR / "create_admin.py"), *args.rest])
    if args.command == "smoke":
        return _run([str(SCRIPTS_DIR / "smoke_check.py"), *args.rest])
    if args.command == "test":
        return _run(["-m", "pytest", "tests", *args.rest])
    if args.command == "run":
        host = os.environ.get("APP_HOST", "127.0.0.1")
        port = os.environ.get("APP_PORT", "8000")
        return _run(
            [
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                host,
                "--port",
                port,
                "--reload",
                *args.rest,
            ]
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
