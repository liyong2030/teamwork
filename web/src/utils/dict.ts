/** 周报状态 / 任务状态 / 优先级的展示字典，与后端 enums.py 保持一致。 */

export const REPORT_STATUS_MAP: Record<string, { label: string; type: string }> = {
  draft: { label: '草稿', type: 'info' },
  ontime: { label: '准时', type: 'success' },
  late: { label: '迟到', type: 'warning' },
  makeup: { label: '补交', type: 'warning' },
  missing: { label: '未提交', type: 'danger' },
  by_proxy: { label: '代提交', type: 'warning' },
}

export const TASK_STATUS_MAP: Record<string, { label: string; type: string; color: string }> = {
  todo: { label: '待办', type: 'info', color: '#909399' },
  in_progress: { label: '进行中', type: 'primary', color: '#409eff' },
  blocked: { label: '已阻塞', type: 'danger', color: '#f56c6c' },
  done: { label: '已完成', type: 'success', color: '#67c23a' },
  cancelled: { label: '已取消', type: 'info', color: '#c0c4cc' },
}

export const TASK_PRIORITY_MAP: Record<string, { label: string; type: string }> = {
  p0: { label: 'P0 最高', type: 'danger' },
  p1: { label: 'P1 高', type: 'warning' },
  p2: { label: 'P2 中', type: 'primary' },
  p3: { label: 'P3 低', type: 'info' },
}

/** 周报四段结构：数组顺序即页面从上到下的填写顺序 */
export const REPORT_SECTIONS = [
  { key: 'progress', label: '本周工作进展', icon: 'Loading', color: '#409eff' },
  { key: 'done', label: '本周工作总结', icon: 'CircleCheck', color: '#67c23a' },
  { key: 'plan', label: '下周工作计划', icon: 'Promotion', color: '#8e7cfb' },
  { key: 'risk', label: '需协调与帮助', icon: 'WarningFilled', color: '#e6a23c' },
] as const

export const LEAVE_STATUS_MAP: Record<string, { label: string; type: string }> = {
  pending: { label: '待审批', type: 'warning' },
  approved: { label: '已通过', type: 'success' },
  rejected: { label: '已驳回', type: 'danger' },
}

export const PROJECT_STATUS_MAP: Record<string, { label: string; type: string }> = {
  planning: { label: '筹备中', type: 'warning' },
  active: { label: '进行中', type: 'success' },
  paused: { label: '已暂停', type: 'warning' },
  archived: { label: '已归档', type: 'info' },
}

/** ISO 周起始日（周一），供统计筛选使用 */
export function mondayOf(date: Date): string {
  const d = new Date(date)
  const day = d.getDay() === 0 ? 7 : d.getDay()
  d.setDate(d.getDate() - day + 1)
  return d.toISOString().slice(0, 10)
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-'
  // 后端已格式化为「YYYY-MM-DD HH:mm」时直接返回，避免二次解析产生时区偏移
  const already = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.exec(value)
  if (already) return already[0]
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
