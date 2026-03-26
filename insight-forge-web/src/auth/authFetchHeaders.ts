import { getApiAccessToken } from '@/auth/getApiAccessToken'

/** Merge these into fetch() headers for API calls that bypass axios. */
export async function getAuthorizationHeaders(): Promise<Record<string, string>> {
  const token = await getApiAccessToken()
  if (token) return { Authorization: `Bearer ${token}` }
  return {}
}
