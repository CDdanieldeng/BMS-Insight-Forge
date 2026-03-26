import { isEntraAuthEnabled } from '@/auth/entraEnv'
import { getBackendUrl } from '@/utils/env'

/**
 * Whether the API enforces Entra JWTs — mirrors backend `AUTH_ENABLED`.
 * Prefers `GET /health` when the server includes `auth_enabled`; otherwise falls back to
 * `VITE_ENTRA_AUTH_ENABLED` (older deployments without the field).
 */
export async function fetchBackendAuthEnabled(): Promise<boolean> {
  try {
    const res = await fetch(`${getBackendUrl()}/health`)
    if (!res.ok) return isEntraAuthEnabled()
    const data = (await res.json()) as { auth_enabled?: boolean }
    if (typeof data.auth_enabled === 'boolean') return data.auth_enabled
  } catch {
    /* ignore */
  }
  return isEntraAuthEnabled()
}
