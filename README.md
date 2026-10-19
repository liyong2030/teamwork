# 团队协作管理系统（CTMS）

面向团队内部的 **周报提交统计** 与 **项目任务管理** 一体化平台，B/S 架构。

设计核心：**周报由任务自动生成草稿**。

> 团队成员平时更新任务状态，周五点击「生成周报草稿」，系统自动汇总本周工作进展、本周工作总结、下周工作计划与需协调事项，人只需补充总结与风险即可提交。
> 周报统计与任务管理因此共享同一份数据源，杜绝人工对账。

---

## 1. 技术栈

| 层 | 选型 | 版本约束 |
|---|---|---|
| 后端框架 | FastAPI | `>=0.110,<1.0` |
| ORM | SQLAlchemy | `>=2.0,<3.0`（2.0 风格 Mapped / DeclarativeBase） |
| 数据校验 | Pydantic v2 + pydantic-settings | `>=2.0` |
| 迁移 | Alembic | `>=1.13` |
| 密码哈希 | argon2-cffi | `>=23.1`（Argon2id） |
| 令牌 | PyJWT | `>=2.8` |
| 定时任务 | APScheduler | `>=3.10,<4.0` |
| 统一身份认证 | httpx（CAS / OIDC）+ ldap3（LDAP/AD） | `>=0.26` / `>=2.9` |
| 数据库 | PostgreSQL 16（生产）/ SQLite 3（开发、单机降级） | — |
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + ECharts + Pinia | — |
| 部署 | Docker Compose / Nginx | — |

最低 Python 版本：**3.10**（代码同时给出 3.9 兼容说明，见文末）。

---

## 2. 目录结构

```
teamwork/
├── README.md                      本文件
├── docker-compose.yml
├── docs/
│   ├── 01-需求规格说明书.md
│   ├── 02-数据库设计说明书.md
│   └── 03-RESTful接口文档.md
├── server/                        后端
│   ├── app/
│   │   ├── main.py                应用入口 / 生命周期
│   │   ├── core/                  配置、安全、依赖注入、异常、日志
│   │   ├── db/                    engine / session / 初始化
│   │   ├── models/                SQLAlchemy 数据模型
│   │   ├── schemas/               Pydantic 出入参
│   │   ├── api/v1/                REST 路由
│   │   ├── services/              业务逻辑（周报生成 / 统计 / 通知 / 请假）
│   │   │   └── sso/               统一身份认证适配器（cas / oidc / ldap）
│   │   ├── tasks/                 APScheduler 定时任务
│   │   └── utils/                 周次计算、下载头、字典
│   ├── scripts/
│   │   ├── create_admin.py        初始管理员（随机口令，仅打印一次）
│   │   └── smoke_check.py         端到端冒烟验证
│   ├── alembic/                   数据库迁移
│   ├── tests/                     pytest（周报生成 / 统计口径 / 认证权鉴）
│   ├── pyproject.toml
│   └── Dockerfile
└── web/                           前端
    ├── src/{api,router,stores,views,components,layouts,types,utils}
    ├── Dockerfile
    ├── nginx.conf
    └── package.json
```

---

## 3. 快速启动

### 3.1 开发环境（SQLite，无需数据库服务）

推荐用统一入口 `tw.py`（会自动挑 `.venv` 里的解释器，不会踩 `ModuleNotFoundError`）：

```bash
cd server
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python tw.py init           # 建表 + 默认配置（首次必做）
python tw.py create-admin   # 创建首个管理员（随机口令只打印一次）
python tw.py run            # 启动后端 http://127.0.0.1:8000
```

升级代码后如果数据库结构有变化，执行：

```bash
python tw.py migrate        # 升级数据库结构（重复执行安全）
python tw.py migrate current      # 查看当前版本
python tw.py migrate stamp head   # 应急：手动登记版本（不改表结构）
```

`migrate` 内部走 Alembic，并会自动处理「先用 `tw.py init` 直接建表、没有版本记录」的存量库：
与当前模型比对后决定是登记为最新版、还是先打基线再补齐迁移，因此不会重复建表。

Windows 下也可直接双击 `server/tw.bat`，按提示输入命令（`init` / `create-admin` / `run`）。

