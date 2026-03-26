import type { NormalizedSlideTable } from '@/utils/slideTable'

export function SlideTable({
  model,
  dimmed,
}: {
  model: NormalizedSlideTable
  dimmed?: boolean
}) {
  const { columnNames, rows, rowLabels, showCornerColumn, hideRowLabelsColumn } = model

  return (
    <div
      className={
        dimmed ? 'opacity-[0.38] transition-opacity' : 'opacity-100 transition-opacity'
      }
    >
      <div className="overflow-auto rounded-xl bg-neutral-50/80 ring-1 ring-neutral-200/60">
        <table className="w-full min-w-0 border-separate border-spacing-0 text-left text-[11px] leading-snug text-neutral-800 md:text-xs">
          <thead>
            <tr>
              {showCornerColumn && !hideRowLabelsColumn ? (
                <th className="sticky top-0 z-10 w-[22%] min-w-[5rem] rounded-tl-xl bg-neutral-200/50 px-2 py-2.5 font-semibold text-neutral-600 md:px-3 md:py-3">
                  {/* corner */}
                </th>
              ) : null}
              {columnNames.map((c, i) => (
                <th
                  key={i}
                  className={`sticky top-0 z-10 bg-neutral-900/[0.06] px-2 py-2.5 font-semibold tracking-tight text-neutral-800 md:px-3 md:py-3 ${
                    !showCornerColumn && i === 0 && !hideRowLabelsColumn
                      ? 'rounded-tl-xl'
                      : ''
                  } ${
                    i === columnNames.length - 1 && hideRowLabelsColumn ? 'rounded-tr-xl' : ''
                  }`}
                >
                  <span className="line-clamp-3 break-words">{c || '—'}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {!rows.length ? (
              <tr>
                <td
                  colSpan={
                    columnNames.length + (showCornerColumn && !hideRowLabelsColumn ? 1 : 0)
                  }
                  className="px-3 py-8 text-center text-[11px] italic text-neutral-400 md:text-xs"
                >
                  Content will appear here after you fill this slide.
                </td>
              </tr>
            ) : (
              rows.map((row, ri) => (
                <tr key={ri} className="group">
                  {showCornerColumn && !hideRowLabelsColumn ? (
                    <th
                      scope="row"
                      className="border-t border-neutral-200/50 bg-neutral-100/30 px-2 py-2 align-top font-medium text-neutral-600 md:px-3 md:py-2.5"
                    >
                      <span className="line-clamp-4 break-words">
                        {rowLabels[ri] ?? `Row ${ri + 1}`}
                      </span>
                    </th>
                  ) : null}
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      className="border-t border-neutral-200/50 px-2 py-2 align-top text-neutral-700 md:px-3 md:py-2.5"
                    >
                      <span className="line-clamp-[8] whitespace-pre-wrap break-words">
                        {cell?.trim() ? cell : ' '}
                      </span>
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
