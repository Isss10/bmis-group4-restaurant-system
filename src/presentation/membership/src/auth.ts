import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type Role = 'customer' | 'waiter' | 'manager' | 'admin'
export interface User {
  id: number
  email: string
  display_name: string
  role: Role
  is_active: boolean
  version: number
}
interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  csrf_token: string
  user: User
}
export interface UserPage { items: User[]; total: number; page: number; page_size: number }
export const roleNames: Record<Role, string> = {
  customer: '顾客', waiter: '服务员', manager: '经理', admin: '管理员',
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public requestId?: string) {
    super(message)
  }
}

async function responseData<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const fallback = response.status === 422
      ? '请检查邮箱、密码长度及表单内容。'
      : response.status === 429 ? '操作过于频繁，请稍后再试。' : '请求失败，请稍后重试。'
    throw new ApiError(response.status, body?.error?.message || fallback, body?.error?.request_id)
  }
  return body as T
}

function send(path: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type', 'application/json')
  return fetch(`/api/v1${path}`, { ...options, headers, credentials: 'include' })
}

export const useAuth = defineStore('membership-auth', () => {
  // Tokens stay in this closure. They are never persisted or returned to templates.
  let accessToken = ''
  let csrfToken = ''
  let refreshPromise: Promise<void> | undefined
  const user = ref<User | null>(null)
  const restoring = ref(true)
  const authenticated = computed(() => user.value !== null)

  function clear(): void {
    accessToken = ''
    csrfToken = ''
    user.value = null
  }

  function accept(session: LoginResponse): void {
    accessToken = session.access_token
    csrfToken = session.csrf_token
    user.value = session.user
  }

  async function refresh(): Promise<void> {
    if (refreshPromise) return refreshPromise
    refreshPromise = (async () => {
      try {
        if (!csrfToken) {
          const csrf = await responseData<{ csrf_token: string }>(await send('/auth/csrf'))
          csrfToken = csrf.csrf_token
        }
        const session = await responseData<LoginResponse>(await send('/auth/refresh', {
          method: 'POST', headers: { 'X-CSRF-Token': csrfToken },
        }))
        accept(session)
      } catch (error) {
        clear()
        throw error
      } finally {
        refreshPromise = undefined
      }
    })()
    return refreshPromise
  }

  async function restore(): Promise<void> {
    restoring.value = true
    try {
      await refresh()
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error
    } finally {
      restoring.value = false
    }
  }

  async function login(email: string, password: string): Promise<void> {
    accept(await responseData<LoginResponse>(await send('/auth/login', {
      method: 'POST', body: JSON.stringify({ email, password }),
    })))
  }

  async function register(email: string, password: string, displayName: string): Promise<void> {
    await responseData<User>(await send('/auth/register', {
      method: 'POST', body: JSON.stringify({ email, password, display_name: displayName }),
    }))
  }

  async function logout(): Promise<void> {
    try {
      // Wait for an in-flight rotation before revoking the resulting session.
      if (refreshPromise) await refreshPromise
      await responseData<unknown>(await send('/auth/logout', {
        method: 'POST', headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {},
      }))
    } finally {
      clear()
    }
  }

  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const before = accessToken
    const run = (): Promise<Response> => {
      const headers = new Headers(options.headers)
      headers.set('Authorization', `Bearer ${accessToken}`)
      return send(path, { ...options, headers })
    }
    let response = await run()
    if (response.status === 401) {
      // Other callers may already have refreshed this token while our request ran.
      if (accessToken === before) await refresh()
      response = await run()
    }
    if (response.status === 401) clear()
    return responseData<T>(response)
  }

  return { user, restoring, authenticated, restore, login, register, logout, request }
})
