import http, { get, post } from './http'
import type { MemberOption, TaskItem, TaskLogItem, TaskPayload } from '@/types'

export const taskApi = {
  list(params: Record<string, unknown>) {
    return get<TaskItem[]>('/tasks', params)
  },
  mine(onlyOpen = true) {
    return get<TaskItem[]>('/tasks/mine', { only_open: onlyOpen })
  },
  detail(id: number) {
    return get<TaskItem>(`/tasks/${id}`)
  },
  create(payload: TaskPayload) {
    return post<{ message: string; id: number }>('/tasks', payload)
  },
  update(id: number, payload: Partial<TaskPayload>) {
    return http.patch<{ message: string; id: number }>(`/tasks/${id}`, payload).then((r) => r.data)
  },
  changeStatus(id: number, toStatus: string, progress?: number | null, remark?: string) {
    return post<{ message: string; id: number }>(`/tasks/${id}/status`, {
      to_status: toStatus,
      progress: progress ?? null,
      remark: remark ?? null,
    })
  },
  move(id: number, toStatus: string, beforeId?: number | null) {
    return post<{ message: string; id: number }>(`/tasks/${id}/move`, {
      to_status: toStatus,
      before_id: beforeId ?? null,
    })
  },
  setCollaborators(id: number, userIds: number[]) {
    return post<{ message: string; id: number }>(`/tasks/${id}/collaborators`, {
      user_ids: userIds,
    })
  },
  toggleChecklist(id: number, index: number, done: boolean) {
    return post<{ message: string; id: number }>(`/tasks/${id}/checklist`, { index, done })
  },
  cancel(id: number) {
    return http.delete<{ message: string; id: number }>(`/tasks/${id}`).then((r) => r.data)
  },
  logs(id: number) {
    return get<TaskLogItem[]>(`/tasks/${id}/logs`)
  },
  memberOptions() {
    return get<MemberOption[]>('/tasks/collaborators/options')
  },
}