等价的原始命令（需先激活虚拟环境）：

```bash
source .venv/bin/activate
cp .env.example .env                                    # 首次运行时 tw.py 也会自动生成
python scripts/create_admin.py
uvicorn app.main:app --reload --port 8000
```

前端：

```bash
cd web
npm install
npm run dev                                             # http://localhost:5173
```

### 3.2 生产部署（Docker Compose）

```bash
cp .env.example .env
# 必须修改：POSTGRES_PASSWORD、SECRET_KEY
docker compose up -d --build
docker compose exec server python scripts/create_admin.py
```

访问 `http://<host>`（Nginx 80 端口，`/api` 反代后端）。

> 多副本部署时，`SCHEDULER_ENABLED` 只能在其中一台实例设为 `true`，否则会出现重复推送。

### 3.3 Windows 单机裸跑（无 Docker 场景）

```powershell
cd server
python -m venv .venv; .\.venv\Scripts\activate
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

python tw.py init
python tw.py create-admin
python tw.py run                 # 默认 127.0.0.1:8000，可用环境变量 APP_HOST / APP_PORT 覆盖
```

> 未创建虚拟环境时，脚本会自动探测 `server/.venv`；都不存在则打印安装指令后退出，
> 不会出现「装了依赖却还是报 ModuleNotFoundError」的情况。
> 数据库路径 `sqlite:///./data/app.db` 已锚定到 `server/` 目录，从任意工作目录启动都指向同一个库。

前端构建后用任意静态服务器托管 `web/dist`，或直接以 Nginx 反代 `/api` 到 `http://127.0.0.1:8000`。

---

## 4. 自检脚本

```bash
# 端到端冒烟：真实拉起 FastAPI，跑通「建项目 → 建任务 → 流转 → 生成周报 →
# 提交 → 修订留痕 → 统计 → 导出 → 请假豁免 → 权限拦截 → 审计」全链路
cd server && python scripts/smoke_check.py

# 单元测试（周报生成算法 / 统计口径 / 口令策略与权鉴）
cd server && pytest tests -q

# 前端类型检查 + 生产构建
cd web && npx vue-tsc --noEmit && npm run build
```

---

## 4. 核心业务口径（速查）

| 项 | 口径 |
|---|---|
| 周报周期 | 自然周：周一 00:00:00 ~ 周日 23:59:59（ISO 周） |
| 提交截止 | **当周五 18:00**（准时线） |
| 迟到窗口 | 周五 18:00 之后 ~ **下周一 09:30** |
| 未提交 | 下周一 09:30 定版时仍无记录 |
| 数据切片 | 无论何时提交，草稿内容锁定为**自然周**内的任务流水与终态 |
| 有效周报 | 「本周工作总结」或「下周工作计划」至少一段非空且 ≥ 20 字 |
| 应提交人数 | 该部门在册在职成员 − 已审批通过的请假（周一时点快照） |
| 提醒时刻 | 周五 10:00 / 周五 17:00 / 周日 20:00 / 周一 08:30 / 周一 09:30 定版 |
| 状态互斥 | 准时 / 迟到 / 补交 / 未提交 / 代提交 —— 五态互斥，补交永不洗白历史 |

详细口径见 `docs/01-需求规格说明书.md`。

---

## 5. 角色与权限

| 角色 | 判定方式 | 可见范围 |
|---|---|---|
| 普通成员 | 默认 | 自己的任务、自己的周报；本部门成员列表只读 |
| 部门组长 | `department_members.is_leader = true` | 本部门全部周报与统计、可代提交、可退回 |
| 系统管理员 | `users.is_superuser = true` | 全局数据、部门/用户/系统配置、审计日志 |

---

## 6. 环境变量

全部配置项集中在 `server/.env`，参见 `.env.example`。关键项：

