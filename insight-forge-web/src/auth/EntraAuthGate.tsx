import { Navigate, Outlet } from 'react-router-dom'

import { useBackendAuthEnabled } from '@/auth/BackendAuthContext'
import { isEntraAuthConfigured, isEntraSignInRequired } from '@/auth/entraEnv'
import { useEntraDirectoryAuth } from '@/auth/useEntraDirectoryAuth'
import { ZS_LOGO_SRC } from '@/utils/constants'

export function EntraSignInWall({ onSignIn }: { onSignIn: () => void }) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center px-4 py-16 md:py-24">
      <img src={ZS_LOGO_SRC} alt="" className="h-10 w-auto md:h-12" aria-hidden />
      <p className="mt-8 text-[11px] font-medium uppercase tracking-[0.2em] text-neutral-400">
        Internal
      </p>
      <h1 className="mt-4 text-center text-2xl font-semibold tracking-tight text-neutral-900 md:text-3xl">
        Sign in to continue
      </h1>
      <p className="mt-4 text-center text-sm leading-relaxed text-neutral-500">
        Use your ZS Microsoft account to access BP Coach. Your session is required before the
        workspace loads.
      </p>
      <div className="mt-10 flex w-full flex-col items-center gap-2">
        <p className="text-center text-[11px] uppercase tracking-wider text-neutral-400">
          Directory sign-in
        </p>
        <button
          type="button"
          onClick={onSignIn}
          className="rounded-xl border border-neutral-900 bg-neutral-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-neutral-800"
        >
          Sign in with Microsoft
        </button>
      </div>
    </div>
  )
}

export function EntraMisconfiguredWall() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center px-4 py-16 md:py-24">
      <img src={ZS_LOGO_SRC} alt="" className="h-10 w-auto md:h-12" aria-hidden />
      <h1 className="mt-8 text-center text-xl font-semibold text-neutral-900">
        Sign-in is not available
      </h1>
      <p className="mt-4 text-center text-sm leading-relaxed text-neutral-500">
        The API expects Entra auth, but this build is missing{' '}
        <span className="font-medium text-neutral-700">VITE_ENTRA_CLIENT_ID</span>,{' '}
        <span className="font-medium text-neutral-700">VITE_ENTRA_TENANT_ID</span>, or{' '}
        <span className="font-medium text-neutral-700">VITE_ENTRA_API_SCOPE</span>.
      </p>
    </div>
  )
}

function EntraProtectedLayoutInner() {
  const { isAuthenticated, scopeReady } = useEntraDirectoryAuth()
  if (!scopeReady) return <Outlet />
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <Outlet />
}

/**
 * When both `AUTH_ENABLED` (API) and `VITE_ENTRA_AUTH_ENABLED` are on, and Entra env is
 * complete, unauthenticated users are sent to `/login` instead of seeing the homepage.
 */
export function EntraProtectedLayout() {
  const apiAuth = useBackendAuthEnabled()
  if (!isEntraSignInRequired(apiAuth)) return <Outlet />
  if (!isEntraAuthConfigured()) return <EntraMisconfiguredWall />
  return <EntraProtectedLayoutInner />
}
