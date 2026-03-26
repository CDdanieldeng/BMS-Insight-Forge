/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BACKEND_URL?: string
  readonly VITE_TEMPLATE_FETCH_URL?: string
  readonly VITE_VOICE_INPUT_LANGUAGE?: string
  /** `true` enables MSAL and sends Bearer tokens to the API when signed in */
  readonly VITE_ENTRA_AUTH_ENABLED?: string
  readonly VITE_ENTRA_CLIENT_ID?: string
  readonly VITE_ENTRA_TENANT_ID?: string
  /** e.g. api://<api-app-id>/access_as_user */
  readonly VITE_ENTRA_API_SCOPE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
