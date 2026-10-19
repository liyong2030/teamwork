import http, { get, post } from './http'
import type {
  AuditLogItem,
  NotificationItem,
  SettingItem,
  SsoStatus,
  SystemInfo,
} from '@/types'

export const systemApi = {
  notifications(params?: { unread_only?: boolean; limit?: number }) {
    return get<NotificationItem[]>('/system/notifications', params)
  },
  unreadCount() {
    return get<{ count: number }>('/system/notifications/unread-count')
  },
  markRead(id: number) {
    return post<{ message: string }>(`/system/notifications/${id}/read`)
  },
  settings() {
    return get<SettingItem[]>('/system/settings')
  },
  updateSetting(key: string, value: string) {
    return http
      .put<{ message: string }>(`/system/settings/${key}`, { value })
      .then((r) => r.data)
  },
  auditLogs(params?: { action?: string; actor_id?: number; limit?: number }) {
    return get<AuditLogItem[]>('/system/audit-logs', params)
  },
  runJob(jobId: string) {
    return post<{ message: string }>(`/system/jobs/${jobId}/run`)
  },
  testEmail(toEmail: string) {
    return post<{ message: string }>('/system/email/test', { to_email: toEmail })
  },
  info() {
    return get<SystemInfo>('/system/info')
  },
  /** 统一身份认证自检（管理员）：配置概览 + IdP 连通性 */
  ssoStatus() {
    return get<SsoStatus>('/system/sso/status')
  },
}
