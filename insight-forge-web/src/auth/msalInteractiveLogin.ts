import type { IPublicClientApplication, PopupRequest, RedirectRequest } from '@azure/msal-browser'

let loginPopupInFlight: Promise<void> | null = null
let redirectLoginIssued = false

/**
 * Runs at most one MSAL login popup at a time. Concurrent callers share the same promise.
 * Prevents BrowserAuthError: interaction_in_progress / timed_out from overlapping popups.
 */
export function loginPopupSingleFlight(
  app: IPublicClientApplication,
  request: PopupRequest,
): Promise<void> {
  if (redirectLoginIssued) return Promise.resolve()
  if (loginPopupInFlight) return loginPopupInFlight

  loginPopupInFlight = (async () => {
    try {
      await app.loginPopup(request)
    } finally {
      loginPopupInFlight = null
    }
  })()

  return loginPopupInFlight
}

/**
 * Runs at most one MSAL login redirect. No-op if a popup login is in progress or redirect was already started.
 */
export function loginRedirectSingleFlight(
  app: IPublicClientApplication,
  request: RedirectRequest,
): void {
  if (loginPopupInFlight || redirectLoginIssued) return

  redirectLoginIssued = true
  try {
    void app.loginRedirect(request).catch(() => {
      redirectLoginIssued = false
    })
  } catch (e) {
    redirectLoginIssued = false
    throw e
  }
}
