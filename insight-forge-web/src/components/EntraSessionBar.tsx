import { useIsAuthenticated, useMsal } from '@azure/msal-react'

import { isEntraAuthConfigured } from '@/auth/entraEnv'

export function EntraSessionBar() {
  if (!isEntraAuthConfigured()) return null
  return <EntraSessionBarInner />
}

function EntraSessionBarInner() {
  const { instance } = useMsal()
  const isAuthenticated = useIsAuthenticated()
  const scope = import.meta.env.VITE_ENTRA_API_SCOPE?.trim() ?? ''

  if (!scope) return null

  const login = () => {
    void instance.loginPopup({ scopes: [scope] })
  }

  const logout = () => {
    void instance.logoutPopup({ mainWindowRedirectUri: window.location.origin })
  }

  return (
    <div className="mt-12 flex w-full max-w-sm flex-col items-center gap-2 border-t border-neutral-200/80 pt-8">
      <p className="text-center text-[11px] uppercase tracking-wider text-neutral-400">
        Directory sign-in
      </p>
      {isAuthenticated ? (
        <button
          type="button"
          onClick={logout}
          className="rounded-xl border border-neutral-200 bg-white px-4 py-2 text-xs font-medium text-neutral-700 hover:bg-neutral-50"
        >
          Sign out
        </button>
      ) : (
        <button
          type="button"
          onClick={login}
          className="rounded-xl border border-neutral-900 bg-neutral-900 px-4 py-2 text-xs font-medium text-white hover:bg-neutral-800"
        >
          Sign in with Microsoft
        </button>
      )}
    </div>
  )
}
