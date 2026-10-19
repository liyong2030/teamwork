import http, { get, post } from './http'
import type {
  DepartmentItem,
  DepartmentPayload,
  LeaveItem,
  LeavePayload,
  UserItem,
  UserPayload,
  WeekExemption,
} from '@/types'

export const userApi = {
  list(params?: Record<string, unknown>) {
    return get<{ items: UserItem[]; total: number; page: number; page_size: number }>(
      '/users',
      params,
    )
  },
  detail(id: number) {
    return get<UserItem>(`/users/${id}`)
  },
  create(payload: UserPayload) {
    return post<{ message: string; temp_password: string }>('/users', payload)
  },
  update(id: number, payload: Partial<UserPayload>) {
    return http.patch<{ message: string }>(`/users/${id}`, payload).then((r) => r.data)
  },
  resetPassword(id: number, newPassword?: string) {
    return post<{ message: string; temp_password: string }>(`/users/${id}/reset-password`, {
      new_password: newPassword || null,
    })
  },
  ssoBind(id: number, payload: { source: string; external_id: string }) {
    return post<{ message: string }>(`/users/${id}/sso-bind`, payload)
  },
  ssoUnbind(id: number, newPassword?: string) {
    return post<{ message: string; temp_password: string }>(`/users/${id}/sso-unbind`, {
      new_password: newPassword || null,
    })
  },
  remove(id: number) {
    return http.delete<{ message: string }>(`/users/${id}`).then((r) => r.data)
  },
  myProfile() {
    return get<Record<string, unknown>>('/users/me/profile')
  },
  updateMyProfile(payload: Record<string, unknown>) {
    return http.patch<{ message: string }>('/users/me/profile', payload).then((r) => r.data)
  },
}

export const departmentApi = {
  list() {
    return get<DepartmentItem[]>('/departments')
  },
  create(payload: DepartmentPayload) {
    return post<{ message: string; id: number }>('/departments', payload)
  },
  update(id: number, payload: Partial<DepartmentPayload>) {
    return http.patch<{ message: string }>(`/departments/${id}`, payload).then((r) => r.data)
  },
  deactivate(id: number) {
    return http.delete<{ message: string }>(`/departments/${id}`).then((r) => r.data)
  },
  assignMember(id: number, userId: number, isLeader = false) {
    return post<{ message: string }>(`/departments/${id}/members`, {
      user_id: userId,
      is_leader: isLeader,
    })
  },
  removeMember(id: number, userId: number) {
    return http
      .delete<{ message: string }>(`/departments/${id}/members/${userId}`)
      .then((r) => r.data)
  },
}

export const leaveApi = {
  list(params?: { user_id?: number; status?: string; limit?: number }) {
    return get<LeaveItem[]>('/leaves', params)
  },
  detail(id: number) {
    return get<LeaveItem>(`/leaves/${id}`)
  },
  create(payload: LeavePayload) {
    return post<{ message: string; id: number }>('/leaves', payload)
  },
  decide(id: number, approved: boolean, comment?: string) {
    return post<{ message: string }>(`/leaves/${id}/decide`, { approved, comment })
  },
  cancel(id: number) {
    return http.delete<{ message: string }>(`/leaves/${id}`).then((r) => r.data)
  },
  weekExemptions(weekStart: string) {
    return get<WeekExemption[]>(`/leaves/week/${weekStart}`)
  },
}
