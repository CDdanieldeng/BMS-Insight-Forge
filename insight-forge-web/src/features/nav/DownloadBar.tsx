import { useEffect, useMemo } from 'react'

export function DownloadBar({
  label,
  fileName,
  pptxBytes,
}: {
  label: string
  fileName: string
  pptxBytes: ArrayBuffer
}) {
  const blob = useMemo(
    () =>
      new Blob([pptxBytes], {
        type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      }),
    [pptxBytes],
  )
  const url = useMemo(() => URL.createObjectURL(blob), [blob])

  useEffect(() => {
    return () => URL.revokeObjectURL(url)
  }, [url])

  return (
    <div className="rounded-2xl border border-neutral-200/80 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium text-neutral-800">{label}</p>
      <a
        href={url}
        download={fileName}
        className="mt-3 inline-flex w-full items-center justify-center rounded-xl bg-neutral-900 py-2.5 text-xs font-medium text-white shadow-sm hover:bg-neutral-800"
      >
        Download deck
      </a>
    </div>
  )
}
