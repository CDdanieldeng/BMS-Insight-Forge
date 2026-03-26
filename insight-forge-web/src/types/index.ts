export type ModuleName =
  | 'Customer Segmentation'
  | 'SWOT Analysis'
  | 'Messaging Strategy'

export interface TableStructure {
  columns: string[]
  indexes: string[]
}

export interface SlideMeta {
  idx: number
  is_fillable: boolean
  module: string
  table_structure?: TableStructure
  is_swot_placeholder_template?: boolean
}

export type ChatRole = 'user' | 'assistant'

export interface ChatMessage {
  role: ChatRole
  content: string
  thinking?: string
}

export interface CoworkDraft {
  table_data: string[][]
  column_headers: string[]
}

export interface WebSearchResult {
  title?: string
  url?: string
  content?: string
}

export type ChatMode = 'cowork' | 'modify'

/** Ephemeral UI while waiting for or revealing the assistant reply */
export type ChatAssistantLive =
  | null
  | 'typing'
  | { partialText: string; thinking?: string }

export interface CoworkChatResponse {
  assistant_message: string
  thinking?: string | null
  draft_table_data?: string[][]
  /** Segment names or header draft; also returned when ending conversation */
  draft_column_headers?: string[]
  workflow?: { ready_for_ppt_fill?: boolean }
}

export interface ModifyChatResponse {
  assistant_message: string
  table_data?: string[][]
  column_headers?: string[] | null
  mode?: ChatMode | string
}

export interface FillGenerationResult {
  table_data: string[][]
  column_headers?: string[] | null
}

export interface PendingIngestFile {
  name: string
  data: ArrayBuffer
}
