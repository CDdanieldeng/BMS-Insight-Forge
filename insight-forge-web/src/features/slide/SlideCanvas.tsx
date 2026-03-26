import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import type { ModuleName, SlideMeta } from '@/types'
import {
  fetchSlideRenderPngValidated,
  type SlidePreviewSource,
} from '@/api/insightForgeApi'
import { buildNormalizedSlideTable } from '@/utils/slideTable'

import { SlideTable } from '@/features/slide/SlideTable'

const PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'

type PreviewTab = 'slide' | 'table'

export function SlideCanvas({
  module,
  slideMeta,
  slideOrdinal,
  filled,
  tableData,
  columnHeaders,
  pptxBytes,
}: {
  module: ModuleName
  slideMeta: SlideMeta
  slideOrdinal: number
  filled: boolean
  tableData?: string[][]
  columnHeaders?: string[]
  pptxBytes: ArrayBuffer | null
}) {
  const slideIdx = slideMeta.idx
  const model = buildNormalizedSlideTable(slideMeta, filled, tableData, columnHeaders)

  const [tab, setTab] = useState<PreviewTab>(() => (pptxBytes ? 'slide' : 'table'))
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewSource, setPreviewSource] = useState<SlidePreviewSource | null>(null)
  const [previewState, setPreviewState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const prevSlideIdxRef = useRef(slideIdx)
  const hadPptxRef = useRef(false)

  useEffect(() => {
    if (!previewUrl) setLightboxOpen(false)
  }, [previewUrl])

  useEffect(() => {
    if (!lightboxOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setLightboxOpen(false)
    }
    window.addEventListener('keydown', onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [lightboxOpen])

  useEffect(() => {
    if (!pptxBytes) {
      setPreviewUrl(null)
      setPreviewSource(null)
      setPreviewState('idle')
      setTab('table')
      hadPptxRef.current = false
      prevSlideIdxRef.current = slideIdx
      return
    }

    if (prevSlideIdxRef.current !== slideIdx) {
      setTab('slide')
      prevSlideIdxRef.current = slideIdx
    } else if (!hadPptxRef.current) {
      setTab('slide')
      hadPptxRef.current = true
    }

    let cancelled = false
    let objectUrl: string | null = null

    setPreviewState('loading')
    setPreviewUrl(null)
    setPreviewSource(null)

    const blob = new Blob([pptxBytes], { type: PPTX_MIME })
    void fetchSlideRenderPngValidated(slideIdx, blob)
      .then(({ blob: png, source }) => {
        const u = URL.createObjectURL(png)
        if (cancelled) {
          URL.revokeObjectURL(u)
          return
        }
        objectUrl = u
        setPreviewUrl(u)
        setPreviewSource(source)
        setPreviewState('ready')
      })
      .catch(() => {
        if (!cancelled) setPreviewState('error')
      })

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [pptxBytes, slideIdx])

  const showTabs = !!pptxBytes

  return (
    <section className="flex w-full justify-center">
      <div className="w-full max-w-[min(100%,56rem)]">
        <div
          className="relative overflow-hidden rounded-2xl bg-white shadow-[0_20px_60px_-24px_rgba(15,15,20,0.35)] ring-1 ring-neutral-200/80"
          style={{ aspectRatio: '16 / 9' }}
        >
          <div className="absolute inset-0 flex flex-col bg-gradient-to-b from-white via-white to-neutral-50/30 p-[6%] md:p-[7%]">
            <header className="mb-4 shrink-0 border-b border-neutral-200/60 pb-3 md:mb-5 md:pb-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h1 className="text-balance text-lg font-semibold tracking-tight text-neutral-900 md:text-xl">
                  {module}
                  <span className="font-normal text-neutral-400"> · </span>
                  <span className="font-normal text-neutral-600">Slide {slideOrdinal}</span>
                </h1>
                <span
                  className={`rounded-full px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-wider md:text-[11px] ${
                    filled
                      ? 'bg-neutral-900 text-white'
                      : 'bg-neutral-100 text-neutral-500 ring-1 ring-neutral-200/80'
                  }`}
                >
                  {filled ? 'Filled' : 'Draft'}
                </span>
              </div>
              <p className="mt-1.5 max-w-prose text-[11px] text-neutral-500 md:text-xs">
                {showTabs
                  ? 'Slide preview is a full-page raster of your deck (LibreOffice + PDF when the server has it; otherwise a table-only fallback). Use Data table for the grid view.'
                  : 'Structured workspace — load a deck to see the slide preview.'}
              </p>
              {showTabs && tab === 'table' ? (
                <p className="mt-2 rounded-md bg-neutral-100/90 px-2 py-1.5 text-[10px] text-neutral-600 md:text-[11px]">
                  You are viewing the <strong className="font-medium">Data table</strong> grid. Switch
                  to <strong className="font-medium">Slide preview</strong> for the page image from your
                  deck.
                </p>
              ) : null}
              {showTabs ? (
                <div className="mt-3 flex gap-1 rounded-lg bg-neutral-100/80 p-0.5 ring-1 ring-neutral-200/60">
                  <button
                    type="button"
                    onClick={() => setTab('slide')}
                    className={`flex-1 rounded-md px-3 py-1.5 text-[11px] font-medium transition-colors md:text-xs ${
                      tab === 'slide'
                        ? 'bg-white text-neutral-900 shadow-sm'
                        : 'text-neutral-500 hover:text-neutral-800'
                    }`}
                  >
                    Slide preview
                  </button>
                  <button
                    type="button"
                    onClick={() => setTab('table')}
                    className={`flex-1 rounded-md px-3 py-1.5 text-[11px] font-medium transition-colors md:text-xs ${
                      tab === 'table'
                        ? 'bg-white text-neutral-900 shadow-sm'
                        : 'text-neutral-500 hover:text-neutral-800'
                    }`}
                  >
                    Data table
                  </button>
                </div>
              ) : null}
            </header>

            <div className="min-h-0 flex-1 overflow-hidden">
              {tab === 'slide' && showTabs ? (
                <div className="flex h-full flex-col gap-2">
                  {previewState === 'ready' &&
                  previewUrl &&
                  (previewSource === 'matplotlib' || previewSource === 'unknown') ? (
                    <p className="shrink-0 rounded-md border border-amber-200/80 bg-amber-50/90 px-2 py-1.5 text-[10px] text-amber-950/90 md:text-[11px]">
                      <span className="font-medium">Simplified preview.</span> The API fell back to a
                      redrawn title+table, not a full LibreOffice page. On the machine running the API,
                      install <code className="rounded bg-amber-100/80 px-0.5">pymupdf</code> and
                      LibreOffice, ensure <code className="rounded bg-amber-100/80 px-0.5">soffice</code>{' '}
                      works (or set <code className="rounded bg-amber-100/80 px-0.5">SOFFICE_PATH</code>
                      ), then restart uvicorn.
                    </p>
                  ) : null}
                  {previewState === 'loading' ? (
                    <div className="flex flex-1 items-center justify-center rounded-xl bg-neutral-50/80 ring-1 ring-neutral-200/60">
                      <p className="text-[11px] text-neutral-400 md:text-xs">Rendering slide…</p>
                    </div>
                  ) : previewState === 'error' ? (
                    <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-xl bg-amber-50/60 px-4 ring-1 ring-amber-200/50">
                      <p className="text-center text-[11px] text-amber-900/80 md:text-xs">
                        Could not render slide preview. Use &ldquo;Data table&rdquo; or check the
                        backend.
                      </p>
                      <button
                        type="button"
                        onClick={() => setTab('table')}
                        className="rounded-md bg-amber-900/90 px-3 py-1 text-[11px] text-white md:text-xs"
                      >
                        Open data table
                      </button>
                    </div>
                  ) : previewUrl ? (
                    <div className="h-full min-h-0 overflow-auto rounded-xl bg-neutral-100/40 ring-1 ring-neutral-200/60">
                      <button
                        type="button"
                        className="relative block w-full cursor-zoom-in p-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/30 focus-visible:ring-offset-2"
                        onClick={() => setLightboxOpen(true)}
                        aria-label="Enlarge slide preview"
                      >
                        <img
                          src={previewUrl}
                          alt={`${module}, slide ${slideOrdinal}`}
                          className="mx-auto h-auto w-full max-h-full object-contain object-top transition-opacity hover:opacity-90"
                          draggable={false}
                        />
                        <span className="pointer-events-none absolute bottom-2 right-2 rounded-md bg-neutral-900/75 px-2 py-1 text-[10px] font-medium text-white shadow-sm md:text-[11px]">
                          Click to enlarge
                        </span>
                      </button>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="h-full overflow-y-auto pr-1">
                  <SlideTable model={model} dimmed={!filled} />
                </div>
              )}
            </div>

            {!filled && tab === 'table' ? (
              <p className="mt-3 shrink-0 text-[10px] text-neutral-400 md:text-[11px]">
                Fill this slide to generate content. Tables stay soft and readable — not a
                spreadsheet.
              </p>
            ) : null}
          </div>
        </div>
      </div>

      {lightboxOpen && previewUrl
        ? createPortal(
            <div
              className="fixed inset-0 z-[200] flex items-center justify-center bg-black/88 p-4 backdrop-blur-[2px]"
              role="dialog"
              aria-modal="true"
              aria-label={`Enlarged slide ${slideOrdinal}`}
              onClick={() => setLightboxOpen(false)}
            >
              <button
                type="button"
                className="absolute right-4 top-4 z-10 rounded-full bg-white/15 px-4 py-2 text-sm font-medium text-white ring-1 ring-white/25 transition hover:bg-white/25"
                onClick={(e) => {
                  e.stopPropagation()
                  setLightboxOpen(false)
                }}
              >
                Close
              </button>
              <p className="pointer-events-none absolute left-4 top-4 max-w-[min(24rem,calc(100vw-6rem))] text-xs text-white/70 md:text-sm">
                {module} · Slide {slideOrdinal}
              </p>
              <figure
                className="m-0 max-h-[min(92vh,calc(100vh-2rem))] max-w-[min(96vw,calc(100vw-2rem))]"
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') e.stopPropagation()
                }}
                tabIndex={-1}
              >
                <img
                  src={previewUrl}
                  alt={`${module}, slide ${slideOrdinal} (enlarged)`}
                  className="max-h-[min(92vh,calc(100vh-2rem))] max-w-[min(96vw,calc(100vw-2rem))] object-contain shadow-2xl ring-1 ring-white/15"
                  draggable={false}
                />
              </figure>
            </div>,
            document.body,
          )
        : null}
    </section>
  )
}
