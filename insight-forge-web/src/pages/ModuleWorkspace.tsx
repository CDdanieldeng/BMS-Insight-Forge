import { useEffect } from 'react'

import type { ModuleName } from '@/types'
import { MODULES, isModuleName } from '@/utils/constants'
import { allFillableSlides, getSlidesByModule } from '@/utils/moduleSlides'
import { useAppStore } from '@/store/appStore'
import { useIsProcessing } from '@/hooks/useIsProcessing'

import { ModuleIcon } from '@/components/ModuleIcon'
import { DownloadBar } from '@/features/nav/DownloadBar'
import { ProgressNavigator } from '@/features/nav/ProgressNavigator'
import { ModuleLandingPage } from '@/features/module/ModuleLandingPage'
import { SlideWorkspace } from '@/features/slide/SlideWorkspace'

export function ModuleWorkspace() {
  const slideInfo = useAppStore((s) => s.slideInfo)
  const activeModule = useAppStore((s) => s.activeModule)
  const setActiveModule = useAppStore((s) => s.setActiveModule)
  const currentPageByModule = useAppStore((s) => s.currentPageByModule)
  const setCurrentPage = useAppStore((s) => s.setCurrentPage)
  const bumpCurrentPage = useAppStore((s) => s.bumpCurrentPage)
  const filledSlides = useAppStore((s) => s.filledSlides)
  const pptxBytes = useAppStore((s) => s.pptxBytes)
  const resetWorkspace = useAppStore((s) => s.resetWorkspace)
  const selectedProduct = useAppStore((s) => s.selectedProduct)
  const productDescription = useAppStore((s) => s.productDescription)
  const completionCelebrated = useAppStore((s) => s.completionCelebrated)
  const setCompletionCelebrated = useAppStore((s) => s.setCompletionCelebrated)
  const isProcessing = useIsProcessing()

  const slidesByModule = getSlidesByModule(slideInfo)
  const allFill = allFillableSlides(slideInfo)
  const nTotal = allFill.length
  const nFilled = allFill.filter((s) => filledSlides.includes(s.idx)).length
  const progress = nTotal > 0 ? nFilled / nTotal : 0

  const module: ModuleName = isModuleName(activeModule) ? activeModule : 'Customer Segmentation'
  const slides = slidesByModule[module]
  const totalPages = 1 + slides.length
  let cur = currentPageByModule[module] ?? 0
  cur = Math.max(0, Math.min(cur, totalPages - 1))

  useEffect(() => {
    const cap = totalPages - 1
    if ((currentPageByModule[module] ?? 0) > cap) {
      setCurrentPage(module, cap)
    }
  }, [module, totalPages, currentPageByModule, setCurrentPage])

  const isComplete = nTotal > 0 && nFilled === nTotal && !!pptxBytes

  useEffect(() => {
    if (isComplete && !completionCelebrated) {
      setCompletionCelebrated(true)
    }
    if (!isComplete) {
      setCompletionCelebrated(false)
    }
  }, [isComplete, completionCelebrated, setCompletionCelebrated])

  if (!slideInfo.length) {
    return (
      <div className="mx-auto max-w-md py-20 text-center">
        <p className="text-sm text-neutral-600">No slide info loaded.</p>
        <button
          type="button"
          onClick={() => resetWorkspace()}
          className="mt-6 rounded-xl bg-neutral-900 px-6 py-2.5 text-xs font-medium text-white"
        >
          Back to welcome
        </button>
      </div>
    )
  }

  const slideFilledFlags = slides.map((s) => filledSlides.includes(s.idx))
  const modAllDone = slides.length > 0 && slideFilledFlags.every(Boolean)

  return (
    <div>
      <header className="mb-8 flex flex-col gap-4 border-b border-neutral-200/60 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-neutral-900">ZS BP Coach</h1>
          <p className="mt-1 text-xs text-neutral-500">
            {selectedProduct ? `${selectedProduct} · ` : ''}Presentation workspace
          </p>
          {productDescription ? (
            <p className="mt-1 max-w-2xl text-[11px] leading-relaxed text-neutral-400 line-clamp-3">
              {productDescription}
            </p>
          ) : null}
        </div>
        <div className="w-full max-w-md md:w-72">
          <div className="h-1.5 overflow-hidden rounded-full bg-neutral-200/80">
            <div
              className="h-full rounded-full bg-neutral-900 transition-all duration-500"
              style={{ width: `${Math.round(progress * 100)}%` }}
            />
          </div>
          <p className="mt-2 text-right text-[11px] text-neutral-400">
            {nTotal ? `${nFilled} / ${nTotal} slides` : '—'}
          </p>
        </div>
      </header>

      <div className="mb-8 flex flex-wrap gap-2 border-b border-neutral-100 pb-4">
        {MODULES.map((m) => {
          const sl = slidesByModule[m]
          const d = sl.filter((x) => filledSlides.includes(x.idx)).length
          const active = m === module
          return (
            <button
              key={m}
              type="button"
              onClick={() => setActiveModule(m)}
              className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-xs font-medium transition ${
                active
                  ? 'bg-neutral-900 text-white shadow-sm [&_svg]:text-neutral-300'
                  : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200/80 [&_svg]:text-neutral-500'
              }`}
            >
              <ModuleIcon module={m} className="size-4" />
              <span className={active ? 'opacity-60' : 'opacity-50'}>
                {d}/{sl.length}
              </span>
              {m}
            </button>
          )
        })}
      </div>

      <ProgressNavigator
        module={module}
        curPage={cur}
        totalPages={totalPages}
        slideFilledFlags={slideFilledFlags}
        onPrev={() => bumpCurrentPage(module, -1)}
        onNext={() => bumpCurrentPage(module, 1)}
        onGoLanding={() => setCurrentPage(module, 0)}
        onGoSlide={(p) => setCurrentPage(module, p)}
        disabled={isProcessing}
      />

      <div className="mt-8">
        {cur === 0 ? (
          <ModuleLandingPage module={module} slides={slides} />
        ) : (
          <SlideWorkspace
            module={module}
            slideMeta={slides[cur - 1]!}
            slideOrdinal={cur}
          />
        )}
      </div>

      {modAllDone && pptxBytes ? (
        <div className="mx-auto mt-10 max-w-md">
          <DownloadBar
            label={`${module} is complete`}
            fileName="insight_forge_deck.pptx"
            pptxBytes={pptxBytes}
          />
        </div>
      ) : null}

      {isComplete && pptxBytes ? (
        <div className="mx-auto mt-10 max-w-lg border-t border-neutral-200/80 pt-10">
          <p className="text-center text-sm font-medium text-neutral-800">All modules complete</p>
          <div className="mt-4">
            <DownloadBar label="Final deck" fileName="insight_forge_deck.pptx" pptxBytes={pptxBytes} />
          </div>
        </div>
      ) : null}

      <footer className="mt-16 flex justify-center border-t border-neutral-100 pt-8">
        <button
          type="button"
          onClick={() => resetWorkspace()}
          className="text-[11px] text-neutral-400 hover:text-neutral-700"
        >
          Exit to welcome
        </button>
      </footer>
    </div>
  )
}
