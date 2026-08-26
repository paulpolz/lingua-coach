import Link from "next/link";

import AccountMenu from "@/components/AccountMenu";

function BrandMark() {
  return (
    <span className="flex h-[22px] w-[22px] items-center justify-center rounded-[6px] bg-accent text-[11px] font-bold text-white">
      L
    </span>
  );
}

export default function AppHeader({
  title,
  description,
}: {
  title?: string;
  description?: string;
}) {
  return (
    <header className="flex h-[52px] shrink-0 items-center justify-between gap-3 border-b border-border bg-background px-5">
      <div className="flex min-w-0 items-center gap-3">
        <Link
          href="/"
          className="flex shrink-0 items-center gap-2 rounded-md text-foreground outline-none hover:opacity-90 focus-visible:ring-2 focus-visible:ring-accent/20"
          aria-label="Lingua Coach home"
        >
          <BrandMark />
          <span className="text-[13px] font-medium leading-[18px] text-muted">Lingua Coach</span>
        </Link>
        {title ? (
          <>
            <span className="h-[18px] w-px shrink-0 bg-border" aria-hidden="true" />
            <div className="min-w-0">
              <h1 className="truncate text-[13px] font-semibold leading-[18px] tracking-[-0.01em] text-foreground">
                {title}
              </h1>
              {description ? (
                <p className="hidden truncate text-[11px] leading-4 text-muted sm:block">{description}</p>
              ) : null}
            </div>
          </>
        ) : null}
      </div>
      <AccountMenu />
    </header>
  );
}
