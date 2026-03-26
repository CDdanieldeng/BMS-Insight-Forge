import type { ModuleName } from '@/types'

type Props = {
  module: ModuleName
  className?: string
  title?: string
}

const attrs = {
  xmlns: 'http://www.w3.org/2000/svg',
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

/** Distinct SVG mark for each business-plan module (stroke icons, inherits `currentColor`). */
export function ModuleIcon({ module, className = 'size-6', title }: Props) {
  switch (module) {
    case 'Customer Segmentation':
      return (
        <svg {...attrs} className={className} aria-hidden={title ? undefined : true} role={title ? 'img' : undefined}>
          {title ? <title>{title}</title> : null}
          <circle cx="12" cy="12" r="9" />
          <path d="M12 12V3" />
          <path d="M12 12 19.2 16.2" />
          <path d="M12 12 4.8 16.2" />
        </svg>
      )
    case 'SWOT Analysis':
      return (
        <svg {...attrs} className={className} aria-hidden={title ? undefined : true} role={title ? 'img' : undefined}>
          {title ? <title>{title}</title> : null}
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <path d="M12 3v18M3 12h18" />
        </svg>
      )
    case 'Messaging Strategy':
      return (
        <svg {...attrs} className={className} aria-hidden={title ? undefined : true} role={title ? 'img' : undefined}>
          {title ? <title>{title}</title> : null}
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          <path d="M8 10h8M8 14h5" />
        </svg>
      )
  }
}
