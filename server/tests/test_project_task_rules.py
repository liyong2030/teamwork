"""项目与任务的两条核心业务规则。

1. 项目编号自动生成且唯一；
2. 任务可见性：普通成员只看「负责人=自己 或 协作人包含自己」的任务。
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models.project import Project, TaskCollaborator
from app.services import permission, project_service, task_service

from .conftest import make_department, make_project, make_task, make_user


# ----------------------------------------------------------------------
# 1. 项目编号
# ----------------------------------------------------------------------
def test_code_auto_generated_when_blank(db: Session) -> None:
    year = dt.date.today().year
    code = project_service.resolve_project_code(db, None)
    assert code == f"PRJ-{year}-001"

    owner = make_user(db, "owner")
    db.add(Project(name="甲", code=code, owner_id=owner.id))
    db.flush()

    assert project_service.resolve_project_code(db, "") == f"PRJ-{year}-002"
    assert project_service.resolve_project_code(db, "   ") == f"PRJ-{year}-002"


def test_code_increments_and_skips_holes(db: Session) -> None:
    year = dt.date.today().year
    owner = make_user(db, "owner")
    for seq in ("001", "002", "007"):
        db.add(Project(name=f"P{seq}", code=f"PRJ-{year}-{seq}", owner_id=owner.id))
    db.flush()

    # 已存在 001/002/007，下一个应取 008（跳过空洞，绝不复用）
    assert project_service.generate_project_code(db) == f"PRJ-{year}-008"


def test_manual_code_respected_and_duplicate_rejected(db: Session) -> None:
    owner = make_user(db, "owner")
    assert project_service.resolve_project_code(db, "MY-CODE") == "MY-CODE"

    db.add(Project(name="甲", code="MY-CODE", owner_id=owner.id))
    db.flush()

    with pytest.raises(AppError) as exc:
        project_service.resolve_project_code(db, "MY-CODE")
    assert "已存在" in str(exc.value)


def test_code_unique_constraint_at_db_level(db: Session) -> None:
    """即使绕开服务层，数据库唯一约束也应拦住重复编号。"""
    from sqlalchemy.exc import IntegrityError

    owner = make_user(db, "owner")
    db.add(Project(name="甲", code="DUP-1", owner_id=owner.id))
    db.flush()
    # 用嵌套事务（SAVEPOINT）隔离，避免把外层用例事务整体打崩
    savepoint = db.begin_nested()
    db.add(Project(name="乙", code="DUP-1", owner_id=owner.id))
    with pytest.raises(IntegrityError):
        db.flush()
    savepoint.rollback()


# ----------------------------------------------------------------------
# 2. 任务可见性
# ----------------------------------------------------------------------
def _seed(db: Session):
    dept = make_department(db, "研发部")
    leader = make_user(db, "leader", department=dept, is_leader=True)
    alice = make_user(db, "alice", department=dept)
    bob = make_user(db, "bob", department=dept)
    outsider = make_user(db, "outsider")  # 其他部门

    project = make_project(db, owner=leader, code="PRJ-VIS")
    mine = make_task(db, project, alice, title="我的任务")
    others = make_task(db, project, bob, title="别人的任务")
    collab = make_task(db, project, bob, title="我协作的任务")
    db.add(TaskCollaborator(task_id=collab.id, user_id=alice.id))
    outside_task = make_task(db, project, outsider, title="外部门任务")
    db.flush()
    return leader, alice, bob, outsider, project, mine, others, outside_task


def test_member_only_sees_own_or_collaborated_tasks(db: Session) -> None:
    _leader, alice, _bob, _outsider, project, mine, others, outside_task = _seed(db)

    rows, _ = task_service.list_tasks(db, viewer=alice)
    ids = {t.id for t in rows}

    assert mine.id in ids  # 负责人是自己
    assert ids & {others.id, outside_task.id} == set()  # 与自己无关的任务不可见
    assert len(ids) == 2  # 自己的 + 协作的

    # 可见性判定函数与列表口径一致
    assert permission.can_view_task(alice, mine, db) is True
    assert permission.can_view_task(alice, others, db) is False


def test_collaborator_can_see_task(db: Session) -> None:
    _leader, alice, _bob, *_rest = _seed(db)
    collaborated = [
        t for t in task_service.list_tasks(db, viewer=alice)[0] if "协作" in t.title
    ]
    assert len(collaborated) == 1
    assert permission.can_view_task(alice, collaborated[0], db) is True


def test_leader_sees_department_tasks(db: Session) -> None:
    leader, _alice, bob, outsider, project, mine, _others, outside_task = _seed(db)

    rows, _ = task_service.list_tasks(db, viewer=leader)
    ids = {t.id for t in rows}
    assert {mine.id, outside_task.id} <= ids  # 部门成员 + 部门项目下的任务
    assert permission.can_view_task(leader, mine, db) is True


def test_admin_sees_everything(db: Session) -> None:
    _leader, _alice, _bob, _outsider, _project, _mine, others, outside_task = _seed(db)
    admin = make_user(db, "root", is_superuser=True)

    rows, _ = task_service.list_tasks(db, viewer=admin)
    ids = {t.id for t in rows}
    assert {others.id, outside_task.id} <= ids
    assert permission.can_view_task(admin, others, db) is True


def test_project_stats_respect_visibility(db: Session) -> None:
    """项目卡片上的任务数也按可见范围统计，避免与看板对不上。"""
    _leader, alice, _bob, _outsider, project, _mine, _others, _outside = _seed(db)

    total_admin, _, _ = task_service.project_progress(db, project.id, viewer=None)
    total_alice, _, _ = task_service.project_progress(db, project.id, viewer=alice)
    assert total_admin == 4
    assert total_alice == 2  # 仅有与自己相关的两条
