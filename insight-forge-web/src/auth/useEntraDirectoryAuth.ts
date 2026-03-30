import { useCallback } from 'react'

import { useIsAuthenticated, useMsal } from '@azure/msal-react'

import { loginPopupSingleFlight } from '@/auth/msalInteractiveLogin'

export function useEntraDirectoryAuth() {
  const { instance } = useMsal()
  const isAuthenticated = useIsAuthenticated()
  const scope = import.meta.env.VITE_ENTRA_API_SCOPE?.trim() ?? ''

  const login = useCallback(() => {
    if (!scope) return
    void loginPopupSingleFlight(instance, { scopes: [scope] })
  }, [instance, scope])

  const logout = () => {
    void instance.logoutPopup({ mainWindowRedirectUri: window.location.origin })
  }

  return { isAuthenticated, login, logout, scopeReady: Boolean(scope) }
}
