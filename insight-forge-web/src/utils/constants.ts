import type { ModuleName } from '@/types'

/** Served from `public/ZS_Associates_Logo.svg`. */
export const ZS_LOGO_SRC = '/ZS_Associates_Logo.svg'

export const MODULES: ModuleName[] = [
  'Customer Segmentation',
  'SWOT Analysis',
  'Messaging Strategy',
]

export const MODULE_DESC: Record<ModuleName, string> = {
  'Customer Segmentation':
    'Identify stakeholders along the patient journey, segment by value and receptivity, and pinpoint behavior changes at each leverage point.',
  'Messaging Strategy':
    'Craft targeted messages for behavior-change objectives, aligned to the Unified Brand Story, versus the competitive set.',
  'SWOT Analysis':
    'Assess strengths, weaknesses, opportunities, and threats to surface strategic priorities and key risks.',
}

export function isModuleName(s: string): s is ModuleName {
  return (MODULES as readonly string[]).includes(s)
}
