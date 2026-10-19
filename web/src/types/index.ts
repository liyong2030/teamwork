/** 后端实际返回结构（与 app/api/v1 各序列化函数一一对应）。 */

// ---------------------------------------------------------------- 用户与部门
export interface UserItem {
  id: number
  username: string
  full_name: string
  email: string | null
  is_active: boolean
  is_superuser: boolean
  must_change_password: boolean
  last_login_at: string | null
  created_at: string
  department_ids: number[]
  leader_department_ids: number[]
  department_names: string[]
  auth_source: string
  auth_source_label: string
  external_id: string | null
  is_sso: boolean
}

export interface UserPayload {
  username: string
  full_name: string
  email?: string | null
  password?: string | null
  department_ids?: number[]
  leader_department_ids?: number[]
  is_superuser?: boolean
  is_active?: boolean
}

export interface CurrentUser {
  id: number
  username: string
  full_name: string
  email: string | null
  is_superuser: boolean
  must_change_password: boolean
  department_ids: number[]
  leader_department_ids: number[]
  is_department_leader: boolean
}

export interface PasswordPolicy {
  min_length: number
  require_classes: number
  must_change_password: boolean
}

export interface DepartmentMemberItem {
  user_id: number
  username: string | null
  full_name: string | null
  is_leader: boolean
}

export interface DepartmentItem {
  id: number
  name: string
  parent_id: number | null
  leader_id: number | null
  sort_order: number
  is_active: boolean
  created_at: string
  member_count: number
  members: DepartmentMemberItem[]
}

export interface DepartmentPayload {
  name: string
  parent_id?: number | null
  leader_id?: number | null
  sort_order?: number
  is_active?: boolean
  member_ids?: number[]
  leader_ids?: number[]
}

// ---------------------------------------------------------------- 请假
export interface LeaveItem {
  id: number
  user_id: number
  start_date: string
  end_date: string
  reason: string | null
  status: string
  approver_id: number | null
  approver_name: string | null
  decided_at: string | null
  created_at: string
  username: string | null
  full_name: string | null
  /** 当前登录用户能否审批该条（后端按管辖范围判定，避免前端重复实现） */
  can_decide: boolean
  /** 当前登录用户能否撤回该条 */
  can_cancel: boolean
}

export interface LeavePayload {
  start_date: string
  end_date: string
  reason?: string | null
}

export interface WeekExemption {
  user_id: number
  full_name: string
  leave_id: number
  start_date: string
  end_date: string
  reason: string | null
  week_end: string
}

// ---------------------------------------------------------------- 项目
export interface ProjectItem {
  id: number
  name: string
  code: string
  description: string | null
  department_id: number | null
  department_name: string | null
  owner_id: number | null
  owner_name: string | null
  status: string
  start_date: string | null
  end_date: string | null
  sort_order: number
  created_at: string
  task_total: number
  task_done: number
  overdue_count: number
  member_ids: number[]
}

export interface ProjectPayload {
  name: string
  /** 留空则由后端自动生成（PRJ-2026-001） */
  code?: string | null
  description?: string | null
  department_id?: number | null
  owner_id?: number | null
  status?: string
  start_date?: string | null
  end_date?: string | null
  member_ids?: number[]
}

// ---------------------------------------------------------------- 任务
export interface ChecklistEntry {
  text: string
  done: boolean
}

