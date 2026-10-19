# 03 RESTful 接口文档

> 团队协同管理平台（周报统计 + 任务管理）后端接口说明。
> 基础路径：`/api/v1`　文件格式：`application/json`（导出接口除外）
> 认证方式：`Authorization: Bearer <access_token>`（除登录接口）
> 在线调试：服务启动后访问 `http://<host>:8000/docs`（Swagger UI）或 `/redoc`

---

## 1. 通用约定

### 1.1 认证令牌

| 令牌 | 有效期 | 用途 |
|---|---|---|
| `access_token` | 8 小时 | 每次业务请求携带 |
| `refresh_token` | 7 天 | 仅用于 `POST /auth/refresh` 换取新令牌 |

前端把令牌存放在 `localStorage`，请求由 Axios 拦截器自动附加；401 且存在
`refresh_token` 时自动刷新并重放原请求，失败则跳转登录页。

### 1.2 统一响应结构

成功：由各接口自行定义的 JSON 对象。

失败：

```json
{
  "message": "错误描述",
  "code": "业务错误码"
}
```

| HTTP 状态 | code 取值 | 场景 |
|---|---|---|
| 400 | `app_error` / `validation_error` | 业务规则不满足、参数不合法 |
| 401 | `auth_error` | 未认证 / 令牌失效 |
| 403 | `permission_denied` | 越权访问 |
| 404 | `not_found` | 资源不存在 |
| 409 | `conflict_state` | 状态冲突（如周报已定版不可改） |
| 422 | `weak_password` / `validation_error` | 口令强度不足、字段校验失败 |

### 1.3 分页约定

列表类接口统一使用 `limit` / `offset`；用户管理使用 `page` / `page_size`
并返回 `{ items, total, page, page_size }`。

### 1.4 角色与可见范围

| 角色 | 判定方式 | 可见范围 |
|---|---|---|
| 管理员 | `is_superuser = true` | 全量数据 |
| 组长 | `leader_department_ids` 非空 | 管辖部门的周报、任务、统计，外加本人所属项目 |
| 成员 | 其余 | 仅本人的周报；参与的项目与任务 |

---

## 2. 认证模块 `/auth`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/login` | 登录，返回双令牌 |
| POST | `/auth/refresh` | 用 refresh_token 换新令牌 |
| GET | `/auth/me` | 当前用户上下文 |
| POST | `/auth/change-password` | 自助改密（须校验原密码） |
| POST | `/auth/logout` | 登出（写审计日志） |
| GET | `/auth/password-policy` | 口令策略：长度与字符类别要求 |
| GET | `/auth/sso/config` | **统一身份认证配置**（匿名可访问，不含密钥） |
| POST | `/auth/sso/login` | **统一身份认证登录**（后端代理校验，返回同样的双令牌） |

### POST `/auth/login`

请求体

```json
{ "username": "zhangsan", "password": "********" }
```

响应

```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 28800,
  "must_change_password": false
}
```

> `must_change_password = true` 时前端必须跳转到改密页，不允许访问其他页面。
>
> 若账号已接入统一身份认证，本接口返回 **400 `code = sso_required`**，
> 前端应据此**自动改调 `/auth/sso/login`**，用户不需要先判断自己该用哪种方式。

### GET `/auth/sso/config`

登录页据此决定是否展示统一身份认证入口（**不含任何密钥**）。

```json
{
  "enabled": true,
  "default": false,
  "label": "统一身份认证",
  "provider": "cas",
  "auth_source": "cas",
  "choices": [
    { "id": "cas", "label": "CAS", "source": "cas", "supported": true },
    { "id": "oidc", "label": "OIDC / OAuth2", "source": "oidc", "supported": true },
    { "id": "ldap", "label": "LDAP / AD", "source": "ldap", "supported": true },
    { "id": "saml", "label": "SAML 2.0", "source": "saml", "supported": false,
      "reason": "SAML 需浏览器跳转（SP-initiated），当前版本尚未实现" }
  ],
  "detail": { "provider": "cas", "source": "cas", "server_url": "https://cas.example.com" }
}
```

### POST `/auth/sso/login`

请求体与 `POST /auth/login` 完全一致，响应也完全一致。差别只在**谁校验这对凭据**。

| 结果 | HTTP | code | 说明 |
|---|:--:|---|---|
| 校验通过 | 200 | — | 返回双令牌；本地无账号时按策略自动建号/绑定 |
| 用户名或口令错误 | 401 | `unauthorized` | 与本地登录措辞一致，不区分账号是否存在 |
| **IdP 不可达/配置有误** | **503** | `sso_unavailable` | 与"口令错误"严格区分，便于运维定位 |
| 未启用 SSO | 401 | `unauthorized` | 提示未启用统一身份认证 |

