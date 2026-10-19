import { downloadFile, get, post } from './http'
import type {
  MyWeekStatus,
  ReportDetail,
  ReportItemIn,
  ReportRevision,
} from '@/types'

export const reportApi = {
  myWeekStatus() {
    return get<MyWeekStatus>('/reports/my-week-status')
  },
  generate(force = false, weekStart?: string) {
    return post<ReportDetail>('/reports/generate', {
      force,
      week_start: weekStart || null,
    })
  },
  saveDraft(items: ReportItemIn[], weekStart?: string) {
    return post<{ message: string; id: number }>('/reports/draft', {
      items,
      week_start: weekStart || null,
    })
  },
  submit(items: ReportItemIn[], weekStart?: string, reason?: string) {
    return post<ReportDetail>('/reports/submit', {
      items,
      week_start: weekStart || null,
      reason: reason || null,
    })
  },
  proxySubmit(userId: number, items: ReportItemIn[], reason: string, weekStart?: string) {
    return post<ReportDetail>('/reports/proxy', {
      user_id: userId,
      items,
      reason,
      week_start: weekStart || null,
    })
  },
  mine(params?: { limit?: number }) {
    return get<ReportDetail[]>('/reports/mine', params)
  },
  mineOfWeek(weekStart: string) {
    return get<ReportDetail>(`/reports/mine/${weekStart}`)
  },
  list(params?: Record<string, unknown>) {
    return get<ReportDetail[]>('/reports', params)
  },
  detail(id: number) {
    return get<ReportDetail>(`/reports/${id}`)
  },
  revisions(id: number) {
    return get<ReportRevision[]>(`/reports/${id}/revisions`)
  },
  revisionDetail(id: number, version: number) {
    return get<ReportRevision>(`/reports/${id}/revisions/${version}`)
  },
  review(id: number, approved: boolean, comment?: string) {
    return post<{ message: string }>(`/reports/${id}/review`, { approved, comment })
  },
  /** 导出个人周报。后端当前产出 Markdown（周报-用户名-周起始.md） */
  async exportMy(weekStart: string) {
    await downloadFile('/reports/export', { week_start: weekStart }, `周报_${weekStart}.md`)
  },
}
