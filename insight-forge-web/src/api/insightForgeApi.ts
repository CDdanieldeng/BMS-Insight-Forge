import type {
  ChatMessage,
  ChatMode,
  CoworkChatResponse,
  FillGenerationResult,
  ModifyChatResponse,
  ModuleName,
  SlideMeta,
  TableStructure,
  WebSearchResult,
} from '@/types'
import { jsonToBase64, base64ToArrayBuffer } from '@/utils/b64'

import { api } from './client'

function historyForApi(messages: ChatMessage[]): { role: string; content: string }[] {
  return messages.map((m) => ({ role: m.role, content: m.content }))
}

export async function fetchSlideInfoFromPptx(pptx: Blob): Promise<SlideMeta[]> {
  const form = new FormData()
  form.append('file', pptx, 'deck.pptx')
  const { data } = await api.post<SlideMeta[]>('/fill-engine/slide-info', form, {
    timeout: 60_000,
  })
  return data
}

export async function fetchTableStructure(slideIdx: number, pptx: Blob): Promise<TableStructure> {
  const form = new FormData()
  form.append('slide_idx', String(slideIdx))
  form.append('file', pptx, 'deck.pptx')
  const { data } = await api.post<TableStructure>('/fill-engine/table-structure', form, {
    timeout: 30_000,
  })
  return data
}

export type SlidePreviewSource = 'raster' | 'matplotlib' | 'unknown'

/** PNG from /fill-engine/render-slide-png; header tells raster vs matplotlib fallback. */
export async function fetchSlideRenderPng(
  slideIdx: number,
  pptx: Blob,
): Promise<{ blob: Blob; source: SlidePreviewSource }> {
  const form = new FormData()
  form.append('slide_idx', String(slideIdx))
  form.append('file', pptx, 'deck.pptx')
  const res = await api.post<Blob>('/fill-engine/render-slide-png', form, {
    responseType: 'blob',
    timeout: 120_000,
  })
  const h = res.headers as { get?: (key: string) => string | undefined } & Record<string, string>
  const raw = (
    h.get?.('x-insight-forge-slide-preview') ?? h['x-insight-forge-slide-preview']
  )?.toLowerCase()
  const source: SlidePreviewSource =
    raw === 'raster' ? 'raster' : raw === 'matplotlib' ? 'matplotlib' : 'unknown'
  return { blob: res.data, source }
}

async function blobIsPng(blob: Blob): Promise<boolean> {
  if (blob.size < 8) return false
  const prefix = new Uint8Array(await blob.slice(0, 8).arrayBuffer())
  return (
    prefix[0] === 0x89 &&
    prefix[1] === 0x50 &&
    prefix[2] === 0x4e &&
    prefix[3] === 0x47 &&
    prefix[4] === 0x0d &&
    prefix[5] === 0x0a &&
    prefix[6] === 0x1a &&
    prefix[7] === 0x0a
  )
}

/** Fetches preview and validates PNG magic bytes (avoids showing broken img on bad responses). */
export async function fetchSlideRenderPngValidated(
  slideIdx: number,
  pptx: Blob,
): Promise<{ blob: Blob; source: SlidePreviewSource }> {
  const { blob, source } = await fetchSlideRenderPng(slideIdx, pptx)
  if (!(await blobIsPng(blob))) {
    let hint = 'Server did not return a valid PNG.'
    try {
      const text = await blob.text()
      const j = JSON.parse(text) as { detail?: string }
      if (j?.detail) hint = j.detail
    } catch {
      /* ignore */
    }
    throw new Error(hint)
  }
  return { blob, source }
}

export async function postGenerationFill(body: {
  slide_idx: number
  module: ModuleName
  file_ids: string[]
  table_structure: TableStructure
  cowork_guidance?: { summary: string; segment_names: string[] } | null
}): Promise<FillGenerationResult> {
  const { data } = await api.post<FillGenerationResult>('/generation/fill', body, {
    timeout: 240_000,
  })
  return data
}

export async function postFillTable(params: {
  slideIdx: number
  pptx: Blob
  tableData: string[][]
  module?: ModuleName
  columnHeaders?: string[]
}): Promise<ArrayBuffer> {
  const { slideIdx, pptx, tableData, module, columnHeaders } = params
  const form = new FormData()
  form.append('slide_idx', String(slideIdx))
  form.append('table_data_b64', jsonToBase64(tableData))
  if (module) form.append('module', module)
  if (columnHeaders?.length) {
    form.append('column_headers_b64', jsonToBase64(columnHeaders))
  }
  form.append('file', pptx, 'deck.pptx')
  const { data } = await api.post<{ pptx_base64: string }>('/fill-engine/fill-table', form, {
    timeout: 60_000,
  })
  return base64ToArrayBuffer(data.pptx_base64)
}

export async function postFillSwotPlaceholders(params: {
  slideIdx: number
  pptx: Blob
  tableData: string[][]
}): Promise<ArrayBuffer> {
  const form = new FormData()
  form.append('slide_idx', String(params.slideIdx))
  form.append('table_data_b64', jsonToBase64(params.tableData))
  form.append('file', params.pptx, 'deck.pptx')
  const { data } = await api.post<{ pptx_base64: string }>(
    '/fill-engine/fill-swot-placeholders',
    form,
    { timeout: 60_000 },
  )
  return base64ToArrayBuffer(data.pptx_base64)
}

