import http, { get, post } from './http'
import type { BoardColumn, ProjectItem, ProjectPayload } from '@/types'

export const projectApi = {
  list(params?: { keyword?: string; status?: string }) {
    return get<ProjectItem[]>('/projects', params)
  },
  detail(id: number) {
    return get<ProjectItem>(`/projects/${id}`)
  },
  nextCode() {
    return get<{ code: string }>('/projects/next-code')
  },
  create(payload: ProjectPayload) {
    return post<{ message: string; id: number }>('/projects', payload)
  },
  update(id: number, payload: Partial<ProjectPayload>) {
    return http.patch<{ message: string }>(`/projects/${id}`, payload).then((r) => r.data)
  },
  board(id: number) {
    return get<BoardColumn[]>(`/projects/${id}/board`)
  },
  summary(id: number) {
    return get<Record<string, unknown>>(`/projects/${id}/summary`)
  },
}
