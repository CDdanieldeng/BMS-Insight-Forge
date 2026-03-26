import { useAppStore } from '@/store/appStore'

export function ProcessingOverlay() {
  const message = useAppStore((s) => s.processingMessage)
  if (!message) return null

  return (
    <div
      className="fixed inset-0 z-[100] flex cursor-not-allowed items-center justify-center bg-white/80 backdrop-blur-[2px]"
      role="alert"
      aria-live="polite"
    >
      <div className="max-w-sm rounded-2xl border border-neutral-200/80 bg-white px-10 py-8 text-center shadow-[0_8px_40px_-12px_rgba(0,0,0,0.18)]">
        <div className="mb-3 flex justify-center gap-1.5">
          <span className="if-pulse-dot size-1.5 rounded-full bg-neutral-400" />
          <span
            className="if-pulse-dot size-1.5 rounded-full bg-neutral-400"
            style={{ animationDelay: '0.15s' }}
          />
          <span
            className="if-pulse-dot size-1.5 rounded-full bg-neutral-400"
            style={{ animationDelay: '0.3s' }}
          />
        </div>
        <p className="text-sm font-medium tracking-tight text-neutral-900">{message}</p>
        <p className="mt-2 text-xs text-neutral-500">Please wait — avoid navigating away.</p>
      </div>
    </div>
  )
}
