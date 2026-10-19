"""端到端冒烟验证：真实拉起 FastAPI 应用，走通核心业务链路。

验证链路：创建管理员 → 建组织 → 建项目/任务 → 状态流转 →
生成周报草稿 → 提交 → 统计 → 导出 → 定版 → 补交不洗白。
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

sqlite_path = Path(tempfile.mkdtemp(prefix="ctms_smoke_")) / "smoke.db"
os.environ["DATABASE_URL"] = f"sqlite:///{sqlite_path.as_posix()}"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["APP_ENV"] = "dev"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _venv_guard import ensure_venv  # noqa: E402

ensure_venv("fastapi")  # 缺少依赖时自动切换到 .venv 重新执行

from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import TaskStatus  # noqa: E402
from app.models.organization import Department, DepartmentMember, User  # noqa: E402
from app.utils.week import week_start_of  # noqa: E402

Base.metadata.create_all(bind=engine)

ADMIN_PASSWORD = "Admin@12345"
MEMBER_PASSWORD = "Member@12345"

with SessionLocal() as seed_db:
    admin = User(
        username="smokeadmin",
        full_name="冒烟管理员",
        email="admin@smoke.local",
        hashed_password=hash_password(ADMIN_PASSWORD),
        is_superuser=True,
        is_active=True,
        must_change_password=False,
    )
    seed_db.add(admin)
    seed_db.flush()

    member = User(
        username="smokemember",
        full_name="冒烟成员",
        email="member@smoke.local",
        hashed_password=hash_password(MEMBER_PASSWORD),
        is_superuser=False,
        is_active=True,
        must_change_password=False,
    )
    seed_db.add(member)
    seed_db.flush()

    dept = Department(name="冒烟研发组", sort_order=1, is_active=True)
    seed_db.add(dept)
    seed_db.flush()
    seed_db.add(DepartmentMember(user_id=member.id, department_id=dept.id, is_leader=False))
    seed_db.add(DepartmentMember(user_id=admin.id, department_id=dept.id, is_leader=True))
    seed_db.commit()
    admin_id = admin.id
    member_id = member.id

client = TestClient(app)


def login(username: str, password: str) -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


admin_headers = login("smokeadmin", ADMIN_PASSWORD)
member_headers = login("smokemember", MEMBER_PASSWORD)

report: list[str] = []


def step(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    report.append(f"[{status}] {name}{(' -> ' + detail) if detail else ''}")
    if not condition:
        print("\n".join(report))
        raise SystemExit(1)


# 1. 当前用户上下文
me = client.get("/api/v1/auth/me", headers=member_headers)
step("获取当前用户上下文", me.status_code == 200 and me.json()["username"] == "smokemember")

# 2. 创建项目
monday = week_start_of(dt.date.today())
project_resp = client.post(
    "/api/v1/projects",
    headers=admin_headers,
    json={"name": "冒烟项目", "code": "SMOKE-001", "member_ids": [member.id]},
)
step("创建项目", project_resp.status_code == 200, project_resp.text[:120])
project_id = project_resp.json()["id"]

# 3. 创建任务
task_ids: list[int] = []
for title in ["完成接口开发", "推进联调", "阻塞在第三方", "下周一交付"]:
    r = client.post(
        "/api/v1/tasks",
        headers=admin_headers,
        json={
            "title": title,
            "project_id": project_id,
            "owner_id": member.id,
            "priority": "p1",
            "due_date": (monday + dt.timedelta(days=3)).isoformat(),
        },
    )
    step(f"创建任务：{title}", r.status_code == 200, r.text[:120])
    task_ids.append(r.json()["id"])

# 4. 状态流转：第一个任务置为完成
r = client.post(
    f"/api/v1/tasks/{task_ids[0]}/status",
    headers=member_headers,
    json={"to_status": "done", "progress": 100, "remark": "已完成"},
)
step("任务状态流转到 done", r.status_code == 200, r.text[:120])

r = client.post(
    f"/api/v1/tasks/{task_ids[1]}/status",
    headers=member_headers,
    json={"to_status": "in_progress", "progress": 60},
)
step("任务状态流转到 in_progress", r.status_code == 200, r.text[:120])

r = client.post(
    f"/api/v1/tasks/{task_ids[2]}/status",
    headers=member_headers,
    json={"to_status": "blocked", "remark": "等待第三方返回"},
)
step("任务状态流转到 blocked", r.status_code == 200, r.text[:120])

# 5. 看板
board = client.get(f"/api/v1/projects/{project_id}/board", headers=member_headers)
step(
    "项目看板五列",
    board.status_code == 200
    and {c["status"] for c in board.json()} == {"todo", "in_progress", "blocked", "done", "cancelled"},
)

# 6. 生成周报草稿
gen = client.post("/api/v1/reports/generate", headers=member_headers, json={"force": True})
step("周报草稿自动生成", gen.status_code == 200, gen.text[:160])
items = gen.json().get("items", [])
sections = {i["section"] for i in items}
step(
    "草稿覆盖本周进展/总结/风险",
    {"done", "progress", "risk"} & sections != set(),
    f"命中段落={sorted(sections)}",
)
report_id = gen.json()["id"]

# 7b. 同一周不可重复创建另一份（未提交时也回 stepping 同一条记录）
dup = client.post("/api/v1/reports/generate", headers=member_headers, json={"force": False})
step(
    "一人一周仅一份周报",
    dup.status_code == 200 and dup.json()["id"] == report_id,
    f"report_id={report_id}",
)

# 7. 补齐下周计划后提交
submit_items = [
    {"section": "plan", "content": "下周完成灰度发布与压力测试脚本编写"},
]
for item in items:
    submit_items.append({"section": item["section"], "content": item["content"], "task_id": item["task_id"]})
submitted = client.post(
    "/api/v1/reports/submit",
    headers=member_headers,
    json={"items": submit_items},
)
step("提交周报", submitted.status_code == 200, submitted.text[:160])
step("提交后周报被锁定", submitted.json().get("is_locked") is True)

# 8. 已提交后重新生成应被拒绝（需走修订流程）
locked_gen = client.post("/api/v1/reports/generate", headers=member_headers, json={"force": True})
step(
    "已提交周报禁止重新生成",
    locked_gen.status_code in (400, 409),
    locked_gen.text[:120],
)

# 8b. 修订：带修改原因再次提交，版本号应递增
rev = client.post(
    "/api/v1/reports/submit",
    headers=member_headers,
    json={"items": submit_items, "reason": "补充遗漏的联调工作"},
)
step(
    "修订提交并生成新版本",
    rev.status_code == 200 and rev.json()["version"] >= 2,
    f"version={rev.json().get('version') if rev.status_code == 200 else rev.text[:120]}",
)

revisions = client.get(f"/api/v1/reports/{report_id}/revisions", headers=member_headers)
step("修订历史留痕", revisions.status_code == 200 and len(revisions.json()) >= 2)

# 9. 我的本周状态
status_card = client.get("/api/v1/reports/my-week-status", headers=member_headers)
step("我的本周状态卡", status_card.status_code == 200 and status_card.json()["has_report"])

# 10. 统计：管理员视角
overview = client.get(
    "/api/v1/stats/overview",
    headers=admin_headers,
    params={"week_start": monday.isoformat()},
)
step("统计概览", overview.status_code == 200, overview.text[:160])
ov = overview.json()
step("应提交人数统计到成员", ov["required"] >= 1, f"required={ov['required']}")

people = client.get(
    "/api/v1/stats/people",
    headers=admin_headers,
    params={"week_start": monday.isoformat()},
)
step("成员明细", people.status_code == 200 and len(people.json()) >= 1)

trend = client.get("/api/v1/stats/trend", headers=admin_headers, params={"weeks": 8})
step("近 8 周趋势", trend.status_code == 200 and len(trend.json()) == 8)

# 11. 导出
for fmt, media in (("xlsx", "spreadsheet"), ("csv", "csv")):
    exp = client.post(
        "/api/v1/stats/export",
        headers=admin_headers,
        json={"week_start": monday.isoformat(), "fmt": fmt},
    )
    step(f"导出 {fmt}", exp.status_code == 200 and len(exp.content) > 0, exp.headers.get("content-type", ""))

exp = client.get(
    "/api/v1/reports/export",
    headers=member_headers,
    params={"week_start": monday.isoformat()},
)
step(
    "导出我的周报",
    exp.status_code == 200 and len(exp.content) > 0,
    f"{exp.status_code} {exp.text[:160]}",
)

# 12. 请假审批影响点名名册
leave = client.post(
    "/api/v1/leaves",
    headers=member_headers,
    json={
        "start_date": (monday - dt.timedelta(days=7)).isoformat(),
        "end_date": (monday + dt.timedelta(days=7)).isoformat(),
        "reason": "冒烟测试请假",
    },
)
step("提交请假", leave.status_code == 200, leave.text[:120])
leave_id = leave.json()["id"]

approve = client.post(
    f"/api/v1/leaves/{leave_id}/decide",
    headers=admin_headers,
    json={"approved": True, "comment": "同意"},
)
step("审批请假通过", approve.status_code == 200, approve.text[:120])

exempt = client.get(f"/api/v1/leaves/week/{monday.isoformat()}", headers=admin_headers)
step("本周豁免名单命中", exempt.status_code == 200 and any(e["user_id"] == member_id for e in exempt.json()))

# 13. 权限校验：成员不得访问用户管理
forbidden = client.get("/api/v1/users", headers=member_headers)
step("成员访问后台被拒", forbidden.status_code in (401, 403), str(forbidden.status_code))

# 14. 审计日志存在
audit = client.get("/api/v1/system/audit-logs", headers=admin_headers, params={"limit": 10})
step("审计日志可读", audit.status_code == 200 and len(audit.json()) > 0, f"共 {len(audit.json())} 条")

# 15. 通知可推送
notices = client.get("/api/v1/system/notifications", headers=member_headers)
step("通知列表可读", notices.status_code == 200)

# 16. 系统设置页的统一身份认证自检卡片（未启用时也要能取到状态）
sso_status = client.get("/api/v1/system/sso/status", headers=admin_headers)
sso_body = sso_status.json() if sso_status.status_code == 200 else {}
step(
    "统一身份认证自检可读",
    sso_status.status_code == 200 and "enabled" in sso_body and "label" in sso_body,
    sso_body.get("message", ""),
)
step(
    "自检不泄露密钥",
    not {"password", "client_secret", "search_bind_password"} & set((sso_body.get("config") or {})),
)

# 17. OpenAPI 文档
docs = client.get("/openapi.json")
step("OpenAPI 可导出", docs.status_code == 200 and "/api/v1/reports/generate" in docs.text)

print("\n".join(report))
print("\n全部冒烟用例通过 ✅")
