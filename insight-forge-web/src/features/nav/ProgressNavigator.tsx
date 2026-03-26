import type { ModuleName } from '@/types'
import { ModuleIcon } from '@/components/ModuleIcon'

export function ProgressNavigator({
  module,
  curPage,
  totalPages,
  slideFilledFlags,
  onPrev,
  onNext,
  onGoLanding,
  onGoSlide,
  disabled,
}: {
  module: ModuleName
  curPage: number
  totalPages: number
  slideFilledFlags: boolean[]
  onPrev: () => void
  onNext: () => void
  onGoLanding: () => void
  onGoSlide: (slidePageIndex: number) => void
  disabled: boolean
}) {
  const nSlides = totalPages - 1

  return (
    <nav className="flex flex-col gap-4 border-b border-neutral-200/60 pb-6 md:flex-row md:items-center md:justify-between">
      <div className="flex gap-2">
        <button
          type="button"
          disabled={disabled || curPage <= 0}
          onClick={onPrev}
          className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs font-medium text-neutral-700 shadow-sm hover:bg-neutral-50 disabled:opacity-40"
        >
          ← Back
        </button>
        <button
          type="button"
          disabled={disabled || curPage >= totalPages - 1}
          onClick={onNext}
          className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs font-medium text-neutral-700 shadow-sm hover:bg-neutral-50 disabled:opacity-40"
        >
          Next →
        </button>
      </div>

      <div className="flex flex-col items-center gap-1">
        <div className="flex flex-wrap items-center justify-center gap-2">
          <button
            type="button"
            disabled={disabled}
            onClick={onGoLanding}
            className={`flex size-8 items-center justify-center rounded-full text-xs transition ${
              curPage === 0
                ? 'bg-neutral-900 text-white shadow-sm'
                : 'bg-neutral-100 text-neutral-500 hover:bg-neutral-200/80'
            }`}
            aria-label="Module home"
            title="Home"
          >
            ⌂
          </button>
          {Array.from({ length: nSlides }, (_, i) => {
            const filled = slideFilledFlags[i]
            const page = i + 1
            const active = curPage === page
            return (
              <button
                key={i}
                type="button"
                disabled={disabled}
                onClick={() => onGoSlide(page)}
                className={`flex size-8 items-center justify-center rounded-full text-[10px] font-medium transition ${
                  active
                    ? 'ring-2 ring-neutral-900 ring-offset-2 ring-offset-neutral-50'
                    : ''
                } ${
                  filled
                    ? 'bg-neutral-800 text-white'
                    : active
                      ? 'bg-white text-neutral-900 ring-1 ring-neutral-300'
                      : 'bg-neutral-100 text-neutral-400 hover:bg-neutral-200/80'
                }`}
                aria-label={`Slide ${page} of ${nSlides}`}
                title={`Slide ${page}`}
              >
                {filled ? '✓' : page}
              </button>
            )
          })}
        </div>
        <p className="flex items-center justify-center gap-1.5 text-[11px] text-neutral-400">
          {curPage === 0 ? (
            <>
              <ModuleIcon module={module} className="size-3.5 text-neutral-400" />
              <span>
                {module} · Overview
              </span>
            </>
          ) : (
            `Slide ${curPage} of ${nSlides}`
          )}
        </p>
      </div>

      <p className="hidden text-right text-[11px] text-neutral-400 md:block md:w-40">
        Linear navigation
      </p>
    </nav>
  )
}
