import axios from 'axios'

import { getApiAccessToken } from '@/auth/getApiAccessToken'
import { getBackendUrl } from '@/utils/env'

export const api = axios.create({
  baseURL: getBackendUrl(),
  timeout: 240_000,
})

api.interceptors.request.use(async (config) => {
  try {
    const token = await getApiAccessToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  } catch {
    /* interactive login may be required first */
  }
  return config
})

export function setApiBaseUrl(url: string): void {
  api.defaults.baseURL = url.replace(/\/$/, '')
}