### GET `/system/sso/status`（管理员）

「系统设置」页的统一身份认证卡片用它渲染：协议、开关、脱敏配置与连通性结论。
**不返回任何密钥，也不发起真实认证**（不会把管理员口令送往 IdP）。

```json
{
  "enabled": true,
  "label": "统一身份认证",
  "healthy": true,
  "message": "配置完整",
  "config": {
    "provider": "cas",
    "source": "cas",
    "server_url": "https://cas.example.com",
    "rest_path": "/cas/v1/tickets",
    "service_url": "https://teamwork.example.com/login",
    "require_service_ticket": true
  },
  "auto_create": true,
  "bind_existing": true,
  "default": false
}
```

未启用时返回 `{"enabled": false, "label": "统一身份认证", "message": "未启用统一身份认证"}`。

### GET `/auth/me`

```json
{
  "id": 1,
  "username": "zhangsan",
  "full_name": "张三",
  "email": "zhangsan@example.com",
  "is_superuser": false,
  "must_change_password": false,
  "department_ids": [2],
  "leader_department_ids": [2],
  "is_department_leader": true
}
```

---

## 3. 用户管理 `/users`

仅管理员可访问（除 `/users/me/*`）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/users` | 用户列表，支持 `keyword` / `department_id` / `is_active` / 分页 |
| POST | `/users` | 创建用户；不传 password 时返回随机初始口令 |
| GET | `/users/{user_id}` | 用户详情 |
| PATCH | `/users/{user_id}` | 更新资料、部门、角色、在职状态 |
| POST | `/users/{user_id}/reset-password` | 重置密码，返回临时口令（一次性） |
| DELETE | `/users/{user_id}` | 停用用户 |
| POST | `/users/{user_id}/sso-bind` | **绑定统一身份** `{ source, external_id }` |
| POST | `/users/{user_id}/sso-unbind` | **解绑统一身份**，返回一次性初始口令 |
| GET | `/users/me/profile` | 本人资料 |
| PATCH | `/users/me/profile` | 修改本人资料 |

### 统一身份绑定管理

```json
// POST /users/12/sso-bind
{ "source": "cas", "external_id": "idp-9527" }

// POST /users/12/sso-unbind
{ "message": "已解绑统一身份，请转告用户使用新口令登录并修改", "temp_password": "Kd3!xQ9a" }
```

- 绑定后该账号**清除本地口令**，只能通过 IdP 登录；
- 解绑后恢复本地口令登录，生成随机初始口令并强制首次登录改密；
- 同一 `(source, external_id)` 只能绑定一个账号，重复绑定返回冲突提示；
- **超级管理员账号不会被自动绑定**（保留 IdP 故障时的应急通道），只能走这里的手动绑定。

### POST `/users`

```json
{
  "username": "lisi",
  "full_name": "李四",
  "email": "lisi@example.com",
  "department_ids": [2],
  "leader_department_ids": [],
  "is_superuser": false,
  "is_active": true,
  "password": null
}
```

响应

```json
{ "message": "用户已创建，初始口令请妥善转达", "temp_password": "Xk9#p2Qm" }
```

> **口令只在创建/重置这一次响应中出现，系统不保存明文**，前端须以弹窗提示管理员立即复制。

---

## 4. 部门管理 `/departments`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/departments` | 部门列表（含成员明细） |
| POST | `/departments` | 创建部门（管理员） |
| PATCH | `/departments/{department_id}` | 更新部门信息/成员/组长（管理员） |
| DELETE | `/departments/{department_id}` | 停用部门（成员不再计入应提交名单） |
| POST | `/departments/{department_id}/members` | 添加成员或设置组长标记 |
| DELETE | `/departments/{department_id}/members/{user_id}` | 移除成员 |

---

## 5. 项目管理 `/projects`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/projects` | 项目列表（`keyword` / `status` 过滤，按权限裁剪） |
| GET | `/projects/next-code` | **预览下一个项目编号**（仅用于表单占位，落库时重新生成） |
| POST | `/projects` | 创建项目（`code` **留空则自动生成**） |
| GET | `/projects/{project_id}` | 项目详情 |
| PATCH | `/projects/{project_id}` | 更新项目 |
| GET | `/projects/{project_id}/board` | **五列看板**：todo / in_progress / blocked / done / cancelled |
| GET | `/projects/{project_id}/summary` | 项目任务分布与逾期统计 |

