"""pytest 公共夹具。

测试使用**内存 SQLite**，每个用例独立重建 schema，互不污染。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Generator, Iterator

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.enums import TaskPriority, TaskStatus
from app.models.organization import Department, DepartmentMember, LeaveRequest, User
from app.models.project import Project, Task, TaskStatusLog
from app.models.report import WeeklyReport
from app.utils.week import utcnow, week_start_of

# 必须在导入 app.models 之后才能拿到完整 metadata
from app.models import *  # noqa: F401,F403,E402  (确保所有模型注册到 Base.metadata)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(Engine, "connect")
    def _fk_on(dbapi_conn, _rec):  # noqa: ANN001, ANN202
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Generator[Session, None, None]:
    """每个用例一个事务，结束后回滚，保证互不干扰。"""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ----------------------------------------------------------------------
# 数据工厂
# ----------------------------------------------------------------------
def make_department(db: Session, name: str = "研发部") -> Department:
    dept = Department(name=name, sort_order=0, is_active=True)
    db.add(dept)
    db.flush()
    return dept


def make_user(
    db: Session,
    username: str,
    *,
    full_name: str | None = None,
    department: Department | None = None,
    is_leader: bool = False,
    is_superuser: bool = False,
    password: str = "StrongPass1!",
) -> User:
    dept = department or make_department(db, f"{username}-部门")
    user = User(
        username=username,
        full_name=full_name or username,
        email=f"{username}@example.com",
        hashed_password=hash_password(password),
        is_superuser=is_superuser,
        is_active=True,
        must_change_password=False,
    )
    db.add(user)
    db.flush()
    db.add(
        DepartmentMember(user_id=user.id, department_id=dept.id, is_leader=is_leader)
    )
    db.flush()
    return user


def make_project(db: Session, owner: User, code: str = "PRJ-1") -> Project:
    project = Project(
        name=f"项目{code}",
        code=code,
        owner_id=owner.id,
        department_id=owner.department_ids[0] if owner.department_ids else None,
        status="active",
    )
    db.add(project)
    db.flush()
    return project


def make_task(
    db: Session,
    project: Project,
    owner: User,
    *,
    title: str = "任务",
    due_date: dt.date | None = None,
    status: TaskStatus = TaskStatus.TODO,
    priority: TaskPriority = TaskPriority.P2,
) -> Task:
    task = Task(
        project_id=project.id,
        title=title,
        owner_id=owner.id,
        priority=priority,
        status=status,
        due_date=due_date,
        checklist=[],
        tags=[],
    )
    db.add(task)
    db.flush()
    db.add(
        TaskStatusLog(
            task_id=task.id,
            from_status=None,
            to_status=status,
            operator_id=owner.id,
            remark="create",
            created_at=utcnow(),
        )
    )
    db.flush()
    return task


def log_status(
    db: Session,
    task: Task,
    to_status: TaskStatus,
    *,
    operator: User,
    at: dt.datetime,
    progress: int | None = None,
    remark: str | None = None,
) -> None:
    """写入一条指定时刻的状态流水，用于构造"本周发生的事实"。"""
    from app.utils.week import ensure_date  # noqa: F401

    log = TaskStatusLog(
        task_id=task.id,
        from_status=task.status,
        to_status=to_status,
        from_progress=task.progress,
        to_progress=progress if progress is not None else task.progress,
        operator_id=operator.id,
        remark=remark,
        created_at=at,
    )
    task.status = to_status
    if progress is not None:
        task.progress = progress
    db.add(log)
    db.flush()


@pytest.fixture
def monday() -> dt.date:
    """本自然周的周一。"""
    return week_start_of(dt.date.today())
