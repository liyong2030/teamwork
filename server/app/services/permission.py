"""权限判定：集中一处，避免散落在各路由里做重复判断。

判定规则（与《需求规格说明书》2.2 权限矩阵一致）：
- 管理员：全局可见可改；
- 组长：可见本部门成员的数据，可为成员代提交周报、审批请假；
- 普通成员：仅自己的数据；
- 任务的负责人与协作人对自己负责的任务拥有修改权限。

``User.memberships`` 采用 ``selectin`` 预加载，因此 ``user.department_ids`` /
``user.leader_department_ids`` 在任何已加载的用户对象上均可直接使用，无需额外查询。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError
from app.models.organization import User
from app.models.project import Task
from app.models.report import WeeklyReport


def departments_of(db: Session, user_id: int) -> set[int]:
    """查询某用户所属的全部部门 ID。"""
    target = db.get(User, user_id)
    return set(target.department_ids) if target else set()


def my_scopes(user: User) -> set[int]:
    """当前用户可"看到"的部门范围（含自身所属 + 管辖）。"""
    return set(user.department_ids) | set(user.leader_department_ids)


def managed_department_ids(user: User) -> set[int]:
    """当前用户可"管理"的部门范围。管理员返回空集，语义上表示"全部部门"。"""
    return set() if user.is_superuser else set(user.leader_department_ids)


def can_manage_department(user: User, department_id: int) -> bool:
    """是否可管理指定部门的数据。"""
    if user.is_superuser:
        return True
    return department_id in user.leader_department_ids


def can_view_department(user: User, department_id: int) -> bool:
    """是否可查看指定部门的数据。"""
    if user.is_superuser:
        return True
    return department_id in my_scopes(user)


def visible_department_ids(user: User, all_department_ids: list[int]) -> list[int]:
    """从全部部门 ID 中筛出该用户可见的部分。"""
    if user.is_superuser:
        return list(all_department_ids)
    allowed = my_scopes(user)
    return [dept_id for dept_id in all_department_ids if dept_id in allowed]


def can_view_report(user: User, report: WeeklyReport, db: Session) -> bool:
    """能否查看某份周报：本人 / 管理员 / 同部门可见。"""
    if user.is_superuser or user.id == report.user_id:
        return True
    target = set(report.user.department_ids) if report.user else departments_of(db, report.user_id)
    return bool(my_scopes(user) & target)


def can_view_report_of(user: User, target: User) -> bool:
    """能否查看**某个用户**的周报（而非某一份周报）。

    与 :func:`can_view_report` 的分工：后者针对已取出的 ``WeeklyReport`` 对象判定，
    适用于「详情 / 修订历史」这类先按 ID 查出再鉴权的接口；
    本函数只有目标用户可用，用于**列表接口在查库之前先拦截**
    （``GET /reports?user_id=``），避免越权条件先落库、再靠内存过滤补救。

    判定口径与 ``can_view_report`` 保持一致：本人 / 管理员 / 同部门可见。
    """
    if user.is_superuser or user.id == target.id:
        return True
    return bool(my_scopes(user) & set(target.department_ids))


def can_write_report(user: User, report: WeeklyReport, db: Session) -> bool:
    """能否编辑周报内容：本人（含草稿与已提交修订）/ 组长（仅未提交时）。"""
    if user.is_superuser or user.id == report.user_id:
        return True
    if report.submitted_at is not None:
        return False
    target = set(report.user.department_ids) if report.user else departments_of(db, report.user_id)
    return bool(set(user.leader_department_ids) & target)


def can_proxy_submit(user: User, target: User) -> bool:
    """能否为某人代提交周报（组长管辖本部门成员，不含自己）。"""
    if user.is_superuser:
        return True
    if user.id == target.id:
        return False
    return bool(set(user.leader_department_ids) & set(target.department_ids))


def can_review_report(user: User, target: User) -> bool:
    """能否审阅某人的周报。"""
    return can_proxy_submit(user, target)


def can_decide_leave(user: User, target: User) -> bool:
    """能否审批某人的请假：管理员全局可批；组长只能批本部门成员，**不能批自己的**。

    与 ``can_proxy_submit`` 同构（都是"管辖他人"语义），此处单独命名是为了让
    路由里的错误文案准确，避免复用时出现"无权为该成员代提交周报"这类误导。
    """
    return can_proxy_submit(user, target)


def can_edit_task(user: User, task: Task, db: Session) -> bool:
    """能否修改任务（含状态流转）：负责人 / 协作人 / 本部门组长 / 管理员。"""
    if user.is_superuser or user.id == task.owner_id or user.id in task.collaborator_ids:
        return True
    return bool(set(user.leader_department_ids) & departments_of(db, task.owner_id))


def can_view_task(user: User, task: Task, db: Session) -> bool:
    """能否查看某条任务。

    口径：管理员全部可见；负责人、协作人可见自己的任务；组长可见本部门
    （含本部门所属项目）的任务。**普通成员只能看到与自己相关的任务**。
    """
    if user.is_superuser:
        return True
    if user.id == task.owner_id or user.id in task.collaborator_ids:
        return True

    leader_depts = set(user.leader_department_ids)
    if not leader_depts:
        return False
    if task.project is not None and task.project.department_id in leader_depts:
        return True
    return bool(leader_depts & departments_of(db, task.owner_id))


def can_manage_project(user: User, owner_id: int | None, department_id: int | None) -> bool:
    """能否管理项目：负责人本人 / 归属部门组长 / 管理员。"""
    if user.is_superuser:
        return True
    if owner_id is not None and user.id == owner_id:
        return True
    if department_id is not None and department_id in user.leader_department_ids:
        return True
    return False


def filter_report_ids(user: User, reports: list[WeeklyReport], db: Session) -> list[WeeklyReport]:
    """批量过滤周报列表，保留当前用户有权查看的部分。"""
    if user.is_superuser:
        return reports
    allowed = my_scopes(user)
    result = []
    for report in reports:
        if report.user_id == user.id:
            result.append(report)
            continue
        target = set(report.user.department_ids) if report.user else departments_of(db, report.user_id)
        if allowed & target:
            result.append(report)
    return result


# ----------------------------------------------------------------------
# 断言版（路由中直接调用，失败抛 403）
# ----------------------------------------------------------------------
def assert_admin(user: User) -> None:
    if not user.is_superuser:
        raise ForbiddenError("需要系统管理员权限")


def assert_can_manage_department(user: User, department_id: int | None) -> None:
    if department_id is None:
        return
    if not can_manage_department(user, department_id):
        raise ForbiddenError("无权操作该部门的数据")


def assert_can_view_department(user: User, department_id: int | None) -> None:
    if department_id is None:
        return
    if not can_view_department(user, department_id):
        raise ForbiddenError("无权查看该部门的数据")


def assert_can_view_report(user: User, report: WeeklyReport, db: Session) -> None:
    if not can_view_report(user, report, db):
        raise ForbiddenError("无权查看该周报")


def assert_can_view_report_of(user: User, target: User) -> None:
    if not can_view_report_of(user, target):
        raise ForbiddenError("无权查看该用户的周报")


def assert_can_write_report(user: User, report: WeeklyReport, db: Session) -> None:
    if not can_write_report(user, report, db):
        raise ForbiddenError("周报已提交或您无权编辑该周报")


def assert_can_proxy(user: User, target: User) -> None:
    if not can_proxy_submit(user, target):
        raise ForbiddenError("无权为该成员代提交周报")


def assert_can_decide_leave(user: User, target: User) -> None:
    if not can_decide_leave(user, target):
        if user.id == target.id:
            raise ForbiddenError("不能审批自己的请假申请")
        raise ForbiddenError("只能审批本部门成员的请假申请")


def assert_can_edit_task(user: User, task: Task, db: Session) -> None:
    if not can_edit_task(user, task, db):
        raise ForbiddenError("无权修改该任务")


def assert_can_view_task(user: User, task: Task, db: Session) -> None:
    if not can_view_task(user, task, db):
        raise ForbiddenError("无权查看该任务")