### 项目编号规则

- 格式 `PRJ-{年份}-{三位序号}`，例如 `PRJ-2026-001`；序号按自然年递增，跨年从 `001` 重新开始；
- 生成时取当前年度已有编号的最大序号 +1，并向后探测跳过已占用值（历史手工编号造成的空洞不会被复用）；
- 调用方可自行填写 `code`，但必须唯一，冲突返回 `400 项目编号 xxx 已存在`；
- `projects.code` 另有数据库唯一约束兜底，并发场景下也不会产生重复编号。

> 看板与项目统计的 `task_total / task_done / overdue_count` 均按**当前用户可见范围**统计，
> 与任务列表口径保持一致。

### ProjectOut

```json
{
  "id": 3,
  "name": "协同平台一期",
  "code": "PRJ-2026-001",
  "description": "周报与任务闭环",
  "department_id": 2,
  "department_name": "研发中心",
  "owner_id": 1,
  "owner_name": "张三",
  "status": "active",
  "start_date": "2026-10-01",
  "end_date": "2026-12-31",
  "sort_order": 0,
  "task_total": 42,
  "task_done": 18,
  "overdue_count": 3,
  "member_ids": [1, 4, 7]
}
```

---

## 6. 任务管理 `/tasks`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/tasks` | 任务列表：`project_id` / `owner_id` / `participant_id` / `status` / `keyword`（**按可见范围裁剪**） |
| GET | `/tasks/mine` | 我负责或参与的任务，`only_open=true` 仅未完结 |
| POST | `/tasks` | 创建任务 |
| GET | `/tasks/{task_id}` | 任务详情 |
| PATCH | `/tasks/{task_id}` | 更新任务字段（含 checklist） |
| POST | `/tasks/{task_id}/status` | **状态流转**（写流水表） |
| POST | `/tasks/{task_id}/move` | 看板拖拽，调整状态与列内排序 |
| POST | `/tasks/{task_id}/checklist` | 勾选检查项 `{ index, done }` |
| DELETE | `/tasks/{task_id}` | 软取消（状态置 `cancelled`，保留历史） |
| GET | `/tasks/{task_id}/logs` | 状态流水记录 |
| POST | `/tasks/{task_id}/collaborators` | 设置协作人 `{ user_ids }` |
| GET | `/tasks/collaborators/options` | 可选成员下拉数据 |

### POST `/tasks/{task_id}/status`

```json
{ "to_status": "done", "progress": 100, "remark": "已完成联调" }
```

> 状态机合法取值：`todo` / `in_progress` / `blocked` / `done` / `cancelled`。
> 每次成功流转都会写一条 `task_status_logs`，**这是周报自动草稿的唯一数据来源**。

### 任务可见性（列表 / 详情 / 看板统一口径）

| 角色 | 可见范围 |
|---|---|
| 管理员 | 全部任务 |
| 组长 | 本部门成员负责的任务 + 归属本部门项目下的任务 |
| 普通成员 | **仅「负责人 = 自己」或「协作人包含自己」的任务** |

不可见的任务在列表中被过滤掉；直接按 ID 访问详情或流水返回 `403 无权查看该任务`。
项目看板 `/projects/{id}/board` 与统计 `/projects/{id}/summary` 同样遵循该口径，
因此卡片上的 `task_total` 与看板里的任务条数始终一致。

### TaskOut（摘要）

```json
{
  "id": 101,
  "project_id": 3,
  "project_name": "协同平台一期",
  "title": "周报生成算法实现",
  "owner_id": 4,
  "owner_name": "李四",
  "collaborator_ids": [7],
  "priority": "P0",
  "status": "in_progress",
  "start_date": "2026-10-13",
  "due_date": "2026-10-17",
  "progress": 70,
  "estimated_hours": 16.0,
  "actual_hours": 12.5,
  "checklist": [{ "text": "单元测试", "done": true }],
  "tags": ["核心"],
  "is_overdue": false,
  "completed_at": null
}
```

---

