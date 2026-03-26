import { ZS_LOGO_SRC } from '@/utils/constants'

export function AppTopBar() {
  return (
    <header className="border-b border-neutral-200/70 bg-white/90 backdrop-blur-sm">
      <div className="mx-auto flex max-w-[1600px] items-center px-6 py-3 md:px-10 md:py-4">
        <img
          src={ZS_LOGO_SRC}
          alt="ZS Associates"
          className="h-7 w-auto md:h-8"
        />
      </div>
    </header>
  )
}
