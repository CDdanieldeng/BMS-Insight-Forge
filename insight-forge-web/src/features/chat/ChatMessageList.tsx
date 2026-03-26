import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { ChatAssistantLive, ChatMessage, ChatMode, ModuleName } from '@/types'

const iconStroke = {
  xmlns: 'http://www.w3.org/2000/svg',
  fill: 'none',
  viewBox: '0 0 24 24',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

function BotIcon({ className }: { className?: string }) {
  return (
    <svg {...iconStroke} className={className} aria-hidden>
      <path d="M12 4v2" />
      <rect x="5.5" y="8.5" width="13" height="11" rx="2.5" />
      <circle cx="9.25" cy="14" r="1" fill="currentColor" stroke="none" />
      <circle cx="14.75" cy="14" r="1" fill="currentColor" stroke="none" />
      <path d="M9.5 17.25h5" />
    </svg>
  )
}

function UserIcon({ className }: { className?: string }) {
  return (
    <svg {...iconStroke} className={className} aria-hidden>
      <circle cx="12" cy="8.5" r="3.25" />
      <path d="M6.75 19.5v-.5a3.75 3.75 0 0 1 3.75-3.75h4a3.75 3.75 0 0 1 3.75 3.75v.5" />
    </svg>
  )
}

function CoworkPreamble({ module, mode }: { module: ModuleName; mode: ChatMode }) {
  if (mode !== 'cowork') return null
  if (module === 'Customer Segmentation') {
    return (
      <AssistantBubble
        content={
          "You're in **Customer Segmentation**. Let's align on the guideline for segmentation — what's the **main commercial goal** for this effort?"
        }
      />
    )
  }
  if (module === 'SWOT Analysis') {
    return (
      <AssistantBubble
        content={
          "You're in **SWOT Analysis**. Is there anything you'd like me to emphasise when we shape this analysis?"
        }
      />
    )
  }
  return null
}

function AssistantBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-start items-end gap-2">
      <BotIcon className="size-10 shrink-0 text-neutral-400" />
      <div className="max-w-[min(100%,32rem)] rounded-2xl rounded-bl-md border border-neutral-200/80 bg-white px-3.5 py-2.5 text-[0.8125rem] leading-relaxed text-neutral-800 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
        <div className="if-md max-w-none">
          <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
        </div>
      </div>
    </div>
  )
}

function AssistantTypingBubble() {
  return (
    <div className="flex items-end justify-start gap-2">
      <BotIcon className="size-10 shrink-0 text-neutral-400" />
      <div className="max-w-[min(100%,32rem)] rounded-2xl rounded-bl-md border border-neutral-200/80 bg-white px-3.5 py-3 text-[0.8125rem] leading-relaxed text-neutral-800 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1">
            <span className="if-pulse-dot size-1.5 rounded-full bg-neutral-400" />
            <span
              className="if-pulse-dot size-1.5 rounded-full bg-neutral-400"
              style={{ animationDelay: '0.2s' }}
            />
            <span
              className="if-pulse-dot size-1.5 rounded-full bg-neutral-400"
              style={{ animationDelay: '0.4s' }}
            />
          </span>
          <span className="text-xs text-neutral-400">Copilot is working…</span>
        </div>
      </div>
    </div>
  )
}

function AssistantStreamingBubble({ text }: { text: string }) {
  return (
    <div className="flex items-end justify-start gap-2">
      <BotIcon className="size-10 shrink-0 text-neutral-400" />
      <div className="max-w-[min(100%,32rem)] rounded-2xl rounded-bl-md border border-neutral-200/80 bg-white px-3.5 py-2.5 text-[0.8125rem] leading-relaxed text-neutral-800 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
        <p className="whitespace-pre-wrap break-words">
          {text}
          <span className="ml-0.5 inline-block h-3 w-px animate-pulse bg-neutral-400 align-text-bottom" />
        </p>
      </div>
    </div>
  )
}

export function ChatMessageList({
  messages,
  module,
  mode,
  assistantLive,
}: {
  messages: ChatMessage[]
  module: ModuleName
  mode: ChatMode
  assistantLive?: ChatAssistantLive
}) {
  const showPreamble =
    messages.length === 0 && (module === 'Customer Segmentation' || module === 'SWOT Analysis')

  return (
    <div className="flex flex-col gap-3 pr-1">
      {showPreamble ? <CoworkPreamble module={module} mode={mode} /> : null}
      {!showPreamble && messages.length === 0 ? (
        <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50/50 px-4 py-10 text-center text-xs text-neutral-400">
          Choose co-work for guided completion, or fill the slide and use modify to refine.
        </div>
      ) : null}
      {messages.map((msg, i) => {
        const isUser = msg.role === 'user'
        return (
          <div
            key={i}
            className={`flex items-end gap-2 ${isUser ? 'justify-end' : 'justify-start'}`}
          >
            {!isUser ? (
              <BotIcon className="size-10 shrink-0 text-neutral-400" />
            ) : null}
            <div
              className={`max-w-[min(100%,32rem)] rounded-2xl px-3.5 py-2.5 text-[0.8125rem] leading-relaxed shadow-[0_1px_2px_rgba(0,0,0,0.04)] ${
                isUser
                  ? 'rounded-br-md border border-neutral-200/60 bg-neutral-900 text-neutral-50'
                  : 'rounded-bl-md border border-neutral-200/80 bg-white text-neutral-800'
              }`}
            >
              {!isUser && msg.thinking ? (
                <details className="mb-2 rounded-lg border border-neutral-200/80 bg-neutral-50 text-[11px] text-neutral-600">
                  <summary className="cursor-pointer select-none px-2 py-1.5 font-medium text-neutral-500">
                    Thinking
                  </summary>
                  <pre className="max-h-40 overflow-auto whitespace-pre-wrap border-t border-neutral-200/60 p-2 font-mono text-[11px] leading-relaxed text-neutral-600">
                    {msg.thinking}
                  </pre>
                </details>
              ) : null}
              {isUser ? (
                <p className="whitespace-pre-wrap break-words">{msg.content}</p>
              ) : (
                <div className="if-md max-w-none">
                  <Markdown remarkPlugins={[remarkGfm]}>{msg.content}</Markdown>
                </div>
              )}
            </div>
            {isUser ? (
              <UserIcon className="size-10 shrink-0 text-neutral-400" />
            ) : null}
          </div>
        )
      })}
      {assistantLive === 'typing' ? <AssistantTypingBubble /> : null}
      {assistantLive && typeof assistantLive === 'object' ? (
        <AssistantStreamingBubble text={assistantLive.partialText} />
      ) : null}
    </div>
  )
}
