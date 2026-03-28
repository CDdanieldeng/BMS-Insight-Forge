import {
  EventType,
  PublicClientApplication,
  type AuthenticationResult,
  type Configuration,
  type EventMessage,
} from '@azure/msal-browser'

import { getEntraAuthEnv, isEntraAuthConfigured } from '@/auth/entraEnv'

let instance: PublicClientApplication | null = null

/**
 * Creates the singleton MSAL instance when the API requires auth (`AUTH_ENABLED`), Entra is
 * enabled in Vite env, and client/tenant/scope are set.
 */
export function createMsalInstance(apiAuthEnabled: boolean): PublicClientApplication | null {
  if (!apiAuthEnabled || !isEntraAuthConfigured()) return null
  const { clientId, tenantId } = getEntraAuthEnv()
  if (!instance) {
    const config: Configuration = {
      auth: {
        clientId,
        authority: `https://login.microsoftonline.com/${tenantId}`,
        redirectUri: typeof window !== 'undefined' ? window.location.origin : undefined,
      },
      cache: {
        cacheLocation: 'sessionStorage',
      },
    }
    const app = new PublicClientApplication(config)
    app.addEventCallback((event: EventMessage) => {
      if (event.eventType !== EventType.LOGIN_SUCCESS || !event.payload) return
      const result = event.payload as AuthenticationResult
      if (result.account) {
        app.setActiveAccount(result.account)
      }
    })
    instance = app
  }
  return instance
}

export function getMsalInstance(): PublicClientApplication | null {
  return instance
}
