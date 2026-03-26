import { MsalProvider } from '@azure/msal-react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from '@/App.tsx'
import { BackendAuthEnabledProvider } from '@/auth/BackendAuthContext'
import { fetchBackendAuthEnabled } from '@/auth/backendAuthFromApi'
import { createMsalInstance } from '@/auth/msalInstance'
import '@/index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

async function bootstrap() {
  const apiAuthEnabled = await fetchBackendAuthEnabled()
  const msal = createMsalInstance(apiAuthEnabled)
  if (msal) {
    await msal.initialize()
    const accounts = msal.getAllAccounts()
    if (accounts[0]) {
      msal.setActiveAccount(accounts[0])
    }
  }

  const shell = (
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BackendAuthEnabledProvider value={apiAuthEnabled}>
          <BrowserRouter>
            {msal ? (
              <MsalProvider instance={msal}>
                <App />
              </MsalProvider>
            ) : (
              <App />
            )}
          </BrowserRouter>
        </BackendAuthEnabledProvider>
      </QueryClientProvider>
    </StrictMode>
  )

  createRoot(document.getElementById('root')!).render(shell)
}

void bootstrap()
