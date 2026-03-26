import type { SlideMeta } from '@/types'

export interface NormalizedSlideTable {
  rowLabels: string[]
  columnNames: string[]
  rows: string[][]
  /** CS-style index column in the template */
  showCornerColumn: boolean
  /** SWOT-style: no row labels, only quadrant columns */
  hideRowLabelsColumn: boolean
}

/**
 * Normalizes slide table structure for preview so filled / unfilled tables render consistently.
 */
export function buildNormalizedSlideTable(
  slideMeta: SlideMeta,
  filled: boolean,
  tableData: string[][] | undefined,
  columnHeaders: string[] | undefined,
): NormalizedSlideTable {
  const table_structure = slideMeta.table_structure ?? { columns: [], indexes: [] }
  const row_labels = table_structure.indexes ?? []
  const module = (slideMeta.module ?? '').trim().toLowerCase()
  const is_swot = module === 'swot analysis'
  const hideRowLabelsColumn = is_swot
  const template_col_names = is_swot
    ? table_structure.columns ?? []
    : (table_structure.columns ?? []).slice(1)

  if (filled && tableData) {
    const normalized_rows = tableData.filter((r): r is string[] => Array.isArray(r))
    const n_data_rows = normalized_rows.length
    const n_data_cols = Math.max(
      1,
      normalized_rows.length ? Math.max(...normalized_rows.map((r) => r.length)) : template_col_names.length,
    )

    const padded = normalized_rows.map((r) => {
      const c = [...r].slice(0, n_data_cols)
      while (c.length < n_data_cols) c.push('')
      return c
    })

    let col_names: string[]
    if (columnHeaders && columnHeaders.length === n_data_cols) {
      col_names = columnHeaders
    } else {
      const base_cols = [...template_col_names].slice(0, n_data_cols)
      if (base_cols.length < n_data_cols) {
        for (let i = base_cols.length; i < n_data_cols; i++) {
          base_cols.push(`Column ${i + 1}`)
        }
      }
      col_names = base_cols
    }

    let idx_names: string[]
    if (row_labels.length) {
      idx_names = row_labels.slice(0, n_data_rows)
      if (idx_names.length < n_data_rows) {
        for (let i = idx_names.length; i < n_data_rows; i++) {
          idx_names.push(`Row ${i + 1}`)
        }
      }
    } else {
      idx_names = Array.from({ length: n_data_rows }, (_, i) => `Row ${i + 1}`)
    }

    if (padded.length) {
      return {
        rowLabels: idx_names,
        columnNames: col_names,
        rows: padded,
        showCornerColumn: !is_swot && row_labels.length > 0,
        hideRowLabelsColumn,
      }
    }

    const fallback_rows = row_labels.length ? row_labels : ['(no rows)']
    const fallback_cols = template_col_names.length ? template_col_names : ['(no columns)']
    const empty_rows = fallback_rows.map(() => fallback_cols.map(() => ''))
    return {
      rowLabels: fallback_rows,
      columnNames: fallback_cols,
      rows: empty_rows,
      showCornerColumn: !is_swot && fallback_rows.length > 0,
      hideRowLabelsColumn,
    }
  }

  const cols = template_col_names.length ? template_col_names : ['—']
  const idx = row_labels.length ? row_labels : []
  const placeholderRows =
    idx.length > 0 ? idx : is_swot ? [' '] : ['—']
  const empty_rows = placeholderRows.map(() => cols.map(() => ''))
  return {
    rowLabels: placeholderRows,
    columnNames: cols,
    rows: empty_rows,
    showCornerColumn: !is_swot && row_labels.length > 0,
    hideRowLabelsColumn,
  }
}
