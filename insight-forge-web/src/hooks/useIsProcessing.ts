import { useAppStore } from '@/store/appStore'

export function useIsProcessing(): boolean {
  return useAppStore((s) => s.processingMessage != null)
}
