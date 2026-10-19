"""应用入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.db import init_db
from app.db.session import engine

logger = get_logger(__name__)

DESCRIPTION = """
团队协作管理系统后端 API。

核心能力：
- **任务驱动的周报**：任务状态平时更新，周五一键生成周报草稿
- **周报提交统计**：准时 / 迟到 / 补交 / 未交五态互斥，补交不回填历史
- **项目任务管理**：两级结构 + 五态状态机 + 完整变更流水
"""


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """应用生命周期：启动时初始化数据与定时任务，退出时释放资源。"""
    setup_logging("DEBUG" if settings.debug else "INFO")
    logger.info("正在启动 %s（环境：%s）", settings.app_name, settings.app_env)

    if settings.app_env == "dev":
        # 开发环境自动建表，生产环境请改用 Alembic 迁移
        init_db.init_db()

    if settings.scheduler_enabled:
        from app.tasks.scheduler import shutdown_scheduler, start_scheduler

        start_scheduler()

    yield

    if settings.scheduler_enabled:
        from app.tasks.scheduler import shutdown_scheduler

        shutdown_scheduler()

    engine.dispose()
    logger.info("服务已停止")


def create_app() -> FastAPI:
    """构造 FastAPI 应用实例（工厂模式，便于测试替换配置）。"""
    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if settings.app_env == "prod" else "/docs",
        redoc_url=None if settings.app_env == "prod" else "/redoc",
        openapi_url=None if settings.app_env == "prod" else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/health", tags=["运维"], summary="健康检查")
    def health() -> JSONResponse:
        """存活探针：不查数据库，保证极快返回。"""
        return JSONResponse({"status": "ok", "env": settings.app_env})

    @app.get("/", tags=["运维"], summary="根路径")
    def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": "1.0.0",
            "docs": "/docs" if settings.app_env != "prod" else "disabled",
        }

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "dev",
    )
