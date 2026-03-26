/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BACKEND_URL?: string
  readonly VITE_TEMPLATE_FETCH_URL?: string
  readonly VITE_VOICE_INPUT_LANGUAGE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
