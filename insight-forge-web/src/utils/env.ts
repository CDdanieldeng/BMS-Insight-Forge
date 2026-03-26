export function getBackendUrl(): string {
  const u = import.meta.env.VITE_BACKEND_URL
  return (typeof u === 'string' && u.length > 0 ? u : 'http://localhost:8001').replace(/\/$/, '')
}

/** Fetched into memory on start — same deck bytes used for slide-info + fill pipeline */
export function getTemplateFetchUrl(): string {
  const u = import.meta.env.VITE_TEMPLATE_FETCH_URL
  return typeof u === 'string' && u.length > 0 ? u : '/template.pptx'
}

export function getVoiceLanguage(): string {
  const u = import.meta.env.VITE_VOICE_INPUT_LANGUAGE
  return typeof u === 'string' && u.length > 0 ? u : 'zh'
}
