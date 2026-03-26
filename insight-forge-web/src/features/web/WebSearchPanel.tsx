import { useEffect, useState } from 'react'

import type { WebSearchResult } from '@/types'

export function WebSearchPanel({
  query,
  results,
  onSearch,
  onClear,
  disabled,
}: {
  query: string
  results: WebSearchResult[]
  onSearch: (q: string) => void
  onClear: () => void
  disabled: boolean
}) {
  const [localQ, setLocalQ] = useState(query)
  useEffect(() => {
    setLocalQ(query)
  }, [query])

  return (
    <section className="mt-6 rounded-2xl border border-neutral-200/70 bg-white/50 p-4 shadow-sm">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
        Web
      </h3>
      <div className="mt-2 flex gap-2">
        <input
          value={localQ}
          onChange={(e) => setLocalQ(e.target.value)}
          disabled={disabled}
          placeholder="Search for context…"
          autoComplete="off"
          className="min-w-0 flex-1 rounded-xl border border-neutral-200 bg-white px-3 py-2 text-xs text-neutral-800 placeholder:text-neutral-400 focus:border-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-200"
        />
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            const q = localQ.trim()
            if (q) onSearch(q)
          }}
          className="shrink-0 rounded-xl bg-neutral-900 px-4 py-2 text-xs font-medium text-white shadow-sm hover:bg-neutral-800 disabled:opacity-40"
        >
          Search
        </button>
      </div>

      {results.length > 0 ? (
        <div className="mt-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-[11px] text-neutral-500">
              Results for <span className="text-neutral-700">{query}</span>
            </p>
            <button
              type="button"
              disabled={disabled}
              onClick={onClear}
              className="text-[11px] text-neutral-400 hover:text-neutral-700"
            >
              Clear
            </button>
          </div>
          <ul className="space-y-2">
            {results.slice(0, 5).map((r, i) => (
              <li key={i}>
                <details className="group rounded-lg border border-neutral-200/80 bg-white">
                  <summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-neutral-800 marker:content-none [&::-webkit-details-marker]:hidden">
                    <span className="mr-1 text-neutral-300 group-open:rotate-90">▸</span>
                    {r.title || `Result ${i + 1}`}
                  </summary>
                  <div className="border-t border-neutral-100 px-3 py-2">
                    {r.url ? (
                      <a
                        href={r.url}
                        target="_blank"
                        rel="noreferrer"
                        className="mb-1 block break-all text-[11px] text-neutral-500 underline-offset-2 hover:underline"
                      >
                        {r.url}
                      </a>
                    ) : null}
                    <p className="whitespace-pre-wrap break-words text-[11px] leading-relaxed text-neutral-600">
                      {r.content}
                    </p>
                  </div>
                </details>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  )
}
