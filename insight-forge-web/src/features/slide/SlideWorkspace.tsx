import type { ModuleName, SlideMeta } from '@/types'

import { useCopilotForSlide } from '@/features/chat/useCopilotForSlide'
import { ChatPanel } from '@/features/chat/ChatPanel'
import { ControlsPanel } from '@/features/controls/ControlsPanel'
import { SlideCanvas } from '@/features/slide/SlideCanvas'
import { WebSearchPanel } from '@/features/web/WebSearchPanel'
import { useAppStore } from '@/store/appStore'

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
  const filled = useAppStore((s) => s.filledSlides.includes(slideIdx))

  const {
    processing,
    pptxBytes,
    fileIds,
    tableData,
    columnHeaders,
    messages,
    coworkReady,
    wsQuery,
    wsResults,
    chatComposerBusy,
    fillReason,
    modeForUi,
    assistantLive,
    handleIngest,
    handleFillSlide,
    handleSend,
    handleEndConversation,
    handleCoworkFill,
    handleWebSearch,
    clearSlideChat,
    clearWebSearch,
  } = useCopilotForSlide(module, slideMeta, 'modify')

  return (
    <div className="grid gap-8 lg:grid-cols-2 lg:gap-10 lg:items-start">
      <div className="order-2 min-h-0 lg:order-1 lg:sticky lg:top-6">
        <ChatPanel
          module={module}
          slideMeta={slideMeta}
          messages={messages}
          mode={modeForUi}
          composerVariant="modifyLocked"
          onSend={(txt) => void handleSend(txt)}
          onClear={() => clearSlideChat()}
          onEndConversation={() => void handleEndConversation()}
          coworkReady={coworkReady}
          onCoworkFill={() => void handleCoworkFill()}
          disabled={processing || chatComposerBusy}
          assistantLive={assistantLive}
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
          onClear={() => clearWebSearch()}
          disabled={processing}
        />
      </div>
    </div>
  )
}
