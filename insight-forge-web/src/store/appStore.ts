import { create } from 'zustand'

import type {
  ChatMessage,
  ChatMode,
  CoworkDraft,
  ModuleName,
  SlideMeta,
  WebSearchResult,
} from '@/types'
function emptyPageMap(): Record<ModuleName, number> {
  return {
    'Customer Segmentation': 0,
    'SWOT Analysis': 0,
    'Messaging Strategy': 0,
  }
}

function emptyFileIds(): Record<ModuleName, string[]> {
  return {
    'Customer Segmentation': [],
    'SWOT Analysis': [],
    'Messaging Strategy': [],
  }
}

function omitKey<T extends Record<string, unknown>>(obj: T, key: string): T {
  const { [key]: _, ...rest } = obj
  return rest as T
}

export interface AppStore {
  started: boolean
  selectedProduct: string
  /** Optional context entered on the welcome page */
  productDescription: string
  slideInfo: SlideMeta[]
  activeModule: ModuleName
  currentPageByModule: Record<ModuleName, number>
  pptxBytes: ArrayBuffer | null
  fileIdsByModule: Record<ModuleName, string[]>
  filledSlides: number[]
  tableDataBySlide: Record<number, string[][]>
  columnHeadersBySlide: Record<number, string[]>
  chatHistoryBySlide: Record<number, ChatMessage[]>
  chatModeBySlide: Record<number, ChatMode>
  coworkSessionIdBySlide: Record<number, string>
  coworkReadyBySlide: Record<number, boolean>
  coworkDraftBySlide: Record<number, CoworkDraft>
  coworkSummaryBySlide: Record<number, string>
  coworkSegmentNamesBySlide: Record<number, string[]>
  webSearchResultsBySlide: Record<number, WebSearchResult[]>
  webSearchQueryBySlide: Record<number, string>
  completionCelebrated: boolean
  processingMessage: string | null
  bannerError: string | null

  setProcessing: (message: string | null) => void
  setBannerError: (message: string | null) => void
  resetWorkspace: () => void

  setStarted: (v: boolean) => void
  setSelectedProduct: (p: string) => void
  setProductDescription: (d: string) => void
  setSlideInfoAndDeck: (slideInfo: SlideMeta[], pptx: ArrayBuffer) => void
  setActiveModule: (m: ModuleName) => void
  setCurrentPage: (module: ModuleName, page: number) => void
  bumpCurrentPage: (module: ModuleName, delta: number) => void

  setFileIdsForModule: (module: ModuleName, ids: string[]) => void
  setPptxBytes: (b: ArrayBuffer) => void
  markSlideFilled: (slideIdx: number, table: string[][], headers?: string[]) => void
  setTableDraftForSlide: (slideIdx: number, table: string[][], headers?: string[]) => void

  appendChatMessage: (slideIdx: number, msg: ChatMessage) => void
  setChatHistory: (slideIdx: number, messages: ChatMessage[]) => void
  setChatMode: (slideIdx: number, mode: ChatMode) => void
  clearSlideChat: (slideIdx: number) => void

  getOrCreateCoworkSession: (slideIdx: number) => string
  setCoworkDraft: (slideIdx: number, draft: CoworkDraft | null, ready: boolean) => void
  setCoworkSummary: (slideIdx: number, summary: string, segmentNames: string[]) => void

  setWebSearch: (slideIdx: number, query: string, results: WebSearchResult[]) => void
  clearWebSearch: (slideIdx: number) => void

  setCompletionCelebrated: (v: boolean) => void

  /** SWOT: first CS slide summary + table */
  getCsContextForSwot: () => {
    summary: string | null
    table: string[][] | null
    headers: string[] | null
  }

  isSlideFilled: (slideIdx: number) => boolean
}

