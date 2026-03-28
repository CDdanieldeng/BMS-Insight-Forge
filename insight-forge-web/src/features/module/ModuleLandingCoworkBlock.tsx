import type { ModuleName, SlideMeta } from '@/types'

import { ChatPanel } from '@/features/chat/ChatPanel'
import { useCopilotForSlide } from '@/features/chat/useCopilotForSlide'

export function ModuleLandingCoworkBlock({
  module,
  slideMeta,
}: {
  module: ModuleName
  slideMeta: SlideMeta
}) {
  const {
    processing,
    fileIds,
    coworkReady,
    wsQuery,
    wsResults,
    chatComposerBusy,
    modeForUi,
    assistantLive,
    handleIngest,
    handleSend,
    handleEndConversation,
    handleCoworkFill,
    handleWebSearch,
    clearSlideChat,
    clearWebSearch,
    messages,
  } = useCopilotForSlide(module, slideMeta, 'cowork')

  return (
    <div className="mt-10 space-y-6">
      <div className="rounded-2xl border border-neutral-200/80 bg-neutral-50/40 px-5 py-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-neutral-500">
          Before you open slides
        </p>
        <p className="mt-1 text-xs leading-relaxed text-neutral-600">
          Use <span className="text-neutral-800">Upload</span> and <span className="text-neutral-800">Web</span>{' '}
          in the copilot below, then chat in <span className="text-neutral-800">Co-work</span>. Open the slide
          workspace with <span className="text-neutral-800">Next</span> to generate and refine content.
        </p>
      </div>
      <ChatPanel
        module={module}
        slideMeta={slideMeta}
        messages={messages}
        mode={modeForUi}
        composerVariant="coworkLocked"
        onSend={(txt) => void handleSend(txt)}
        onClear={() => clearSlideChat()}
        onEndConversation={() => void handleEndConversation()}
        coworkReady={coworkReady}
        onCoworkFill={() => void handleCoworkFill()}
        disabled={processing || chatComposerBusy}
        assistantLive={assistantLive}
        landingToolbar={{
          fileCount: fileIds.length,
          onIngest: (fs) => void handleIngest(fs),
          wsQuery,
          wsResults,
          onWebSearch: (q) => void handleWebSearch(q),
          onWebClear: () => clearWebSearch(),
        }}
      />
    </div>
  )
}
