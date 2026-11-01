import type { ReactNode } from "react";

/** Dashboard headline block: title, optional helper line, optional actions. */
export default function DeskHero({
  title,
  helper,
  helperClassName = "text-sm leading-[22px] text-muted",
  children,
}: {
  title: string;
  helper?: string;
  helperClassName?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-4">
      <h1 className="text-[22px] font-[590] leading-7 tracking-[-0.03em] text-foreground">{title}</h1>
      {helper ? <p className={helperClassName}>{helper}</p> : null}
      {children}
    </div>
  );
}
