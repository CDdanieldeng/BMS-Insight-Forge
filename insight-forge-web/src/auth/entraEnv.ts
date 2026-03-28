function truthy(v: unknown): boolean {
  return v === 'true' || v === '1' || v === 'yes'
}

/** When true, MSAL loads and API calls attach a Bearer token when the user has signed in. */
export function isEntraAuthEnabled(): boolean {
  return truthy(import.meta.env.VITE_ENTRA_AUTH_ENABLED)
}

/** Both API (`AUTH_ENABLED`) and SPA opt in — session is required before the main app routes. */
export function isEntraSignInRequired(apiAuthEnabled: boolean): boolean {
  return apiAuthEnabled && isEntraAuthEnabled()
}

export function getEntraAuthEnv(): { clientId: string; tenantId: string } {
  return {
    clientId: (import.meta.env.VITE_ENTRA_CLIENT_ID ?? '').trim(),
    tenantId: (import.meta.env.VITE_ENTRA_TENANT_ID ?? '').trim(),
  }
}

/** True when MSAL should load: flag on plus client, tenant, and API scope. */
export function isEntraAuthConfigured(): boolean {
  if (!isEntraAuthEnabled()) return false
  const { clientId, tenantId } = getEntraAuthEnv()
  const scope = import.meta.env.VITE_ENTRA_API_SCOPE?.trim()
  return Boolean(clientId && tenantId && scope)
}
