import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { useIsAuthenticated, useMsal } from '@azure/msal-react'

let loginInFlight: Promise<void> | null = null

export function useEntraDirectoryAuth() {
  const { instance } = useMsal()
  const isAuthenticated = useIsAuthenticated()
  const scope = import.meta.env.VITE_ENTRA_API_SCOPE?.trim() ?? ''

  const login = () => {
    if (!scope) return
    if (loginInFlight) {
      void loginInFlight
      return
    }

    const attempt = async () => {
      const existing = instance.getActiveAccount() ?? instance.getAllAccounts()[0]
      if (existing) {
        instance.setActiveAccount(existing)
        try {
          const silent = await instance.acquireTokenSilent({
            account: existing,
            scopes: [scope],
          })
          if (silent.account) instance.setActiveAccount(silent.account)
          return
        } catch (e) {
          if (!(e instanceof InteractionRequiredAuthError)) throw e
        }
      } else {
        try {
          const silent = await instance.ssoSilent({ scopes: [scope] })
          if (silent.account) instance.setActiveAccount(silent.account)
          return
        } catch {
          /* No usable Entra SSO session in the silent iframe — fall back to popup */
        }
      }

      await instance.loginPopup({ scopes: [scope] })
    }

    loginInFlight = attempt()
      .catch(() => {
        /* User dismissed popup or MSAL error — allow retry */
      })
      .finally(() => {
        loginInFlight = null
      })
    void loginInFlight
  }

  const logout = () => {
    void instance.logoutPopup({ mainWindowRedirectUri: window.location.origin })
  }

  return { isAuthenticated, login, logout, scopeReady: Boolean(scope) }
}
