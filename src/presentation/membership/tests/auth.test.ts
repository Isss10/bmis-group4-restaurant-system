import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuth } from '../src/auth'

const user = { id: 1, email: 'customer@example.com', display_name: '顾客', role: 'customer', is_active: true, version: 1 }
const session = { access_token: 'memory-only-token', token_type: 'bearer', expires_in: 3600, csrf_token: 'csrf-value', user }
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })

beforeEach(() => { setActivePinia(createPinia()); vi.unstubAllGlobals() })

describe('session lifecycle', () => {
  it('restores from the HttpOnly cookie and coalesces parallel 401 refresh attempts', async () => {
    let refreshes = 0
    const fetcher = vi.fn(async (path: string, options: RequestInit) => {
      if (path.endsWith('/auth/csrf')) return json({ csrf_token: 'csrf-value' })
      if (path.endsWith('/auth/refresh')) {
        refreshes++
        await new Promise((resolve) => setTimeout(resolve, 5))
        return json({ ...session, access_token: `refreshed-${refreshes}` })
      }
      const authorization = new Headers(options.headers).get('Authorization')
      return authorization === 'Bearer refreshed-2' ? json(user) : json({ error: { message: 'Expired' } }, 401)
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
      if (path.endsWith('/auth/login')) return json(session)
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
    const fetcher = vi.fn(async () => json({ error: { message: 'Not authenticated' } }, 401))
    vi.stubGlobal('fetch', fetcher)
    const auth = useAuth()
    await auth.restore()
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(auth.restoring).toBe(false)
    expect(auth.authenticated).toBe(false)
  })
})
