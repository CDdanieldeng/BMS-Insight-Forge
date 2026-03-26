import type { ReactNode } from 'react'

import { AppTopBar } from '@/components/AppTopBar'
import { ProcessingOverlay } from '@/components/ProcessingOverlay'

export function AppShell({
  children,
  banner,
}: {
  children: ReactNode
  banner?: ReactNode
}) {
  return (
    <div className="min-h-screen">
      {banner}
      <AppTopBar />
      <main className="mx-auto max-w-[1600px] px-6 py-8 md:px-10 md:py-10">{children}</main>
      <ProcessingOverlay />
    </div>
  )
}
