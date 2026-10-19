import http from './http'
import { get } from './http'
import type {
  DepartmentStatRow,
  MyHistoryRow,
  OverviewData,
  PeopleRow,
  StatSnapshot,
  TrendRow,
} from '@/types'

export const statsApi = {
  overview(params?: { week_start?: string; department_id?: number }) {
    return get<OverviewData>('/stats/overview', params)
  },
  departments(params?: { week_start?: string }) {
    return get<DepartmentStatRow[]>('/stats/departments', params)
  },
  trend(params?: { weeks?: number; department_id?: number }) {
    return get<TrendRow[]>('/stats/trend', params)
  },
  people(params?: { week_start?: string; department_id?: number }) {
    return get<PeopleRow[]>('/stats/people', params)
  },
  snapshots(params?: { week_start?: string; department_id?: number }) {
    return get<StatSnapshot[]>('/stats/snapshots', params)
  },
  myHistory(weeks = 12) {
    return get<MyHistoryRow[]>('/stats/my-history', { weeks })
  },
  departmentOptions() {
    return get<Array<{ id: number; name: string }>>('/stats/departments/options')
  },
  async download(
    payload: { week_start: string; department_id?: number | null; fmt: 'xlsx' | 'csv' },
    filename: string,
  ) {
    const { data } = await http.post('/stats/export', payload, { responseType: 'blob' })
    const blob = data as unknown as Blob
    if (blob.type && blob.type.includes('json')) {
      // 服务端返回的是错误 JSON，转为可读提示
      const text = await blob.text()
      let message = '导出失败'
      try {
        message = (JSON.parse(text) as { message?: string }).message || message
      } catch {
        /* 忽略解析异常，使用默认文案 */
      }
      throw new Error(message)
    }
    const blobUrl = window.URL.createObjectURL(new Blob([data as BlobPart]))
    const link = document.createElement('a')
    link.href = blobUrl
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(blobUrl)
  },
}
