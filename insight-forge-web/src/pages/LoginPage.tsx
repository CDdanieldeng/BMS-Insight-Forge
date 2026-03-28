import { Navigate } from 'react-router-dom'

import { useBackendAuthEnabled } from '@/auth/BackendAuthContext'
import {
  EntraMisconfiguredWall,
  EntraSignInWall,
} from '@/auth/EntraAuthGate'
import { isEntraAuthConfigured, isEntraSignInRequired } from '@/auth/entraEnv'
import { useEntraDirectoryAuth } from '@/auth/useEntraDirectoryAuth'

function LoginPageInner() {
  const { isAuthenticated, login, scopeReady } = useEntraDirectoryAuth()
  if (!scopeReady) {
    return (
      <p className="mx-auto max-w-md px-4 py-16 text-center text-sm text-neutral-500">Loading…</p>
    )
  }
  if (isAuthenticated) return <Navigate to="/" replace />
  return <EntraSignInWall onSignIn={login} />
}

/**
 * Dedicated sign-in route when Entra is mandatory. With auth flags off, `/login` redirects
 * home so local development goes straight to the app.
 */
export function LoginPage() {
  const apiAuth = useBackendAuthEnabled()
  if (!isEntraSignInRequired(apiAuth)) return <Navigate to="/" replace />
  if (!isEntraAuthConfigured()) return <EntraMisconfiguredWall />
  return <LoginPageInner />
}
