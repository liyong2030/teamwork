import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

const ACCESS_KEY = 'ctms_access_token'
const REFRESH_KEY = 'ctms_refresh_token'

export const tokenStore = {
  get access() {
    return localStorage.getItem(ACCESS_KEY) || ''
  },
  set access(v: string) {
    v ? localStorage.setItem(ACCESS_KEY, v) : localStorage.removeItem(ACCESS_KEY)
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY) || ''
  },
  set refresh(v: string) {
    v ? localStorage.setItem(REFRESH_KEY, v) : localStorage.removeItem(REFRESH_KEY)
  },
  clear() {
    this.access = ''
    this.refresh = ''
  },
}

declare module 'axios' {
  interface AxiosRequestConfig {
    /** 为 true 时不弹全局错误提示，由调用方自行处理（例如登录失败需静默降级重试） */
    _silent?: boolean
    /** 令牌刷新重试标记 */
    _retry?: boolean
  }
}

const http: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

// 请求拦截：自动携带令牌
http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokenStore.access
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：统一错误提示 + 令牌过期自动刷新
let refreshing = false
let waiting: Array<(token: string) => void> = []

async function refreshToken(): Promise<string> {
  const { data } = await axios.post<{ access_token: string; refresh_token: string }>(
    '/api/v1/auth/refresh',
    { refresh_token: tokenStore.refresh },
  )
  tokenStore.access = data.access_token
  tokenStore.refresh = data.refresh_token
  return data.access_token
}

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<{ message?: string; code?: string }>) => {
    const status = error.response?.status
    const original = error.config as InternalAxiosRequestConfig
    const requestUrl = original?.url || ''

    // 登录与刷新接口本身不参与重试，避免死循环（含统一身份认证登录）
    const isAuthEndpoint =
      requestUrl.includes('/auth/login') ||
      requestUrl.includes('/auth/sso/login') ||
      requestUrl.includes('/auth/refresh')

    if (status === 401 && !isAuthEndpoint && original) {
      if (!tokenStore.refresh) {
        tokenStore.clear()
        router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
        return Promise.reject(error)
      }
      if (!original._retry) {
        original._retry = true
        if (!refreshing) {
          refreshing = true
          try {
            const token = await refreshToken()
            waiting.forEach((cb) => cb(token))
            waiting = []
            original.headers.Authorization = `Bearer ${token}`
            return http(original)
          } catch {
            tokenStore.clear()
            router.push({ name: 'login' })
            return Promise.reject(error)
          } finally {
            refreshing = false
          }
        }
        // 刷新进行中，排队等待
        return new Promise((resolve) => {
          waiting.push((token: string) => {
            original.headers.Authorization = `Bearer ${token}`
            resolve(http(original))
          })
        })
      }
    }

    const message =
      error.response?.data?.message ||
      (status === 403 ? '没有权限执行该操作' : '请求失败，请稍后重试')
    const silent = original?._silent === true
    if (!silent && (status !== 401 || isAuthEndpoint)) {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

export default http

/** 统一的 GET 便捷方法 */
export function get<T>(url: string, params?: Record<string, unknown>) {
  return http.get<T>(url, { params }).then((r) => r.data)
}

/** 统一的 POST 便捷方法 */
export function post<T>(url: string, data?: unknown, config?: { _silent?: boolean }) {
  return http.post<T>(url, data, config).then((r) => r.data)
}

/** 下载二进制文件（导出接口用），服务端返回 JSON 时转为可读异常 */
export async function downloadFile(
  url: string,
  params: Record<string, unknown>,
  filename: string,
) {
  const { data } = await http.get(url, { params, responseType: 'blob' })
  const blob = data as unknown as Blob
  if (blob.type && blob.type.includes('json')) {
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
}
