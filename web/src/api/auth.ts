import { get, post, tokenStore } from './http'

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
  auth_source: string
  is_sso: boolean
}

/** 登录页用于判断是否展示统一身份认证入口（不含任何密钥） */
export interface SsoConfig {
  enabled: boolean
  default: boolean
  label: string
  provider: string | null
  auth_source: string | null
  choices: { id: string; label: string; source: string; supported: boolean; reason?: string }[]
  detail?: Record<string, unknown>
}

export interface LoginPayload {
  username: string
  password: string
}

export interface TokenResult {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  must_change_password: boolean
}

export const authApi = {
  /**
   * 本地口令登录。
   * `silent = true` 时不弹全局错误提示 —— 登录页据此静默捕获 `sso_required`，
   * 自动改走统一身份认证，避免用户看到"该账号已接入…"的误导性报错。
   */
  login(payload: LoginPayload, silent = false) {
    return post<TokenResult>('/auth/login', payload, { _silent: silent })
  },
  /** 统一身份认证登录：账号密码由后端代理提交给 IdP 校验 */
  ssoLogin(payload: LoginPayload) {
    return post<TokenResult>('/auth/sso/login', payload)
  },
  ssoConfig() {
    return get<SsoConfig>('/auth/sso/config')
  },
  me() {
    return get<CurrentUser>('/auth/me')
  },
  logout() {
    return post<{ message: string }>('/auth/logout')
  },
  changePassword(oldPassword: string, newPassword: string) {
    return post<{ message: string }>('/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  },
  passwordPolicy() {
    return get<{ min_length: number; require_classes: number; description: string }>(
      '/auth/password-policy',
    )
  },
  clearToken() {
    tokenStore.clear()
  },
  saveToken(data: TokenResult) {
    tokenStore.access = data.access_token
    tokenStore.refresh = data.refresh_token
  },
}

export interface LoginHistoryItem {
  id: number
  action: string
  ip_address: string | null
  created_at: string
}
