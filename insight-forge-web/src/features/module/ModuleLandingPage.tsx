import type { ModuleName, SlideMeta } from '@/types'
import { ModuleIcon } from '@/components/ModuleIcon'
import { MODULE_DESC } from '@/utils/constants'
import { useAppStore } from '@/store/appStore'
import { ModuleLandingCoworkBlock } from '@/features/module/ModuleLandingCoworkBlock'

function moduleHasLandingCowork(module: ModuleName): boolean {
  return module === 'Customer Segmentation' || module === 'SWOT Analysis'
}

export function ModuleLandingPage({ module, slides }: { module: ModuleName; slides: SlideMeta[] }) {
  const filledSlides = useAppStore((s) => s.filledSlides)
  const n = slides.length
  const done = slides.filter((s) => filledSlides.includes(s.idx)).length
  const firstSlide = slides[0]
  const showCoworkBlock = moduleHasLandingCowork(module) && firstSlide != null

  return (
    <div className="mx-auto max-w-3xl py-8 md:py-14">
      <div className="rounded-3xl border border-neutral-200/80 bg-white px-8 py-10 shadow-[0_24px_60px_-32px_rgba(0,0,0,0.25)] md:px-12 md:py-12">
        <ModuleIcon
          module={module}
          className="size-12 text-neutral-400"
          title={`${module} icon`}
        />
        <h1 className="mt-4 text-3xl font-semibold tracking-tight text-neutral-900 md:text-4xl">
          {module}
        </h1>
        <p className="mt-4 max-w-prose text-sm leading-relaxed text-neutral-500 md:text-base">
          {MODULE_DESC[module]}
        </p>
        <div className="mt-8 inline-flex items-center gap-2 rounded-full bg-neutral-100 px-4 py-1.5 text-xs font-medium text-neutral-600">
          <span className="size-1.5 rounded-full bg-neutral-400" />
          {n === 0 ? 'No slides' : `${done} / ${n} slides complete`}
        </div>
        <p className="mt-8 text-xs text-neutral-400">
          {showCoworkBlock ? (
            <>
              Use <span className="text-neutral-600">Co-work</span> below to align on this module,
              then <span className="text-neutral-600">Next</span> for each slide to review and refine.
            </>
          ) : (
            <>
              Use <span className="text-neutral-600">Next</span> to open the presentation workspace
              for each slide.
            </>
          )}
        </p>
      </div>
      {showCoworkBlock ? <ModuleLandingCoworkBlock module={module} slideMeta={firstSlide} /> : null}
    </div>
  )
}
