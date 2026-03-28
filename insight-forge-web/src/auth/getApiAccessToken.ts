import { InteractionRequiredAuthError } from '@azure/msal-browser'

import { getMsalInstance } from '@/auth/msalInstance'

/** Access token for the configured API scope, or null if MSAL is off, user is logged out, or consent is required. */
export async function getApiAccessToken(): Promise<string | null> {
  const msal = getMsalInstance()
  if (!msal) return null

  const scope = import.meta.env.VITE_ENTRA_API_SCOPE?.trim()
  if (!scope) return null

  const account = msal.getActiveAccount() ?? msal.getAllAccounts()[0]
  if (!account) return null

  try {
    const result = await msal.acquireTokenSilent({ account, scopes: [scope] })
    return result.accessToken
  } catch (e) {
    if (e instanceof InteractionRequiredAuthError) return null
    throw e
  }
}
