import { useEffect, useRef } from 'react'

import type { ChatAssistantLive, ChatMessage, ChatMode, ModuleName, SlideMeta } from '@/types'

import { ChatComposer } from '@/features/chat/ChatComposer'
import { ChatMessageList } from '@/features/chat/ChatMessageList'

export function ChatPanel({
  module,
  slideMeta,
  messages,
  mode,
  onModeChange,
  onSend,
  onClear,
  onEndConversation,
  coworkReady,
  onCoworkFill,
  disabled,
  assistantLive,
}: {
  module: ModuleName
  slideMeta: SlideMeta
  messages: ChatMessage[]
  mode: ChatMode
  onModeChange: (m: ChatMode) => void
  onSend: (text: string) => void
  onClear: () => void
  onEndConversation: () => void
  coworkReady: boolean
  onCoworkFill: () => void
  disabled: boolean
  assistantLive?: ChatAssistantLive
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: 'auto' })
  }, [messages, assistantLive])

  return (
    <div
      key={slideMeta.idx}
      className="flex h-[min(34rem,calc(100dvh-10rem))] w-full flex-col overflow-hidden rounded-2xl border border-neutral-200/80 bg-white shadow-[0_2px_20px_-8px_rgba(0,0,0,0.12)]"
    >
      <div className="shrink-0 border-b border-neutral-100 px-4 py-3.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-neutral-500">
          Copilot
        </h2>
        <p className="text-xs text-neutral-400">Helping your business plan take shape</p>
      </div>
      <div
        ref={scrollRef}
        className="if-chat-messages min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-3 py-3 [scrollbar-gutter:stable] md:px-4"
      >
        <ChatMessageList
          messages={messages}
          module={module}
          mode={mode}
          assistantLive={assistantLive ?? null}
        />
      </div>
      <ChatComposer
        module={module}
        mode={mode}
        onModeChange={onModeChange}
        onSend={onSend}
        onClear={onClear}
        onEndConversation={onEndConversation}
        coworkReady={coworkReady}
        onCoworkFill={onCoworkFill}
        disabled={disabled}
      />
    </div>
  )
}