const initial = (): Omit<
  AppStore,
  | keyof Pick<
      AppStore,
      | 'setProcessing'
      | 'setBannerError'
      | 'resetWorkspace'
      | 'setStarted'
      | 'setSelectedProduct'
      | 'setProductDescription'
      | 'setSlideInfoAndDeck'
      | 'setActiveModule'
      | 'setCurrentPage'
      | 'bumpCurrentPage'
      | 'setFileIdsForModule'
      | 'setPptxBytes'
      | 'markSlideFilled'
      | 'setTableDraftForSlide'
      | 'appendChatMessage'
      | 'setChatHistory'
      | 'setChatMode'
      | 'clearSlideChat'
      | 'getOrCreateCoworkSession'
      | 'setCoworkDraft'
      | 'setCoworkSummary'
      | 'setWebSearch'
      | 'clearWebSearch'
      | 'setCompletionCelebrated'
      | 'getCsContextForSwot'
      | 'isSlideFilled'
    >
> => ({
  started: false,
  selectedProduct: '',
  productDescription: '',
  slideInfo: [],
  activeModule: 'Customer Segmentation',
  currentPageByModule: emptyPageMap(),
  pptxBytes: null,
  fileIdsByModule: emptyFileIds(),
  filledSlides: [],
  tableDataBySlide: {},
  columnHeadersBySlide: {},
  chatHistoryBySlide: {},
  chatModeBySlide: {},
  coworkSessionIdBySlide: {},
  coworkReadyBySlide: {},
  coworkDraftBySlide: {},
  coworkSummaryBySlide: {},
  coworkSegmentNamesBySlide: {},
  webSearchResultsBySlide: {},
  webSearchQueryBySlide: {},
  completionCelebrated: false,
  processingMessage: null,
  bannerError: null,
})

