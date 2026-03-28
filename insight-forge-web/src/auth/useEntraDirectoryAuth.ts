import { useIsAuthenticated, useMsal } from '@azure/msal-react'

export function useEntraDirectoryAuth() {
  const { instance } = useMsal()
  const isAuthenticated = useIsAuthenticated()
  const scope = import.meta.env.VITE_ENTRA_API_SCOPE?.trim() ?? ''

  const login = () => {
    if (!scope) return
    void instance.loginPopup({ scopes: [scope] })
  }

  const logout = () => {
    void instance.logoutPopup({ mainWindowRedirectUri: window.location.origin })
  }

  return { isAuthenticated, login, logout, scopeReady: Boolean(scope) }
}