## 7. 周报模块 `/reports`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/reports/my-week-status` | 本周状态卡片（含截止/定版时刻、能否编辑） |
| POST | `/reports/generate` | **按任务流水生成草稿** `{ week_start?, force? }` |
| GET | `/reports/mine` | 我的周报历史列表 |
| GET | `/reports/mine/{week_start}` | 我指定周的周报全文 |
| POST | `/reports/draft` | 保存草稿 `{ week_start?, items[] }`（已提交可暂存改动，会留痕） |
| POST | `/reports/submit` | 提交周报（生成版本快照并锁定） |
| POST | `/reports/proxy` | **代提交** `{ user_id, week_start?, items[], reason }` |
| GET | `/reports` | 团队周报列表（按周/部门/用户过滤） |
| GET | `/reports/{report_id}` | 周报详情（含四段分组内容） |
| GET | `/reports/{report_id}/revisions` | 修订历史列表 |
| GET | `/reports/{report_id}/revisions/{version}` | 某版本快照 |
| POST | `/reports/{report_id}/review` | 组长审阅 `{ approved, comment? }` |
| GET | `/reports/export` | 导出我的周报 `week_start` + `fmt=xlsx|csv` |

### POST `/reports/draft` 的三种情形

| 周报状态 | 行为 | 前端提示 |
|---|---|---|
| 未提交 | 内容落库，不产生版本、不留痕 | 草稿内容已保存，请及时「提交周报」 |
| **已提交（本周未定版）** | 内容落库 + 版本号 +1 + 写一条修订留痕（reason=保存草稿），**提交状态不变** | 同上 |
| **本周已定版** | 409 拒绝：`本周周报已定版，无法再修改内容，如需更正请联系管理员` | — |

> 「已提交后可暂存」是为了避免用户改完内容点保存却被拦住；口径上仍守住两点：
> 提交时刻判定的状态（准时/迟到/补交）**不被草稿改动改写**，且每次改动都留痕可追溯。

### 周报四段结构

`ReportItemIn`：`{ "section": "done|progress|risk|plan", "content": "...", "task_id": 可选, "source": "auto|manual" }`

展示顺序（填写页 / 详情 / 团队视图 / 导出文件一致）：

| 顺序 | `section` | 名称 |
|:--:|---|---|
| 1 | `progress` | 本周工作进展 |
| 2 | `done` | 本周工作总结 |
| 3 | `plan` | 下周工作计划 |
| 4 | `risk` | 需协调与帮助 |

> 导出 Markdown 的章节标题与顺序同上；有效周报判定取 `done` + `plan` 两段字数之和。
>
> `deadline_at` / `finalize_at` 为**面向展示**的本地时间串（`YYYY-MM-DD HH:mm`，精确到分钟、不带时区后缀），
> 前端可直接渲染；其余 `* _at` 字段仍为 ISO 8601，需按展示时区自行格式化。

### GET `/reports/my-week-status`

```json
{
  "week_start": "2026-10-19",
  "week_label": "2026 年第 43 周",
  "deadline_at": "2026-10-23 18:00",
  "finalize_at": "2026-10-26 09:30",
  "deadline_passed": false,
  "has_report": true,
  "report_id": 512,
  "status": "draft",
  "status_label": "草稿",
  "submitted_at": null,
  "can_edit": true,
  "can_generate": true
}
```

### 周报状态五态互斥

| status | 含义 | 判定逻辑 |
|---|---|---|
| `draft` | 草稿 | 未提交 |
| `ontime` | 准时 | 提交时间 ≤ 当周五 18:00 |
| `late` | 迟到 | 周五 18:00 后 ~ 下周一 09:30 前 |
| `makeup` | 补交 | 定版之后提交，**永不洗白未提交** |
| `missing` | 未提交 | 定版时点仍无记录 |
| `by_proxy` | 代提交 | 组长/管理员代填，记录代提交人与原因 |

---

## 8. 统计看板 `/stats`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/stats/overview` | 总览：应提交/准时/迟到/补交/未交/代提交/有效 及各项比率 |
| GET | `/stats/departments` | 部门横向对比（按准时率降序） |
| GET | `/stats/trend` | 近 N 周趋势（`weeks` ≤ 52），优先读定版快照 |
| GET | `/stats/people` | 成员明细（含是否豁免、连续未交周数） |
| GET | `/stats/snapshots` | 定版快照（冻结数据） |
| POST | `/stats/export` | 导出 Excel / CSV：`{ week_start, department_id?, fmt }` |
| GET | `/stats/my-history` | 我的近 N 周提交记录 |
| GET | `/stats/departments/options` | 当前用户可见部门下拉 |

### GET `/stats/overview`

```json
{
  "week_start": "2026-10-19",
  "week_label": "2026 年第 43 周",
  "required": 46,
  "exempt": 2,
  "submitted": 41,
  "ontime": 35,
  "late": 4,
  "makeup": 1,
  "missing": 5,
  "by_proxy": 1,
  "valid": 39,
  "ontime_rate": 76.09,
  "submit_rate": 89.13,
  "missing_rate": 10.87,
  "valid_rate": 95.12,
  "finalized": false
}
```

