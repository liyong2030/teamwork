"""项目服务：编号自动生成、成员维护等跨路由复用逻辑。

编号规则：``PRJ-{年份}-{三位序号}``，例如 ``PRJ-2026-001``。

- 序号按**自然年**递增，跨年自动重新从 001 开始；
- 生成时先取当前年度已有编号的最大序号，再逐个向后探测，避开"历史遗留/手工填写"
  造成的空洞与冲突；
- 数据库层 ``projects.code`` 另有唯一约束兜底，并发下也不会出现重复编号。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models.project import Project
from app.utils.week import today_local

CODE_PREFIX = "PRJ"
MAX_PROBE = 1000  # 极端情况下的探测上限，防止死循环


def _year_prefix(year: int | None = None) -> str:
    year = year or today_local().year
    return f"{CODE_PREFIX}-{year}-"


def generate_project_code(db: Session) -> str:
    """生成下一个可用的项目编号（不落库，仅返回候选值）。"""
    prefix = _year_prefix()
    existing = db.execute(select(Project.code).where(Project.code.like(f"{prefix}%"))).all()

    max_seq = 0
    for (code,) in existing:
        tail = (code or "")[len(prefix) :]
        if tail.isdigit():
            max_seq = max(max_seq, int(tail))

    seq = max_seq + 1
    for _ in range(MAX_PROBE):
        candidate = f"{prefix}{seq:03d}"
        taken = db.execute(select(Project.id).where(Project.code == candidate)).first()
        if taken is None:
            return candidate
        seq += 1

    raise AppError("项目编号生成失败，请稍后重试")


def resolve_project_code(db: Session, raw: str | None) -> str:
    """确定项目最终编号：手工填写则以手工值为准，留空则自动生成。

    :raises AppError: 手工填写的编号已被占用，或编号超长
    """
    code = (raw or "").strip()
    if not code:
        return generate_project_code(db)

    if len(code) > 32:
        raise AppError("项目编号长度不能超过 32 个字符")

    exists = db.execute(select(Project.id).where(Project.code == code)).first()
    if exists:
        raise AppError(f"项目编号 {code} 已存在")
    return code
