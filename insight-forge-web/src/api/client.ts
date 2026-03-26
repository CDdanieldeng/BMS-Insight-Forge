import axios from 'axios'

import { getBackendUrl } from '@/utils/env'

export const api = axios.create({
  baseURL: getBackendUrl(),
  timeout: 240_000,
})

export function setApiBaseUrl(url: string): void {
  api.defaults.baseURL = url.replace(/\/$/, '')
}
