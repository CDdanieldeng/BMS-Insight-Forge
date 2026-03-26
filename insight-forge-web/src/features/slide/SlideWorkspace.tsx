import { useCallback, useEffect, useState } from 'react'

import type {
  ChatAssistantLive,
  ChatMessage,
  ChatMode,
  ModuleName,
  SlideMeta,
  WebSearchResult,
} from '@/types'

const EMPTY_CHAT_MESSAGES: ChatMessage[] = []
const EMPTY_WEB_RESULTS: WebSearchResult[] = []
import {
  endCoworkConversation,
  fetchTableStructure,
  postDocumentIngest,
  postFillSwotPlaceholders,
  postFillTable,
  postGenerationChat,
  postGenerationFill,
  postWebSearch,
  sendCoworkMessage,
} from '@/api/insightForgeApi'
import { defaultChatModeForModule, useAppStore } from '@/store/appStore'
import { coerceTableStructure } from '@/utils/tableStructure'

import { ChatPanel } from '@/features/chat/ChatPanel'
import { ControlsPanel } from '@/features/controls/ControlsPanel'
import { SlideCanvas } from '@/features/slide/SlideCanvas'
import { WebSearchPanel } from '@/features/web/WebSearchPanel'

function deckBlob(buf: ArrayBuffer): Blob {
  return new Blob([buf], {
    type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  })
}

type AssistantLiveState =
  | null
  | { slideIdx: number; phase: 'request' }
  | { slideIdx: number; phase: 'stream'; full: string; pos: number; thinking?: string }

function toPanelAssistantLive(slideIdx: number, live: AssistantLiveState): ChatAssistantLive {
  if (!live || live.slideIdx !== slideIdx) return null
  if (live.phase === 'request') return 'typing'
  return { partialText: live.full.slice(0, live.pos), thinking: live.thinking }
}

