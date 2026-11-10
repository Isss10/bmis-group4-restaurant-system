import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ApiError, useAuth, type User, type UserPage } from '../src/auth'

const user: User = { id: 1, email: 'customer@example.com', display_name: '顾客', role: 'customer', is_active: true, version: 1 }
const session = { access_token: 'memory-only-token', token_type: 'bearer', expires_in: 3600, csrf_token: 'csrf-value', user }
const envelope = (data: unknown, code = 0, message = 'ok') => ({
  code, message, data, request_id: 'req_membership_test', timestamp: '2026-11-08T04:30:00Z',
})
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
const ok = (data: unknown, status = 200) => json(envelope(data), status)
const failure = (status: number, code: number, message: string) => json(envelope(null, code, message), status)

beforeEach(() => { setActivePinia(createPinia()); vi.unstubAllGlobals() })

describe('session lifecycle', () => {
  it('restores from the HttpOnly cookie and coalesces parallel 401 refresh attempts', async () => {
    let refreshes = 0
    const fetcher = vi.fn(async (path: string, options: RequestInit) => {
      if (path.endsWith('/auth/csrf')) return ok({ csrf_token: 'csrf-value' })
      if (path.endsWith('/auth/refresh')) {
        refreshes++
        await new Promise((resolve) => setTimeout(resolve, 5))
        return ok({ ...session, access_token: `refreshed-${refreshes}` })
      }
      const authorization = new Headers(options.headers).get('Authorization')
      return authorization === 'Bearer refreshed-2' ? ok(user) : failure(401, 30002, '认证凭据无效或已过期')
    })
    vi.stubGlobal('fetch', fetcher)
    const auth = useAuth()
    await auth.restore()
    await Promise.all([auth.request('/membership/profile'), auth.request('/membership/profile')])
    expect(refreshes).toBe(2)
    expect(auth.user?.display_name).toBe('顾客')
    for (const [path, options] of fetcher.mock.calls) {
      expect(options.credentials).toBe('include')
      if (path.endsWith('/auth/refresh')) expect(new Headers(options.headers).get('X-CSRF-Token')).toBe('csrf-value')
    }
    expect('accessToken' in auth).toBe(false)
  })

  it('clears identity after logout even when the network fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async (path: string) => {
      if (path.endsWith('/auth/login')) return ok(session)
      throw new TypeError('Network unavailable')
    }))
    const auth = useAuth()
    await auth.login('customer@example.com', 'a-test-password')
    expect(auth.authenticated).toBe(true)
    await expect(auth.logout()).rejects.toThrow('Network unavailable')
    expect(auth.authenticated).toBe(false)
    expect(auth.user).toBeNull()
  })

  it('does not loop indefinitely after an invalid refresh cookie', async () => {
    const fetcher = vi.fn(async () => failure(401, 30002, '认证凭据无效或已过期'))
    vi.stubGlobal('fetch', fetcher)
    const auth = useAuth()
    await auth.restore()
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(auth.restoring).toBe(false)
    expect(auth.authenticated).toBe(false)
  })
})

describe('unified API contract', () => {
  it('unwraps registration and paginated account data', async () => {
    const users: UserPage = { items: [user], total: 1, page: 1, page_size: 20, total_pages: 1 }
    const fetcher = vi.fn(async (path: string) => {
      if (path.endsWith('/auth/register')) return ok(user, 201)
      if (path.endsWith('/auth/login')) return ok(session)
      return ok(users)
    })
    vi.stubGlobal('fetch', fetcher)
    const auth = useAuth()
    await auth.register('customer@example.com', 'a-test-password', '顾客')
    await auth.login('customer@example.com', 'a-test-password')
    expect(auth.user?.id).toBe(1)
    expect(await auth.request<UserPage>('/users')).toEqual(users)
  })

  it('keeps the frozen error code, message and request id for the page', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => failure(409, 20004, '数据已被其他请求修改，请刷新后重试')))
    const auth = useAuth()
    await expect(auth.request('/users/1/role', { method: 'PATCH' })).rejects.toMatchObject({
      status: 409, code: 20004, message: '数据已被其他请求修改，请刷新后重试', requestId: 'req_membership_test',
    })
  })

  it('shows permission errors without attempting a token refresh', async () => {
    const fetcher = vi.fn(async () => failure(403, 30003, '权限不足'))
    vi.stubGlobal('fetch', fetcher)
    await expect(useAuth().request('/users')).rejects.toMatchObject({ code: 30003, message: '权限不足' })
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('rejects a business failure carried by an HTTP 200 response', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => failure(200, 30002, '认证凭据无效或已过期')))
    const auth = useAuth()
    await expect(auth.login('customer@example.com', 'a-test-password')).rejects.toBeInstanceOf(ApiError)
    expect(auth.authenticated).toBe(false)
  })

  it.each([
    session,
    { ...envelope(session), code: '0' },
    { code: 0, message: 'ok', request_id: null, timestamp: '2026-11-08T04:30:00Z' },
    { ...envelope(session), request_id: 12 },
  ])('rejects malformed or unwrapped successful responses', async (body) => {
    vi.stubGlobal('fetch', vi.fn(async () => json(body)))
    const auth = useAuth()
    await expect(auth.login('customer@example.com', 'a-test-password')).rejects.toMatchObject({
      message: '服务返回了无法识别的数据，请稍后重试。',
    })
    expect(auth.authenticated).toBe(false)
  })

  it('uses a readable fallback when a proxy returns non-JSON rate-limit output', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('Too many requests', { status: 429 })))
    await expect(useAuth().login('customer@example.com', 'a-test-password')).rejects.toMatchObject({
      status: 429, message: '操作过于频繁，请稍后再试。',
    })
  })
})