| 变量 | 说明 | 默认 |
|---|---|---|
| `APP_ENV` | `dev` / `prod` | `dev` |
| `DATABASE_URL` | SQLAlchemy DSN | `sqlite+aiosqlite:///./data/app.db` |
| `SECRET_KEY` | JWT 签名密钥，**生产必须更换** | 随机生成 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access Token 有效期 | `480`（8h） |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh Token 有效期 | `7` |
| `REPORT_DEADLINE_WEEKDAY` | 截止日（周几） | `5`（周五） |
| `REPORT_DEADLINE_TIME` | 截止时间 | `18:00` |
| `REPORT_FINALIZE_OFFSET_HOURS` | 定版延后小时数 | `63.5`（周一 09:30） |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | 邮件提醒 | 空 = 关闭邮件，仅站内 |

统一身份认证相关（`AUTH_SSO_*` 及各协议段）较多，完整清单见
`.env.example` 与 `server/.env.example` 的「统一身份认证」小节。

---

## 6.1 统一身份认证（SSO）

**模式：后端代理校验**——登录页照旧提交账号 + 口令，由后端拿这对凭据去 IdP 校验，
通过即签发本系统 JWT。**只做认证，不同步组织架构**（部门、组长身份、角色仍由本地维护）。

### 支持矩阵

| 协议 | 状态 | 校验方式 | 关键配置 |
|---|:--:|---|---|
| CAS | ✅ | REST 换 TGT → 换 ST → `serviceValidate` 解析 XML | `CAS_SERVER_URL`、`CAS_SERVICE_URL` |
| OIDC | ✅ | password grant → userinfo（或解析 id_token） | `OIDC_ISSUER` / `OIDC_TOKEN_ENDPOINT`、`OIDC_CLIENT_ID/SECRET` |
| LDAP / AD | ✅ | simple bind（直接 bind 或先查后 bind） | `LDAP_SERVER_URI`、`LDAP_BIND_DN_TEMPLATE` 或 `LDAP_BASE_DN` |
| SAML 2.0 | ⛔ | 需浏览器跳转（SP-initiated），与本模式不兼容 | 二期实现 |

### 接入步骤

1. 在 `.env` 设置 `AUTH_SSO_ENABLED=true` 与 `AUTH_SSO_PROVIDER=cas|oidc|ldap`，填好对应协议段；
2. 重启服务，用管理员登录 → 后台「系统设置」查看 **统一身份认证自检**
   （`GET /system/sso/status`），确认连通性与生效配置；
3. 让一名成员用 IdP 账号登录一次，验证自动建号/绑定符合预期；
4. 稳定后再视情况打开 `AUTH_SSO_DEFAULT=true`（全员默认走 SSO）。

### 账号解析规则

| 优先级 | 条件 | 行为 |
|:--:|---|---|
| 1 | 命中 `(auth_source, external_id)` | 直接登录，仅补全空的姓名/邮箱 |
| 2 | 同名本地账号 + `AUTH_SSO_BIND_EXISTING=true` | 绑定为 SSO 账号，清除本地口令，**保留部门与组长身份** |
| 3 | 无匹配 + `AUTH_SSO_AUTO_CREATE=true` | 自动建号：普通成员、无本地口令、落入「未分组」 |
| — | 都不满足 | 拒绝并提示联系管理员 |

### 三条安全底线

1. **超级管理员账号不会被自动绑定** —— 它是 IdP 故障时的本地应急通道，只能由管理员手动绑定
   （`POST /users/{id}/sso-bind`）。
2. **SSO 账号禁用本地口令登录** —— 本地入口返回 `400 sso_required`，前端自动改走 IdP，
   用户只需输入一次账号密码。
3. **IdP 不可达报 503 `sso_unavailable`** —— 绝不能混同为"用户名或密码错误"，否则故障时无法定位。

> 升级已有库请执行 `alembic upgrade head`（迁移 `49eaab6013e1` 会为存量账号回填
> `auth_source='local'`，并把 `hashed_password` 改为可空）。

---

## 7. 后续演进（明确不做，二期评估）

- 子任务层级、甘特图、任务依赖线
- SAML 2.0 / 企业微信 / 钉钉对接（SSO 适配器已预留扩展点 `app/services/sso/`）
- 工时计费、OKR、绩效考核
- 移动端原生 App（当前为响应式 Web）

---

## 8. 免责说明

本工程为团队协作场景的内部管理系统实现。上线生产前请完成安全审计（HTTPS 强制、备份策略、口令策略复核）与压力测试。
