import type { ReactNode } from 'react'

import { useBackendAuthEnabled } from '@/auth/BackendAuthContext'
import { isEntraAuthConfigured } from '@/auth/entraEnv'
import { useEntraDirectoryAuth } from '@/auth/useEntraDirectoryAuth'
import { ZS_LOGO_SRC } from '@/utils/constants'

function EntraSignInWall({ onSignIn }: { onSignIn: () => void }) {
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

function EntraAuthGateInner({ children }: { children: ReactNode }) {
  const { isAuthenticated, login, scopeReady } = useEntraDirectoryAuth()
  if (!scopeReady) return children
  if (!isAuthenticated) return <EntraSignInWall onSignIn={login} />
  return children
}

/**
 * When the API has `AUTH_ENABLED` and Entra is configured in the SPA, blocks the app until
 * the user signs in.
 */
export function EntraAuthGate({ children }: { children: ReactNode }) {
  const apiAuth = useBackendAuthEnabled()
  if (!apiAuth || !isEntraAuthConfigured()) return children
  return <EntraAuthGateInner>{children}</EntraAuthGateInner>
}
