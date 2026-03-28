import { useEffect, useRef, useState } from 'react'

import { transcribeVoiceStream } from '@/api/insightForgeApi'
import type { ModuleName, WebSearchResult } from '@/types'
import { getVoiceLanguage } from '@/utils/env'

export type ChatComposerVariant = 'coworkLocked' | 'modifyLocked'

/** Compact ingest / web controls for the module landing copilot */
export type ChatLandingToolbar = {
  fileCount: number
  onIngest: (files: File[]) => void
  wsQuery: string
  wsResults: WebSearchResult[]
  onWebSearch: (q: string) => void
  onWebClear: () => void
}

function pickRecorderMime(): string | undefined {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus',
  ]
  for (const t of candidates) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(t)) return t
  }
  return undefined
}

function MicIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d="M12 19v3M8 22h8M12 15a4 4 0 0 0 4-4V6a4 4 0 0 0-8 0v5a4 4 0 0 0 4 4Z" />
      <path d="M19 11a7 7 0 0 1-14 0" />
    </svg>
  )
}

export function ChatComposer({
  module,
  variant = 'modifyLocked',
  onSend,
  onClear,
  onEndConversation,
  coworkReady,
  onCoworkFill,
  disabled,
  landingToolbar,
}: {
  module: ModuleName
  variant?: ChatComposerVariant
  onSend: (text: string) => void
  onClear: () => void
  onEndConversation: () => void
  coworkReady: boolean
  onCoworkFill: () => void
  disabled: boolean
  landingToolbar?: ChatLandingToolbar
}) {
  const [text, setText] = useState('')
  const [voiceStatus, setVoiceStatus] = useState<string | null>(null)
  const [isRecording, setIsRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [webOpen, setWebOpen] = useState(false)
  const [webLocalQ, setWebLocalQ] = useState(landingToolbar?.wsQuery ?? '')
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setWebLocalQ(landingToolbar?.wsQuery ?? '')
  }, [landingToolbar?.wsQuery])

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = null
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        try {
          mediaRecorderRef.current.stop()
        } catch {
          /* ignore */
        }
      }
      mediaRecorderRef.current = null
    }
  }, [])

  const isCoworkLanding = variant === 'coworkLocked'

  const placeholder =
    isCoworkLanding && module === 'Customer Segmentation'
      ? 'Collaborate step by step on segmentation…'
      : isCoworkLanding && module === 'SWOT Analysis'
        ? 'Align on emphasis and context for SWOT…'
        : 'Ask the model to refine this slide…'

  async function transcribeBuffer(buf: ArrayBuffer) {
    setTranscribing(true)
    setVoiceStatus('Transcribing…')
    try {
      let finalT = ''
      await transcribeVoiceStream(buf, getVoiceLanguage(), (ev) => {
        if (ev.type === 'partial' || ev.type === 'final_segment') {
          if (ev.transcript) setVoiceStatus(ev.transcript.slice(0, 120))
        }
        if (ev.type === 'error') {
          setVoiceStatus(ev.message ?? 'Voice error')
        }
        if (ev.type === 'final' && ev.transcript) {
          finalT = ev.transcript
        }
      })
      if (finalT) setText((t) => (t ? `${t}\n${finalT}` : finalT))
      setVoiceStatus(null)
    } catch (e) {
      setVoiceStatus(e instanceof Error ? e.message : 'Voice failed')
    } finally {
      setTranscribing(false)
    }
  }

  async function toggleVoiceCapture() {
    if (disabled || transcribing) return
    if (isRecording) {
      mediaRecorderRef.current?.stop()
      return
    }
    if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setVoiceStatus('Microphone not supported')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const mime = pickRecorderMime()
      const rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream)
      chunksRef.current = []
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        streamRef.current = null
        mediaRecorderRef.current = null
        setIsRecording(false)
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || 'audio/webm' })
        chunksRef.current = []
        if (blob.size === 0) {
          setVoiceStatus(null)
          return
        }
        void blob.arrayBuffer().then((buf) => void transcribeBuffer(buf))
      }
      rec.onerror = () => {
        stream.getTracks().forEach((t) => t.stop())
        streamRef.current = null
        mediaRecorderRef.current = null
        setIsRecording(false)
        setVoiceStatus('Recording error')
      }
      mediaRecorderRef.current = rec
      rec.start()
      setIsRecording(true)
      setVoiceStatus('Listening…')
    } catch (e) {
      setVoiceStatus(e instanceof Error ? e.message : 'Mic permission denied')
    }
  }

  return (
    <div className="border-t border-neutral-100 bg-neutral-50/30 px-3 py-3 md:px-4">
      <div className="flex flex-wrap items-stretch gap-2">
        <textarea
          rows={2}
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          placeholder={placeholder}
          className="min-h-[2.75rem] min-w-[12rem] flex-1 resize-y rounded-xl border border-neutral-200 bg-white px-3 py-2 text-xs leading-normal text-neutral-800 shadow-sm placeholder:text-neutral-400 focus:border-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-200"
        />
        <div className="flex flex-col justify-center gap-1 self-center">
          <button
            type="button"
            disabled={transcribing || (disabled && !isRecording)}
            title={
              transcribing
                ? 'Transcribing…'
                : isRecording
                  ? 'Stop and send for transcription'
                  : 'Speak — partial text streams while transcribing'
            }
            onClick={() => void toggleVoiceCapture()}
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border shadow-sm disabled:cursor-not-allowed disabled:opacity-40 ${
              isRecording
                ? 'border-red-300 bg-red-50 text-red-600 ring-2 ring-red-200'
                : 'border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-50'
            }`}
          >
            <MicIcon className="size-4" />
          </button>
          {voiceStatus ? (
            <span className="max-w-[8rem] truncate text-[10px] text-neutral-400">{voiceStatus}</span>
          ) : null}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            const t = text.trim()
            if (!t) return
            onSend(t)
            setText('')
          }}
          className="rounded-lg bg-neutral-900 px-4 py-2 text-xs font-medium text-white shadow-sm hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Send
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={onClear}
          className="rounded-lg border border-neutral-200 bg-white px-4 py-2 text-xs font-medium text-neutral-700 shadow-sm hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Clear
        </button>
        {isCoworkLanding ? (
          <button
            type="button"
            disabled={disabled}
            onClick={onEndConversation}
            className="rounded-lg border border-neutral-200 bg-white px-4 py-2 text-xs font-medium text-neutral-700 shadow-sm hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            End conversation
          </button>
        ) : null}
        {landingToolbar ? (
          <>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pptx,.docx,.doc,.md,.pdf"
              className="hidden"
              disabled={disabled}
              onChange={(e) => {
                const fs = [...(e.target.files ?? [])]
                if (fs.length) landingToolbar.onIngest(fs)
                e.target.value = ''
              }}
            />
            <button
              type="button"
              disabled={disabled}
              title="Upload module files (PPTX, DOCX, DOC, MD, PDF). Replaces this module’s retrieval set."
              onClick={() => fileInputRef.current?.click()}
              className="rounded-lg border border-neutral-200 bg-white px-2.5 py-2 text-[11px] font-medium text-neutral-700 shadow-sm hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Upload{landingToolbar.fileCount ? ` · ${landingToolbar.fileCount}` : ''}
            </button>
            <button
              type="button"
              disabled={disabled}
              title="Search the web for context"
              onClick={() => setWebOpen((o) => !o)}
              className={`rounded-lg border px-2.5 py-2 text-[11px] font-medium shadow-sm disabled:cursor-not-allowed disabled:opacity-40 ${
                webOpen
                  ? 'border-neutral-800 bg-neutral-900 text-white'
                  : 'border-neutral-200 bg-white text-neutral-700 hover:bg-neutral-50'
              }`}
            >
              Web
            </button>
          </>
        ) : null}
      </div>

      {landingToolbar && webOpen ? (
        <div className="mt-2 max-h-52 overflow-y-auto rounded-xl border border-neutral-200/80 bg-white px-2.5 py-2 shadow-sm">
          <div className="flex gap-1.5">
            <input
              value={webLocalQ}
              onChange={(e) => setWebLocalQ(e.target.value)}
              disabled={disabled}
              placeholder="Search the web…"
              autoComplete="off"
              className="min-w-0 flex-1 rounded-lg border border-neutral-200 bg-white px-2 py-1.5 text-[11px] text-neutral-800 placeholder:text-neutral-400 focus:border-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-200"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const q = webLocalQ.trim()
                  if (q) landingToolbar.onWebSearch(q)
                }
              }}
            />
            <button
              type="button"
              disabled={disabled}
              onClick={() => {
                const q = webLocalQ.trim()
                if (q) landingToolbar.onWebSearch(q)
              }}
              className="shrink-0 rounded-lg bg-neutral-900 px-3 py-1.5 text-[11px] font-medium text-white hover:bg-neutral-800 disabled:opacity-40"
            >
              Go
            </button>
          </div>
          {landingToolbar.wsResults.length > 0 ? (
            <div className="mt-2 space-y-1.5 border-t border-neutral-100 pt-2">
              <div className="flex items-center justify-between gap-2">
                <p className="truncate text-[10px] text-neutral-500">
                  {landingToolbar.wsQuery ? (
                    <>
                      Results for <span className="text-neutral-700">{landingToolbar.wsQuery}</span>
                    </>
                  ) : (
                    'Results'
                  )}
                </p>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => landingToolbar.onWebClear()}
                  className="text-[10px] text-neutral-400 hover:text-neutral-700"
                >
                  Clear
                </button>
              </div>
              <ul className="space-y-1">
                {landingToolbar.wsResults.slice(0, 4).map((r, i) => (
                  <li key={i}>
                    <details className="group rounded-md border border-neutral-200/80 bg-neutral-50/50">
                      <summary className="cursor-pointer list-none px-2 py-1.5 text-[10px] font-medium text-neutral-800 marker:content-none [&::-webkit-details-marker]:hidden">
                        <span className="mr-0.5 text-neutral-300 group-open:rotate-90">▸</span>
                        {r.title || `Result ${i + 1}`}
                      </summary>
                      <div className="border-t border-neutral-100 px-2 py-1.5">
                        {r.url ? (
                          <a
                            href={r.url}
                            target="_blank"
                            rel="noreferrer"
                            className="mb-0.5 block break-all text-[10px] text-neutral-500 underline-offset-2 hover:underline"
                          >
                            {r.url}
                          </a>
                        ) : null}
                        <p className="whitespace-pre-wrap break-words text-[10px] leading-relaxed text-neutral-600">
                          {r.content}
                        </p>
                      </div>
                    </details>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      {isCoworkLanding && coworkReady ? (
        <button
          type="button"
          disabled={disabled}
          onClick={onCoworkFill}
          className="mt-3 w-full rounded-xl bg-neutral-900 py-2.5 text-xs font-medium text-white shadow-sm hover:bg-neutral-800 disabled:opacity-40"
        >
          Ready to fill the template?
        </button>
      ) : null}
    </div>
  )
}
