import { MsalProvider } from '@azure/msal-react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from '@/App.tsx'
import { createMsalInstance } from '@/auth/msalInstance'
import '@/index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

async function bootstrap() {
  const msal = createMsalInstance()
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
        <BrowserRouter>
          {msal ? (
            <MsalProvider instance={msal}>
              <App />
            </MsalProvider>
          ) : (
            <App />
          )}
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>
  )

  createRoot(document.getElementById('root')!).render(shell)
}

void bootstrap()
