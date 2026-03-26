import { useEffect, useRef, useState } from 'react'

import type { ChatMode, ModuleName } from '@/types'
import { getVoiceLanguage } from '@/utils/env'
import { transcribeVoiceStream } from '@/api/insightForgeApi'

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
  mode,
  onModeChange,
  onSend,
  onClear,
  onEndConversation,
  coworkReady,
  onCoworkFill,
  disabled,
}: {
  module: ModuleName
  mode: ChatMode
  onModeChange: (m: ChatMode) => void
  onSend: (text: string) => void
  onClear: () => void
  onEndConversation: () => void
  coworkReady: boolean
  onCoworkFill: () => void
  disabled: boolean
}) {
  const [text, setText] = useState('')
  const [voiceStatus, setVoiceStatus] = useState<string | null>(null)
  const [isRecording, setIsRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)

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

  const showCowork = module === 'Customer Segmentation' || module === 'SWOT Analysis'

  const placeholder =
    mode === 'cowork' && module === 'Customer Segmentation'
      ? 'Collaborate step by step on segmentation…'
      : mode === 'cowork' && module === 'SWOT Analysis'
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
        {showCowork ? (
          <div className="flex min-h-[2.75rem] shrink-0">
            <select
              value={mode}
              disabled={disabled}
              onChange={(e) => onModeChange(e.target.value as ChatMode)}
              className="h-full min-w-[6.5rem] rounded-lg border border-neutral-200 bg-white px-2 py-2 text-xs leading-normal text-neutral-700 shadow-sm focus:border-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-200"
            >
              <option value="cowork">Co-work</option>
              <option value="modify">Modify</option>
            </select>
          </div>
        ) : (
          <span className="flex h-full min-h-[2.75rem] shrink-0 items-center rounded-lg border border-transparent px-2 text-xs text-neutral-400">
            Modify
          </span>
        )}
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
        {showCowork ? (
          <button
            type="button"
            disabled={disabled}
            onClick={onEndConversation}
            className="rounded-lg border border-neutral-200 bg-white px-4 py-2 text-xs font-medium text-neutral-700 shadow-sm hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            End conversation
          </button>
        ) : null}
      </div>

      {coworkReady ? (
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
