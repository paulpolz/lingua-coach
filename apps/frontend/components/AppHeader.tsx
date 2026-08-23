import Link from "next/link";

import AccountMenu from "@/components/AccountMenu";

function BrandMark() {
  return (
    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-sm font-bold text-white dark:text-stone-950">
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
    <header className="flex shrink-0 items-center justify-between gap-4 border-b border-border bg-surface px-4 py-3">
      <div className="flex min-w-0 items-center gap-4">
        <Link
          href="/"
          className="flex shrink-0 items-center gap-2.5 rounded-md text-foreground outline-none hover:opacity-90 focus-visible:ring-2 focus-visible:ring-accent"
          aria-label="Lingua Coach home"
        >
          <BrandMark />
          <span className="text-base font-semibold tracking-tight">Lingua Coach</span>
        </Link>
        {title ? (
          <div className="hidden min-w-0 border-l border-border pl-4 sm:block">
            <h1 className="truncate text-sm font-medium text-foreground">{title}</h1>
            {description ? <p className="truncate text-xs text-muted">{description}</p> : null}
          </div>
        ) : null}
      </div>
      <AccountMenu />
    </header>
  );
}
