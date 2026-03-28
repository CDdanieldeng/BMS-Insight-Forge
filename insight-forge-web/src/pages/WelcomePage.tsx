import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { fetchSlideInfoFromPptx } from '@/api/insightForgeApi'
import { EntraSessionBar } from '@/components/EntraSessionBar'
import { ModuleIcon } from '@/components/ModuleIcon'
import { MODULE_DESC, MODULES, ZS_LOGO_SRC } from '@/utils/constants'
import { getTemplateFetchUrl } from '@/utils/env'
import { useAppStore } from '@/store/appStore'

export function WelcomePage() {
  const navigate = useNavigate()
  const selectedProduct = useAppStore((s) => s.selectedProduct)
  const setSelectedProduct = useAppStore((s) => s.setSelectedProduct)
  const productDescription = useAppStore((s) => s.productDescription)
  const setProductDescription = useAppStore((s) => s.setProductDescription)
  const setSlideInfoAndDeck = useAppStore((s) => s.setSlideInfoAndDeck)
  const setStarted = useAppStore((s) => s.setStarted)
  const setProcessing = useAppStore((s) => s.setProcessing)
  const setBannerError = useAppStore((s) => s.setBannerError)

  const startMutation = useMutation({
    mutationFn: async (payload: { name: string; description: string }) => {
      const res = await fetch(getTemplateFetchUrl())
      if (!res.ok) {
        throw new Error(`Could not load template deck (${res.status}). Check VITE_TEMPLATE_FETCH_URL.`)
      }
      const buf = await res.arrayBuffer()
      const blob = new Blob([buf], {
        type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      })
      const slideInfo = await fetchSlideInfoFromPptx(blob)
      return { slideInfo, buf, ...payload }
    },
    onMutate: () => {
      setProcessing('Loading deck…')
      setBannerError(null)
    },
    onSuccess: (data) => {
      setSelectedProduct(data.name)
      setProductDescription(data.description)
      setSlideInfoAndDeck(data.slideInfo, data.buf)
      setStarted(true)
      setProcessing(null)
      navigate('/workspace')
    },
    onError: (e) => {
      setProcessing(null)
      setBannerError(e instanceof Error ? e.message : 'Start failed')
    },
  })

  const productOk = selectedProduct.trim().length > 0

  return (
    <div className="mx-auto flex max-w-4xl flex-col items-center px-4 py-16 md:py-24">
      <img
        src={ZS_LOGO_SRC}
        alt=""
        className="h-10 w-auto md:h-12"
        aria-hidden
      />
      <p className="mt-8 text-[11px] font-medium uppercase tracking-[0.2em] text-neutral-400">
        Internal
      </p>
      <h1 className="mt-4 text-center text-4xl font-semibold tracking-tight text-neutral-900 md:text-5xl">
        ZS BP Coach
      </h1>
      <p className="mt-5 max-w-lg text-center text-sm leading-relaxed text-neutral-500 md:text-base">
        A calm workspace for shaping your business plan — co-create slides with retrieval and
        structured fills, without the noise of a classic dashboard.
      </p>

      <div className="mt-14 grid w-full max-w-2xl gap-3 sm:grid-cols-3">
        {MODULES.map((m) => (
          <div
            key={m}
            className="rounded-2xl border border-neutral-200/80 bg-white px-5 py-5 shadow-[0_2px_24px_-12px_rgba(0,0,0,0.12)]"
          >
            <ModuleIcon module={m} className="size-8 text-neutral-400" title={`${m} icon`} />
            <div className="mt-3 text-sm font-medium text-neutral-800">{m}</div>
            <div className="mt-2 text-[11px] leading-relaxed text-neutral-500 line-clamp-4">
              {MODULE_DESC[m]}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-14 w-full max-w-sm space-y-4">
        <div>
          <label
            htmlFor="product-name"
            className="block text-[11px] font-medium uppercase tracking-wider text-neutral-500"
          >
            Product name
            <span className="font-normal normal-case tracking-normal text-red-600"> *</span>
          </label>
          <input
            id="product-name"
            type="text"
            value={selectedProduct}
            onChange={(e) => setSelectedProduct(e.target.value)}
            autoComplete="off"
            placeholder="Repatha"
            required
            className="mt-2 w-full rounded-xl border border-neutral-200 bg-white px-4 py-3 text-sm text-neutral-800 shadow-sm placeholder:text-neutral-400 focus:border-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-200"
          />
        </div>

        <div>
          <label
            htmlFor="product-description"
            className="block text-[11px] font-medium uppercase tracking-wider text-neutral-500"
          >
            Product description
            <span className="ml-1 font-normal normal-case tracking-normal text-neutral-400">
              (optional)
            </span>
          </label>
          <input
            id="product-description"
            type="text"
            value={productDescription}
            onChange={(e) => setProductDescription(e.target.value)}
            autoComplete="off"
            placeholder="PCSK9 inhibitor used to significantly lower LDL-C"
            className="mt-2 w-full rounded-xl border border-neutral-200 bg-white px-4 py-3 text-sm text-neutral-800 shadow-sm placeholder:text-neutral-400 focus:border-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-200"
          />
        </div>
        <button
          type="button"
          disabled={!productOk || startMutation.isPending}
          onClick={() =>
            startMutation.mutate({
              name: selectedProduct.trim(),
              description: productDescription.trim(),
            })
          }
          className="w-full rounded-xl bg-neutral-900 py-3 text-sm font-medium text-white shadow-sm hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Start
        </button>
        <EntraSessionBar />
      </div>
    </div>
  )
}