export function SlideWorkspace({
  module,
  slideMeta,
  slideOrdinal,
}: {
  module: ModuleName
  slideMeta: SlideMeta
  slideOrdinal: number
}) {
  const slideIdx = slideMeta.idx

  const processing = useAppStore((s) => !!s.processingMessage)
  const pptxBytes = useAppStore((s) => s.pptxBytes)
  const fileIds = useAppStore((s) => s.fileIdsByModule[module])
  const tableData = useAppStore((s) => s.tableDataBySlide[slideIdx])
  const columnHeaders = useAppStore((s) => s.columnHeadersBySlide[slideIdx])
  const filled = useAppStore((s) => s.filledSlides.includes(slideIdx))
  const messages = useAppStore((s) => s.chatHistoryBySlide[slideIdx] ?? EMPTY_CHAT_MESSAGES)
  const mode = useAppStore(
    (s) => s.chatModeBySlide[slideIdx] ?? defaultChatModeForModule(module),
  )
  const coworkReady = useAppStore((s) => s.coworkReadyBySlide[slideIdx] ?? false)
  const coworkDraft = useAppStore((s) => s.coworkDraftBySlide[slideIdx])
  const wsQuery = useAppStore((s) => s.webSearchQueryBySlide[slideIdx] ?? '')
  const wsResults = useAppStore((s) => s.webSearchResultsBySlide[slideIdx] ?? EMPTY_WEB_RESULTS)

  const setProcessing = useAppStore((s) => s.setProcessing)
  const setBannerError = useAppStore((s) => s.setBannerError)
  const setPptxBytes = useAppStore((s) => s.setPptxBytes)
  const setFileIds = useAppStore((s) => s.setFileIdsForModule)
  const markSlideFilled = useAppStore((s) => s.markSlideFilled)
  const appendChat = useAppStore((s) => s.appendChatMessage)
  const setChatMode = useAppStore((s) => s.setChatMode)
  const clearSlideChat = useAppStore((s) => s.clearSlideChat)
  const getOrCreateCoworkSession = useAppStore((s) => s.getOrCreateCoworkSession)
  const setCoworkDraft = useAppStore((s) => s.setCoworkDraft)
  const setCoworkSummary = useAppStore((s) => s.setCoworkSummary)
  const setWebSearch = useAppStore((s) => s.setWebSearch)
  const clearWebSearch = useAppStore((s) => s.clearWebSearch)
  const getCsContextForSwot = useAppStore((s) => s.getCsContextForSwot)

  const [assistantLiveInternal, setAssistantLiveInternal] = useState<AssistantLiveState>(null)

  useEffect(() => {
    setAssistantLiveInternal(null)
  }, [slideIdx])

  useEffect(() => {
    const live = assistantLiveInternal
    if (!live || live.slideIdx !== slideIdx || live.phase !== 'stream') return
    const { full, pos, thinking } = live
    if (pos >= full.length) {
      appendChat(slideIdx, {
        role: 'assistant',
        content: full,
        ...(thinking ? { thinking } : {}),
      })
      setAssistantLiveInternal(null)
      return
    }
    const step = Math.max(1, Math.min(4, Math.ceil(full.length / 72)))
    const id = window.setTimeout(() => {
      setAssistantLiveInternal((prev) => {
        if (!prev || prev.phase !== 'stream' || prev.slideIdx !== slideIdx) return prev
        return { ...prev, pos: Math.min(prev.full.length, prev.pos + step) }
      })
    }, 14)
    return () => clearTimeout(id)
  }, [assistantLiveInternal, slideIdx, appendChat])

  const chatComposerBusy =
    !!assistantLiveInternal &&
    assistantLiveInternal.slideIdx === slideIdx &&
    (assistantLiveInternal.phase === 'request' || assistantLiveInternal.phase === 'stream')

  const applyPptxTable = useCallback(
    async (table: string[][], headers?: string[]) => {
      if (!pptxBytes) return
      const isSwotPh = !!slideMeta.is_swot_placeholder_template
      const blob = deckBlob(pptxBytes)
      const next = isSwotPh
        ? await postFillSwotPlaceholders({ slideIdx, pptx: blob, tableData: table })
        : await postFillTable({
            slideIdx,
            pptx: blob,
            tableData: table,
            module,
            columnHeaders: headers,
          })
      setPptxBytes(next)
      markSlideFilled(slideIdx, table, headers)
    },
    [pptxBytes, slideIdx, slideMeta.is_swot_placeholder_template, module, setPptxBytes, markSlideFilled],
  )

  const handleIngest = useCallback(
    async (files: File[]) => {
      setProcessing('Ingesting files…')
      setBannerError(null)
      try {
        const data = await postDocumentIngest(files)
        setFileIds(module, data.file_ids)
        for (const err of data.errors ?? []) {
          if (err.file) {
            setBannerError(`Skipped ${err.file}: ${err.error ?? 'error'}`)
          }
        }
        if (!data.file_ids?.length) {
          setBannerError('No files were successfully ingested.')
        }
      } catch (e) {
        setBannerError(e instanceof Error ? e.message : 'Ingest failed')
      } finally {
        setProcessing(null)
      }
    },
    [module, setFileIds, setProcessing, setBannerError],
  )

  const handleFillSlide = useCallback(async () => {
    if (!pptxBytes) {
      setBannerError('Deck not loaded.')
      return
    }
    const fids = fileIds
    if (!fids.length && module !== 'Messaging Strategy') {
      setBannerError('Upload and ingest files for this module first.')
      return
    }
    setProcessing('Generating content…')
    setBannerError(null)
    try {
      const blob = deckBlob(pptxBytes)
      let table_structure
      if (slideMeta.table_structure != null) {
        table_structure = coerceTableStructure(slideMeta)
      } else {
        table_structure = await fetchTableStructure(slideIdx, blob)
      }
      const st = useAppStore.getState()
      const cowork_summary = st.coworkSummaryBySlide[slideIdx]
      const cowork_segments = st.coworkSegmentNamesBySlide[slideIdx]
      const summaryTrim = cowork_summary != null ? String(cowork_summary).trim() : ''
      const hasSegments = (cowork_segments?.length ?? 0) > 0
      const cowork_guidance =
        summaryTrim || hasSegments
          ? { summary: summaryTrim, segment_names: cowork_segments ?? [] }
          : undefined
      const fillResult = await postGenerationFill({
        slide_idx: slideIdx,
        module,
        file_ids: fids,
        table_structure,
        cowork_guidance,
      })
      const table_data = fillResult.table_data ?? []
      const colH = fillResult.column_headers ?? undefined
      if (table_data.length) {
        await applyPptxTable(table_data, colH)
      }
    } catch (e) {
      setBannerError(e instanceof Error ? e.message : 'Fill failed')
    } finally {
      setProcessing(null)
    }
  }, [
    pptxBytes,
    fileIds,
    module,
    slideIdx,
    slideMeta.table_structure,
    applyPptxTable,
    setProcessing,
    setBannerError,
  ])

  const handleSend = useCallback(
    async (text: string) => {
      const st0 = useAppStore.getState()
      const preMode = st0.chatModeBySlide[slideIdx] ?? defaultChatModeForModule(module)
      if (preMode === 'modify') {
        const cur = st0.tableDataBySlide[slideIdx]
        if (!cur?.length) {
          appendChat(slideIdx, {
            role: 'assistant',
            content: 'Please fill this slide first, then I can help you refine it.',
          })
          return
        }
      }

      appendChat(slideIdx, { role: 'user', content: text })
      const st = useAppStore.getState()
      const history = st.chatHistoryBySlide[slideIdx] ?? []
      const ts = coerceTableStructure(slideMeta)
      const m = st.chatModeBySlide[slideIdx] ?? defaultChatModeForModule(module)

      setBannerError(null)
      setAssistantLiveInternal({ slideIdx, phase: 'request' })
      try {
        if (m === 'cowork') {
          const sessionId = getOrCreateCoworkSession(slideIdx)
          const ctx =
            module === 'SWOT Analysis'
              ? (() => {
                  const c = getCsContextForSwot()
                  return {
                    summary: c.summary,
                    table: c.table,
                    headers: c.headers,
                  }
                })()
              : undefined
          const payload = await sendCoworkMessage({
            module,
            slideIdx,
            sessionId,
            fileIds: st.fileIdsByModule[module],
            tableStructure: ts,
            history,
            userMessage: text,
            allowWeb: false,
            csContext: ctx,
          })
          const draftData = payload.draft_table_data ?? []
          const draftHeaders = payload.draft_column_headers ?? []
          setCoworkDraft(
            slideIdx,
            { table_data: draftData, column_headers: draftHeaders },
            !!payload.workflow?.ready_for_ppt_fill,
          )
          const assistantReply = payload.assistant_message ?? ''
          setAssistantLiveInternal({
            slideIdx,
            phase: 'stream',
            full: assistantReply,
            pos: 0,
            thinking: payload.thinking ?? undefined,
          })
        } else {
          const curData = st.tableDataBySlide[slideIdx] ?? []
          const curHeaders = st.columnHeadersBySlide[slideIdx]
          const payload = await postGenerationChat({
            slide_idx: slideIdx,
            module,
            file_ids: st.fileIdsByModule[module],
            current_content: curData,
            table_structure: ts,
            current_column_headers: curHeaders,
            user_message: text,
            conversation_history: history.map((x) => ({ role: x.role, content: x.content })),
            mode: m,
          })
          const resolved = (payload.mode as ChatMode) ?? m
          const updated = payload.table_data ?? []
          const updatedHeaders = payload.column_headers ?? undefined
          const assistantMsg =
            payload.assistant_message ??
            (resolved === 'modify'
              ? 'Thanks for your feedback. I have updated this slide.'
              : 'Here is what I found based on your question.')
          if (resolved === 'modify' && updated.length && st.pptxBytes) {
            const isSwotPh = !!slideMeta.is_swot_placeholder_template
            const blob = deckBlob(st.pptxBytes)
            const buf = isSwotPh
              ? await postFillSwotPlaceholders({ slideIdx, pptx: blob, tableData: updated })
              : await postFillTable({
                  slideIdx,
                  pptx: blob,
                  tableData: updated,
                  module,
                  columnHeaders: updatedHeaders ?? undefined,
                })
            setPptxBytes(buf)
            markSlideFilled(slideIdx, updated, updatedHeaders ?? undefined)
          }
          setAssistantLiveInternal({
            slideIdx,
            phase: 'stream',
            full: assistantMsg,
            pos: 0,
          })
        }
      } catch (e) {
        setAssistantLiveInternal(null)
        setBannerError(e instanceof Error ? e.message : 'Chat failed')
        appendChat(slideIdx, {
          role: 'assistant',
          content:
            'Sorry, something went wrong while processing your message. Please try again.',
        })
      }
    },
    [
      slideIdx,
      module,
      slideMeta.table_structure,
      slideMeta.is_swot_placeholder_template,
      appendChat,
      getOrCreateCoworkSession,
      getCsContextForSwot,
      setCoworkDraft,
      setPptxBytes,
      markSlideFilled,
      setBannerError,
    ],
  )

  const handleEndConversation = useCallback(async () => {
    const st = useAppStore.getState()
    const sessionId = getOrCreateCoworkSession(slideIdx)
    const history = st.chatHistoryBySlide[slideIdx] ?? []
    const ctx =
      module === 'SWOT Analysis'
        ? (() => {
            const c = getCsContextForSwot()
            return { summary: c.summary, table: c.table, headers: c.headers }
          })()
        : undefined
    setProcessing('Generating summary…')
    setBannerError(null)
    try {
      const payload = await endCoworkConversation({
        module,
        slideIdx,
        sessionId,
        fileIds: st.fileIdsByModule[module],
        tableStructure: coerceTableStructure(slideMeta),
        history,
        csContext: ctx,
      })
      const summary = payload.assistant_message ?? 'Summary not available.'
      appendChat(slideIdx, { role: 'assistant', content: summary })
      const seg = payload.draft_column_headers
      setCoworkSummary(slideIdx, summary, Array.isArray(seg) ? seg : [])
    } catch (e) {
      setBannerError(e instanceof Error ? e.message : 'End conversation failed')
    } finally {
      setProcessing(null)
    }
  }, [
    slideIdx,
    module,
    slideMeta.table_structure,
    getOrCreateCoworkSession,
    getCsContextForSwot,
    appendChat,
    setCoworkSummary,
    setProcessing,
    setBannerError,
  ])

  const handleCoworkFill = useCallback(async () => {
    if (!coworkDraft?.table_data?.length || !pptxBytes) {
      setBannerError('Cowork draft is not ready yet.')
      return
    }
    setProcessing('Filling slide…')
    setBannerError(null)
    try {
      await applyPptxTable(coworkDraft.table_data, coworkDraft.column_headers)
      setCoworkDraft(slideIdx, null, false)
    } catch (e) {
      setBannerError(e instanceof Error ? e.message : 'Fill from draft failed')
    } finally {
      setProcessing(null)
    }
  }, [coworkDraft, pptxBytes, applyPptxTable, setCoworkDraft, slideIdx, setProcessing, setBannerError])

  const handleWebSearch = useCallback(
    async (q: string) => {
      setProcessing('Searching the web…')
      setBannerError(null)
      try {
        const results = await postWebSearch(q)
        setWebSearch(slideIdx, q, results)
      } catch (e) {
        setBannerError(e instanceof Error ? e.message : 'Search failed')
      } finally {
        setProcessing(null)
      }
    },
    [slideIdx, setWebSearch, setProcessing, setBannerError],
  )

  const fillReason =
    !fileIds.length && module !== 'Messaging Strategy'
      ? 'Ingest at least one document to enable fill for this module.'
      : undefined

  return (
    <div className="grid gap-8 lg:grid-cols-2 lg:gap-10 lg:items-start">
      <div className="order-2 min-h-0 lg:order-1 lg:sticky lg:top-6">
        <ChatPanel
          module={module}
          slideMeta={slideMeta}
          messages={messages}
          mode={mode}
          onModeChange={(chatMode) => setChatMode(slideIdx, chatMode)}
          onSend={(txt) => void handleSend(txt)}
          onClear={() => clearSlideChat(slideIdx)}
          onEndConversation={() => void handleEndConversation()}
          coworkReady={coworkReady}
          onCoworkFill={() => void handleCoworkFill()}
          disabled={processing || chatComposerBusy}
          assistantLive={toPanelAssistantLive(slideIdx, assistantLiveInternal)}
        />
      </div>

      <div className="order-1 space-y-2 lg:order-2">
        <SlideCanvas
          module={module}
          slideMeta={slideMeta}
          slideOrdinal={slideOrdinal}
          filled={filled}
          tableData={tableData}
          columnHeaders={columnHeaders}
          pptxBytes={pptxBytes}
        />
        <ControlsPanel
          fileCount={fileIds.length}
          onIngest={(fs) => void handleIngest(fs)}
          onFill={() => void handleFillSlide()}
          fillDisabledReason={fillReason}
          disabled={processing}
        />
        <WebSearchPanel
          query={wsQuery}
          results={wsResults}
          onSearch={(q) => void handleWebSearch(q)}
          onClear={() => clearWebSearch(slideIdx)}
          disabled={processing}
        />
      </div>
    </div>
  )
}
