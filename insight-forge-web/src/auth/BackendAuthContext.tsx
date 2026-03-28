import { createContext, useContext, type ReactNode } from 'react'

const BackendAuthEnabledContext = createContext<boolean>(false)

export function BackendAuthEnabledProvider({
  value,
  children,
}: {
  value: boolean
  children: ReactNode
}) {
  return (
    <BackendAuthEnabledContext.Provider value={value}>
      {children}
    </BackendAuthEnabledContext.Provider>
  )
}

export function useBackendAuthEnabled(): boolean {
  return useContext(BackendAuthEnabledContext)
}
