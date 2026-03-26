import type { ModuleName, SlideMeta } from '@/types'
import { MODULES } from '@/utils/constants'

export function getSlidesByModule(slideInfo: SlideMeta[]): Record<ModuleName, SlideMeta[]> {
  const grouped: Record<ModuleName, SlideMeta[]> = {
    'Customer Segmentation': [],
    'SWOT Analysis': [],
    'Messaging Strategy': [],
  }
  for (const s of slideInfo) {
    if (!s.is_fillable) continue
    const m = s.module
    if (m in grouped) grouped[m as ModuleName].push(s)
  }
  return grouped
}

export function allFillableSlides(slideInfo: SlideMeta[]): SlideMeta[] {
  return MODULES.flatMap((m) => getSlidesByModule(slideInfo)[m])
}
