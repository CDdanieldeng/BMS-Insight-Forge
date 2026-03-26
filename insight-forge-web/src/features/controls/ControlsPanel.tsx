import { useRef } from 'react'

export function ControlsPanel({
  fileCount,
  onIngest,
  onFill,
  fillDisabledReason,
  disabled,
}: {
  fileCount: number
  onIngest: (files: File[]) => void
  onFill: () => void
  fillDisabledReason?: string
  disabled: boolean
}) {
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <section className="mt-6 space-y-4 rounded-2xl border border-neutral-200/70 bg-white/60 p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Module files
        </h3>
        <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] text-neutral-500">
          {fileCount} ingested
        </span>
      </div>
      <p className="text-[11px] leading-relaxed text-neutral-500">
        Upload replaces this module’s retrieval set. Supported: PPTX, DOCX, DOC, MD, PDF.
      </p>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".pptx,.docx,.doc,.md,.pdf"
        className="hidden"
        disabled={disabled}
        onChange={(e) => {
          const fs = [...(e.target.files ?? [])]
          if (fs.length) onIngest(fs)
          e.target.value = ''
        }}
      />
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
          className="rounded-xl border border-neutral-200 bg-white px-4 py-2 text-xs font-medium text-neutral-800 shadow-sm hover:bg-neutral-50"
        >
          Choose files
        </button>
      </div>
      <div className="border-t border-neutral-100 pt-4">
        <button
          type="button"
          disabled={disabled}
          onClick={onFill}
          className="w-full rounded-xl bg-neutral-900 py-2.5 text-xs font-medium text-white shadow-sm hover:bg-neutral-800 disabled:opacity-40"
        >
          Fill slide
        </button>
        {fillDisabledReason ? (
          <p className="mt-2 text-[11px] text-neutral-400">{fillDisabledReason}</p>
        ) : null}
      </div>
    </section>
  )
}
