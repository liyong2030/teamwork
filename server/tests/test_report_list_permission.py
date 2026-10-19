"""周报列表的按人查询鉴权（回归用例）。

背景：``GET /api/v1/reports?user_id=<他人>`` 曾调用 ``permission.can_view_report_of()``，
而该函数在 ``app/services/permission.py`` 中并不存在，任何角色（含管理员）访问都会
抛 ``AttributeError`` 并被全局 handler 兜成 500。

本文件同时覆盖两层：
1. 单元层：``can_view_report_of`` 的判定矩阵；
2. 接口层：真实拉起 FastAPI，断言返回的是 200 / 403 / 404 而**不是 500**。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.services import permission

from .conftest import make_department, make_user


def _call(db: Session, as_user, query: str):
    """以指定身份调用一次接口，返回响应（退出时清理依赖覆盖）。"""
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: as_user
    try:
        return TestClient(app).get(query)
    finally:
        app.dependency_overrides.clear()


def test_can_view_report_of_matrix(db: Session) -> None:
    """判定矩阵：本人 / 管理员 / 同部门可见，跨部门不可见。"""
    dept_a = make_department(db, "A部")
    dept_b = make_department(db, "B部")
    leader = make_user(db, "boss", department=dept_a, is_leader=True)
    member = make_user(db, "worker", department=dept_a)
    outsider = make_user(db, "other", department=dept_b)
    admin = make_user(db, "root", department=dept_b, is_superuser=True)

    # 本人永远可见
    assert permission.can_view_report_of(member, member) is True
    # 组长可见本部门成员
    assert permission.can_view_report_of(leader, member) is True
    # 组长不可见跨部门成员
    assert permission.can_view_report_of(leader, outsider) is False
    # 管理员全局可见
    assert permission.can_view_report_of(admin, member) is True
    assert permission.can_view_report_of(admin, outsider) is True
    # 普通成员可见同部门成员（与 can_view_report 口径一致）
    assert permission.can_view_report_of(member, leader) is True
    assert permission.can_view_report_of(member, outsider) is False


def test_can_view_report_of_consistency_with_report_level(db: Session, monday) -> None:
    """两个函数的口径必须一致，否则会出现"列表看不到、详情能打开"的割裂。"""
    from app.models.report import WeeklyReport

    dept = make_department(db, "一致性部")
    author = make_user(db, "author", department=dept)
    viewer = make_user(db, "viewer2", department=dept)
    report = WeeklyReport(
        user_id=author.id,
        week_start=monday,
        year=monday.isocalendar()[0],
        week_no=monday.isocalendar()[1],
        version=1,
    )
    db.add(report)
    db.flush()

    assert permission.can_view_report_of(viewer, author) is True
    assert permission.can_view_report(viewer, report, db) is True


def test_assert_version_raises_forbidden(db: Session) -> None:
    dept_a = make_department(db, "A部")
    dept_b = make_department(db, "B部")
    leader = make_user(db, "boss2", department=dept_a, is_leader=True)
    outsider = make_user(db, "other2", department=dept_b)

    from app.core.exceptions import ForbiddenError

    with pytest.raises(ForbiddenError):
        permission.assert_can_view_report_of(leader, outsider)
    # 同部门不应抛错
    member = make_user(db, "worker2", department=dept_a)
    permission.assert_can_view_report_of(leader, member)


# ----------------------------------------------------------------------
# 接口层：确认不再是 500
# ----------------------------------------------------------------------
def test_list_reports_by_user_id_not_500(db: Session) -> None:
    """组长查本部门成员：应正常返回 200，而不是 500。"""
    dept_a = make_department(db, "甲部")
    leader = make_user(db, "leader-a", department=dept_a, is_leader=True)
    member = make_user(db, "member-a", department=dept_a)

    resp = _call(db, leader, f"/api/v1/reports?user_id={member.id}")

    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


def test_list_reports_cross_department_forbidden(db: Session) -> None:
    """组长查跨部门成员：应返回 403 forbidden，而不是 500。"""
    dept_a = make_department(db, "丙部")
    dept_b = make_department(db, "丁部")
    leader = make_user(db, "leader-b", department=dept_a, is_leader=True)
    outsider = make_user(db, "member-b", department=dept_b)

    resp = _call(db, leader, f"/api/v1/reports?user_id={outsider.id}")

    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "forbidden"


def test_list_reports_admin_query_any_user(db: Session) -> None:
    """管理员查任意成员：应返回 200（修复前同样是 500，因为拦截在超管判断之前）。"""
    dept_a = make_department(db, "戊部")
    dept_b = make_department(db, "己部")
    admin = make_user(db, "admin-c", department=dept_b, is_superuser=True)
    member = make_user(db, "member-c", department=dept_a)

    resp = _call(db, admin, f"/api/v1/reports?user_id={member.id}")

    assert resp.status_code == 200, resp.text


def test_list_reports_unknown_user_404(db: Session) -> None:
    """查询不存在的用户：应返回 404 not_found。"""
    admin = make_user(db, "admin-d", department=make_department(db, "庚部"), is_superuser=True)

    resp = _call(db, admin, "/api/v1/reports?user_id=999999")

    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "not_found"
