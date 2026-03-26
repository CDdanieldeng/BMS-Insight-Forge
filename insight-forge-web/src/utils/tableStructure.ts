import type { SlideMeta, TableStructure } from '@/types'

export function coerceTableStructure(meta: SlideMeta): TableStructure {
  const t = meta.table_structure
  return {
    columns: t?.columns ?? [],
    indexes: t?.indexes ?? [],
  }
}