export interface TaskItem {
  id: number
  project_id: number
  project_name: string | null
  project_code: string | null
  title: string
  description: string | null
  owner_id: number | null
  owner_name: string | null
  collaborator_ids: number[]
  priority: string
  status: string
  start_date: string | null
  due_date: string | null
  progress: number
  estimated_hours: number | null
  actual_hours: number | null
  checklist: ChecklistEntry[]
  tags: string[]
  sort_order: number
  is_overdue: boolean
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface TaskPayload {
  title: string
  project_id: number
  description?: string | null
  owner_id?: number | null
  collaborator_ids?: number[]
  priority?: string
  status?: string
  start_date?: string | null
  due_date?: string | null
  progress?: number | null
  estimated_hours?: number | null
  actual_hours?: number | null
  tags?: string[]
  checklist?: ChecklistEntry[]
}

export interface BoardColumn {
  status: string
  title: string
  tasks: TaskItem[]
}

export interface TaskLogItem {
  id: number
  task_id: number
  from_status: string | null
  to_status: string
  from_progress: number | null
  to_progress: number | null
  operator_id: number
  operator_name: string | null
  remark: string | null
  created_at: string
}

// ---------------------------------------------------------------- 周报
export interface ReportItem {
  id: number
  report_id: number
  section: string
  content: string
  task_id: number | null
  task_title: string | null
  source: string
  sort_order: number
}

export interface ReportSections {
  done: ReportItem[]
  progress: ReportItem[]
  risk: ReportItem[]
  plan: ReportItem[]
}

export interface ReportDetail {
  id: number
  user_id: number
  username: string | null
  full_name: string | null
  week_start: string
  week_label: string | null
  year: number
  week_no: number
  status: string
  status_label: string | null
  version: number
  submitted_at: string | null
  last_edited_at: string | null
  submitted_by_id: number | null
  submitted_by_name: string | null
  proxy_reason: string | null
  reviewed_by_id: number | null
  reviewed_at: string | null
  review_comment: string | null
  is_valid: boolean
  invalid_reason: string | null
  is_locked: boolean
  items: ReportItem[]
  sections: ReportSections | null
  char_count: number
  created_at: string
  updated_at: string
}

export interface ReportItemIn {
  section: string
  content: string
  task_id?: number | null
  source?: string
}

export interface MyWeekStatus {
  week_start: string
  week_label: string
  deadline_at: string
  finalize_at: string
  deadline_passed: boolean
  has_report: boolean
  report_id: number | null
  status: string
  status_label: string
  submitted_at: string | null
  can_edit: boolean
  can_generate: boolean
}

export interface ReportRevision {
  id: number
  report_id: number
  version: number
  snapshot: Record<string, unknown>
  editor_id: number
  editor_name: string | null
  reason: string | null
  created_at: string
}

// ---------------------------------------------------------------- 统计
export interface StatCounts {
  required: number
  exempt: number
  submitted: number
  ontime: number
  late: number
  makeup: number
  missing: number
  by_proxy: number
  valid: number
}

export interface OverviewData extends StatCounts {
  week_start: string
  week_label: string
  ontime_rate: number
  submit_rate: number
  missing_rate: number
  valid_rate: number
  finalized: boolean
}

export interface DepartmentStatRow extends StatCounts {
  department_id: number
  department_name: string
  ontime_rate: number
  submit_rate: number
}

export interface TrendRow extends StatCounts {
  week_start: string
  week_label: string
  ontime_rate: number
  submit_rate: number
  finalized: boolean
}

export interface PeopleRow {
  user_id: number
  username: string
  full_name: string
  department_name: string | null
  required: boolean
  exempt_reason: string | null
  status: string
  status_label: string
  submitted_at: string | null
  is_valid: boolean
  continuous_missing: number
}

export interface MyHistoryRow {
  week_start: string
  week_label: string
  status: string
  status_label: string
  submitted_at: string | null
  is_valid: boolean
  report_id: number | null
}

export interface StatSnapshot {
  id: number
  week_start: string
  department_id: number
  department_name: string | null
  required_count: number
  exempt_count: number
  submitted_count: number
  ontime_count: number
  late_count: number
  makeup_count: number
  missing_count: number
  by_proxy_count: number
  valid_count: number
  finalized: boolean
  created_at: string
}

// ---------------------------------------------------------------- 系统
export interface NotificationItem {
  id: number
  user_id: number
  title: string
  content: string
  channel: string
  link: string | null
  is_read: boolean
  created_at: string
}

export interface AuditLogItem {
  id: number
  action: string
  actor_id: number | null
  actor_name: string | null
  target_type: string | null
  target_id: number | null
  detail: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

export interface SettingItem {
  key: string
  value: string
  description: string | null
  updated_at: string
}

export interface SystemInfo {
  app_name: string
  env: string
  timezone: string
  deadline: string
  finalize: string
  valid_min_chars: number
  scheduler_enabled: boolean
  email_enabled: boolean
}

/** 统一身份认证自检结果（GET /system/sso/status，仅管理员） */
export interface SsoStatus {
  enabled: boolean
  /** 登录页展示的认证入口名称 */
  label: string
  healthy?: boolean
  message: string
  /** 脱敏后的协议配置（不含任何密钥），按 provider 不同字段不同 */
  config?: Record<string, unknown>
  auto_create?: boolean
  bind_existing?: boolean
  default?: boolean
}

export interface MemberOption {
  id: number
  username: string
  full_name: string
  email: string | null
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
