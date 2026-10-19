"""解释器守卫：确保脚本运行在装有依赖的虚拟环境里。

用系统 Python（或 IDE 默认的解释器）直接执行脚本时，最常见的报错是::

    ModuleNotFoundError: No module named 'sqlalchemy'

因为依赖装在 ``server/.venv`` 里，系统解释器看不到。本模块必须在**导入任何
三方库之前**调用：若检测到依赖缺失，会自动切换到项目内 ``.venv`` 的解释器
重新执行当前命令；找不到虚拟环境时，给出可直接复制的安装指令。

用法（放在脚本最顶部，位于 ``import sqlalchemy`` 之前）::

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # server 根目录
    sys.path.insert(0, str(Path(__file__).resolve().parent))      # scripts 目录
    from _venv_guard import ensure_venv
    ensure_venv()
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = SERVER_ROOT / ".venv"

HINT = f"""
[bootstrap] 未找到可用的依赖环境。

请先创建虚拟环境并安装依赖（在项目 server/ 目录下执行）：

    python -m venv .venv
    .venv\\Scripts\\python.exe -m pip install --upgrade pip
    .venv\\Scripts\\python.exe -m pip install -r requirements.txt

若网络较慢，可加国内镜像：

    .venv\\Scripts\\python.exe -m pip install -r requirements.txt \\
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple

安装完成后重新执行本命令即可。
"""


def _venv_python() -> Path | None:
    """返回项目虚拟环境中的解释器路径（不存在则返回 None）。"""
    candidates = (
        VENV_DIR / "Scripts" / "python.exe",  # Windows
        VENV_DIR / "bin" / "python",  # Linux / macOS
        VENV_DIR / "bin" / "python3",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _is_current(python_path: Path) -> bool:
    try:
        return Path(sys.executable).resolve() == python_path.resolve()
    except OSError:  # pragma: no cover - 路径不可解析时按“不是”处理
        return False


def ensure_venv(module: str = "sqlalchemy") -> None:
    """校验依赖可用；不可用时切换到 .venv 重新执行当前命令。"""
    try:
        __import__(module)
        return
    except ModuleNotFoundError:
        pass

    venv_python = _venv_python()
    if venv_python is not None and not _is_current(venv_python):
        print(f"[bootstrap] 当前解释器缺少依赖，改用虚拟环境：{venv_python}", flush=True)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SERVER_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        completed = subprocess.run([str(venv_python), *sys.argv], env=env)
        raise SystemExit(completed.returncode)

    print(HINT, flush=True)
    raise SystemExit(2)


def resolve_python() -> str:
    """返回应当用于执行子命令的解释器路径。"""
    venv_python = _venv_python()
    if venv_python is not None:
        return str(venv_python)
    return sys.executable