**口径说明**

- 应提交人数 = 在册在职成员 − 已审批通过的请假人员
- 准时率分母固定为 `required`，补交/迟到的后续操作不会回填历史比率
- `finalized = true` 表示该周已定版归档，读的是冻结快照

---

## 9. 请假豁免 `/leaves`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/leaves` | 提交请假 `{ start_date, end_date, reason? }` |
| GET | `/leaves` | 请假列表（`user_id` / `status` 过滤，按权限裁剪） |
| GET | `/leaves/{leave_id}` | 请假详情 |
| POST | `/leaves/{leave_id}/decide` | 审批 `{ approved, comment? }`（组长/管理员） |
| DELETE | `/leaves/{leave_id}` | 撤回（已通过的不能撤回） |
| GET | `/leaves/week/{week_start}` | 某周豁免名单 |

> **只有 `approved` 状态的请假会扣减应提交人数**，这是提交率分母的唯一豁免来源。

### 审批权限与动作位

`GET /leaves` 的每条记录都带 `can_decide` / `can_cancel`，前端据此渲染按钮，
避免两端口径漂移导致"按钮能点但接口 403"：

| 角色 | `can_decide`（仅 `pending` 时为真） | `can_cancel` |
|---|---|---|
| 管理员 | 任何人，**含自己**（单人部署否则无人可批） | 自己的 / 已通过除外 |
| 部门组长 | 本部门成员，**不含自己** | 仅自己的 |
| 普通成员 | 否 | 仅自己的 |

`POST /leaves/{id}/decide` 越权时：`自己 → 403 不能审批自己的请假申请`；
`跨部门 → 403 只能审批本部门成员的请假申请`；`已审批过 → 该请假已审批，无法重复处理`。
列表排序为「待审批优先，其余按提交时间倒序」。

---

## 10. 系统模块 `/system`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/system/notifications` | 我的通知（`unread_only`、`limit`） |
| GET | `/system/notifications/unread-count` | 未读数 |
| POST | `/system/notifications/{id}/read` | 标记已读 |
| GET | `/system/settings` | 全部配置项（管理员） |
| PUT | `/system/settings/{key}` | 更新配置 `{ "value": "..." }`（管理员） |
| GET | `/system/audit-logs` | 审计日志（`action` / `actor_id` / `limit`） |
| POST | `/system/jobs/{job_id}/run` | 手动触发定时任务（管理员） |
| POST | `/system/email/test` | 邮件连通性测试 `{ to_email }` |
| GET | `/system/sso/status` | **统一身份认证自检**（管理员；不返回密钥、不发起真实认证） |
| GET | `/system/info` | 运行期信息（截止时刻、定版时刻、时区等） |

### 可手动触发的 job_id

| job_id | 触发时机 | 说明 |
|---|---|---|
| `roll_call` | 周一 00:05 | 生成本周点名名册 |
| `remind_fri_1000` | 周五 10:00 | 首次提醒 |
| `remind_fri_1700` | 周五 17:00 | 截止预警（仅未动笔者） |
| `remind_sun_2000` | 周日 20:00 | 周末催办 |
| `remind_mon_0830` | 周一 08:30 | 最后通牒并抄送组长 |
| `finalize` | 周一 09:30 | 定版结算并推送统计摘要 |

---

## 11. 定时任务说明

五个提醒/定版时点由 APScheduler 调度，受环境变量 `SCHEDULER_ENABLED` 控制，
时区由 `SCHEDULER_TIMEZONE` 指定（默认 `Asia/Shanghai`）。

单次值班表中的搜由 `report_service.submit_report` 在提交时即时判定，
不依赖定时任务——只有「批量提醒」与「定版冻结」才需要调度器。

> 多副本部署时必须把 `SCHEDULER_ENABLED` 仅在其中一台实例设为 `true`，
> 否则会出现重复推送。

---

## 12. 错误处置建议（前端）

| 场景 | 处理 |
|---|---|
| 401 且无 refresh_token | 清空本地令牌 → 跳登录页并带 `redirect` |
| 401 刷新失败 | 同上 |
| 403 | 提示「没有权限执行该操作」，不重试 |
| 409 周报已锁定 | 提示走修订流程，引导填写修改原因 |
| 422 口令强度不足 | 原样展示后端返回的中文提示 |
