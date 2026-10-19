"""REST 路由聚合。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    departments,
    leaves,
    projects,
    reports,
    stats,
    system,
    tasks,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(departments.router)
api_router.include_router(projects.router)
api_router.include_router(tasks.router)
api_router.include_router(leaves.router)
api_router.include_router(reports.router)
api_router.include_router(stats.router)
api_router.include_router(system.router)

__all__ = ["api_router"]