export async function postDocumentIngest(files: File[]): Promise<{
  file_ids: string[]
  errors: { file?: string; error?: string }[]
}> {
  const form = new FormData()
  for (const f of files) {
    form.append('files', f, f.name)
  }
  const { data } = await api.post('/document/ingest', form, { timeout: 120_000 })
  return data as { file_ids: string[]; errors: { file?: string; error?: string }[] }
}

export async function postWebSearch(query: string): Promise<WebSearchResult[]> {
  const { data } = await api.post<{ results: WebSearchResult[] }>(
    '/web-search/search',
    { query, max_results: 5 },
    { timeout: 30_000 },
  )
  return data.results ?? []
}

export async function postGenerationChat(body: {
  slide_idx: number
  module: ModuleName
  file_ids: string[]
  current_content: string[][]
  table_structure: TableStructure
  current_column_headers?: string[] | null
  user_message: string
  conversation_history: { role: string; content: string }[]
  mode: ChatMode | 'ask'
}): Promise<ModifyChatResponse> {
  const { data } = await api.post<ModifyChatResponse>('/generation/chat', body, {
    timeout: 240_000,
  })
  return data
}

function coworkEndpoint(module: ModuleName): string {
  return module === 'SWOT Analysis'
    ? '/cowork-agent/swot/chat'
    : '/cowork-agent/cs/chat'
}

export async function postCoworkChat(body: {
  session_id: string
  module: ModuleName
  slide_idx: number
  file_ids: string[]
  table_structure: TableStructure
  user_message: string
  conversation_history: { role: string; content: string }[]
  allow_web_search: boolean
  action?: 'end_conversation'
  cs_cowork_summary?: string
  cs_filled_table?: string[][]
  cs_filled_headers?: string[]
}): Promise<CoworkChatResponse> {
  const { data } = await api.post<CoworkChatResponse>(coworkEndpoint(body.module), body, {
    timeout: 240_000,
  })
  return data
}

export async function endCoworkConversation(params: {
  module: ModuleName
  slideIdx: number
  sessionId: string
  fileIds: string[]
  tableStructure: TableStructure
  history: ChatMessage[]
  csContext?: {
    summary?: string | null
    table?: string[][] | null
    headers?: string[] | null
  }
}): Promise<CoworkChatResponse> {
  const payload: Parameters<typeof postCoworkChat>[0] = {
    session_id: params.sessionId,
    module: params.module,
    slide_idx: params.slideIdx,
    file_ids: params.fileIds,
    table_structure: params.tableStructure,
    user_message: '',
    conversation_history: historyForApi(params.history),
    allow_web_search: false,
    action: 'end_conversation',
  }
  const ctx = params.csContext
  if (ctx?.summary) payload.cs_cowork_summary = ctx.summary
  if (ctx?.table?.length) payload.cs_filled_table = ctx.table
  if (ctx?.headers?.length) payload.cs_filled_headers = ctx.headers
  return postCoworkChat(payload)
}

export async function sendCoworkMessage(params: {
  module: ModuleName
  slideIdx: number
  sessionId: string
  fileIds: string[]
  tableStructure: TableStructure
  history: ChatMessage[]
  userMessage: string
  allowWeb: boolean
  csContext?: {
    summary?: string | null
    table?: string[][] | null
    headers?: string[] | null
  }
}): Promise<CoworkChatResponse> {
  const payload: Parameters<typeof postCoworkChat>[0] = {
    session_id: params.sessionId,
    module: params.module,
    slide_idx: params.slideIdx,
    file_ids: params.fileIds,
    table_structure: params.tableStructure,
    user_message: params.userMessage,
    conversation_history: historyForApi(params.history),
    allow_web_search: params.allowWeb,
  }
  const ctx = params.csContext
  if (ctx?.summary) payload.cs_cowork_summary = ctx.summary
  if (ctx?.table?.length) payload.cs_filled_table = ctx.table
  if (ctx?.headers?.length) payload.cs_filled_headers = ctx.headers
  return postCoworkChat(payload)
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  let binary = ''
  const bytes = new Uint8Array(buffer)
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]!)
  }
  return btoa(binary)
}

/** SSE stream: consumes `data: {...}\\n\\n` lines from /voice/transcribe/stream */
export async function transcribeVoiceStream(
  wavBytes: ArrayBuffer,
  language: string,
  onEvent: (ev: { type: string; transcript?: string; message?: string }) => void,
): Promise<void> {
  const audio_b64 = arrayBufferToBase64(wavBytes)
  const res = await fetch(`${api.defaults.baseURL}/voice/transcribe/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ audio_b64, language }),
  })
  if (!res.ok || !res.body) {
    throw new Error(`Voice request failed (${res.status})`)
  }
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() ?? ''
    for (const block of parts) {
      const line = block.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      try {
        const ev = JSON.parse(line.slice(6)) as {
          type: string
          transcript?: string
          message?: string
        }
        onEvent(ev)
      } catch {
        /* ignore */
      }
    }
  }
}