export const useAppStore = create<AppStore>((set, get) => ({
  ...initial(),

  setProcessing: (message) => set({ processingMessage: message }),
  setBannerError: (message) => set({ bannerError: message }),

  resetWorkspace: () =>
    set({
      ...initial(),
      selectedProduct: get().selectedProduct,
      productDescription: get().productDescription,
    }),

  setStarted: (v) => set({ started: v }),
  setSelectedProduct: (p) => set({ selectedProduct: p }),
  setProductDescription: (d) => set({ productDescription: d }),

  setSlideInfoAndDeck: (slideInfo, pptx) =>
    set({
      slideInfo,
      pptxBytes: pptx,
      filledSlides: [],
      tableDataBySlide: {},
      columnHeadersBySlide: {},
      chatHistoryBySlide: {},
      chatModeBySlide: {},
      coworkSessionIdBySlide: {},
      coworkReadyBySlide: {},
      coworkDraftBySlide: {},
      coworkSummaryBySlide: {},
      coworkSegmentNamesBySlide: {},
      webSearchResultsBySlide: {},
      webSearchQueryBySlide: {},
      currentPageByModule: emptyPageMap(),
      completionCelebrated: false,
    }),

  setActiveModule: (m) => set({ activeModule: m }),

  setCurrentPage: (module, page) =>
    set((s) => ({
      currentPageByModule: { ...s.currentPageByModule, [module]: page },
    })),

  bumpCurrentPage: (module, delta) =>
    set((s) => {
      const cur = s.currentPageByModule[module] ?? 0
      return {
        currentPageByModule: { ...s.currentPageByModule, [module]: cur + delta },
      }
    }),

  setFileIdsForModule: (module, ids) =>
    set((s) => ({
      fileIdsByModule: { ...s.fileIdsByModule, [module]: ids },
    })),

  setPptxBytes: (b) => set({ pptxBytes: b }),

  markSlideFilled: (slideIdx, table, headers) =>
    set((s) => {
      const filled = s.filledSlides.includes(slideIdx)
        ? s.filledSlides
        : [...s.filledSlides, slideIdx]
      const nextHeaders = { ...s.columnHeadersBySlide }
      if (headers?.length) nextHeaders[slideIdx] = headers
      return {
        filledSlides: filled,
        tableDataBySlide: { ...s.tableDataBySlide, [slideIdx]: table },
        columnHeadersBySlide: nextHeaders,
        coworkReadyBySlide: { ...s.coworkReadyBySlide, [slideIdx]: false },
      }
    }),

  setTableDraftForSlide: (slideIdx, table, headers) =>
    set((s) => {
      const nextHeaders = { ...s.columnHeadersBySlide }
      if (headers?.length) nextHeaders[slideIdx] = headers
      return {
        tableDataBySlide: { ...s.tableDataBySlide, [slideIdx]: table },
        columnHeadersBySlide: nextHeaders,
      }
    }),

  appendChatMessage: (slideIdx, msg) =>
    set((s) => {
      const prev = s.chatHistoryBySlide[slideIdx] ?? []
      return {
        chatHistoryBySlide: { ...s.chatHistoryBySlide, [slideIdx]: [...prev, msg] },
      }
    }),

  setChatHistory: (slideIdx, messages) =>
    set((s) => ({
      chatHistoryBySlide: { ...s.chatHistoryBySlide, [slideIdx]: messages },
    })),

  setChatMode: (slideIdx, mode) =>
    set((s) => ({
      chatModeBySlide: { ...s.chatModeBySlide, [slideIdx]: mode },
    })),

  clearSlideChat: (slideIdx) =>
    set((s) => ({
      chatHistoryBySlide: { ...s.chatHistoryBySlide, [slideIdx]: [] },
      coworkSessionIdBySlide: omitKey(s.coworkSessionIdBySlide, String(slideIdx)),
      coworkReadyBySlide: omitKey(s.coworkReadyBySlide, String(slideIdx)),
      coworkDraftBySlide: omitKey(s.coworkDraftBySlide, String(slideIdx)),
    })),

  getOrCreateCoworkSession: (slideIdx) => {
    const existing = get().coworkSessionIdBySlide[slideIdx]
    if (existing) return existing
    const id = crypto.randomUUID()
    set((s) => ({
      coworkSessionIdBySlide: { ...s.coworkSessionIdBySlide, [slideIdx]: id },
    }))
    return id
  },

  setCoworkDraft: (slideIdx, draft, ready) =>
    set((s) => {
      if (!draft) {
        return {
          coworkDraftBySlide: omitKey(s.coworkDraftBySlide, String(slideIdx)),
          coworkReadyBySlide: { ...s.coworkReadyBySlide, [slideIdx]: false },
        }
      }
      return {
        coworkDraftBySlide: { ...s.coworkDraftBySlide, [slideIdx]: draft },
        coworkReadyBySlide: { ...s.coworkReadyBySlide, [slideIdx]: ready },
      }
    }),

  setCoworkSummary: (slideIdx, summary, segmentNames) =>
    set((s) => ({
      coworkSummaryBySlide: { ...s.coworkSummaryBySlide, [slideIdx]: summary },
      coworkSegmentNamesBySlide: {
        ...s.coworkSegmentNamesBySlide,
        [slideIdx]: segmentNames,
      },
    })),

  setWebSearch: (slideIdx, query, results) =>
    set((s) => ({
      webSearchQueryBySlide: { ...s.webSearchQueryBySlide, [slideIdx]: query },
      webSearchResultsBySlide: { ...s.webSearchResultsBySlide, [slideIdx]: results },
    })),

  clearWebSearch: (slideIdx) =>
    set((s) => ({
      webSearchQueryBySlide: omitKey(s.webSearchQueryBySlide, String(slideIdx)),
      webSearchResultsBySlide: omitKey(s.webSearchResultsBySlide, String(slideIdx)),
    })),

  setCompletionCelebrated: (v) => set({ completionCelebrated: v }),

  getCsContextForSwot: () => {
    const s = get()
    const csSlides = s.slideInfo.filter(
      (x) => x.is_fillable && x.module === 'Customer Segmentation',
    )
    if (!csSlides.length) {
      return { summary: null, table: null, headers: null }
    }
    const csIdx = csSlides[0]!.idx
    const summary = s.coworkSummaryBySlide[csIdx] ?? null
    const table = s.tableDataBySlide[csIdx] ?? null
    const headers = s.columnHeadersBySlide[csIdx] ?? null
    return {
      summary,
      table: table?.length ? table : null,
      headers: headers?.length ? headers : null,
    }
  },

  isSlideFilled: (slideIdx) => get().filledSlides.includes(slideIdx),
}))

export function defaultChatModeForModule(module: ModuleName): ChatMode {
  return module === 'Messaging Strategy' ? 'modify' : 'cowork'
}
