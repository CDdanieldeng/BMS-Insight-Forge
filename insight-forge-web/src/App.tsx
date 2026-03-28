import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { EntraProtectedLayout } from '@/auth/EntraAuthGate'
import { AppShell } from '@/components/AppShell'
import { LoginPage } from '@/pages/LoginPage'
import { ModuleWorkspace } from '@/pages/ModuleWorkspace'
import { WelcomePage } from '@/pages/WelcomePage'
import { useAppStore } from '@/store/appStore'

function WorkspaceGate({ children }: { children: ReactNode }) {
  const started = useAppStore((s) => s.started)
  if (!started) return <Navigate to="/" replace />
  return children
}

function WelcomeRoute() {
  const started = useAppStore((s) => s.started)
  if (started) return <Navigate to="/workspace" replace />
  return <WelcomePage />
}

function ErrorBanner() {
  const err = useAppStore((s) => s.bannerError)
  const setErr = useAppStore((s) => s.setBannerError)
  if (!err) return null
  return (
    <div className="border-b border-red-200/80 bg-red-50/90 px-6 py-3 text-center text-xs text-red-900">
      <span>{err}</span>
      <button
        type="button"
        className="ml-3 underline decoration-red-300 decoration-1 underline-offset-2 hover:text-red-950"
        onClick={() => setErr(null)}
      >
        Dismiss
      </button>
    </div>
  )
}

export default function App() {
  return (
    <AppShell banner={<ErrorBanner />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<EntraProtectedLayout />}>
          <Route path="/" element={<WelcomeRoute />} />
          <Route
            path="/workspace"
            element={
              <WorkspaceGate>
                <ModuleWorkspace />
              </WorkspaceGate>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </AppShell>
  )
}
