"""结构化日志：控制台彩色输出 + 文件轮转留存 30 天。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """初始化根 logger，幂等调用。"""
    root = logging.getLogger()
    if getattr(root, "_ctms_configured", False):  # 避免重复添加 handler
        root.setLevel(level)
        return

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = TimedRotatingFileHandler(
        filename=LOG_DIR / "app.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    root.setLevel(level)
    # uvicorn 默认自带 handler，这里统一接管避免重复打印
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True

    # APScheduler 日志过于啰嗦
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)

    root._ctms_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger。"""
    return logging.getLogger(name)
