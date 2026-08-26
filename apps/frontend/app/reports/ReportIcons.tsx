import type { ReactElement, SVGProps } from "react";

export type ReportIconName =
  | "chart"
  | "sparkle"
  | "list"
  | "warning"
  | "calendar"
  | "swap"
  | "flag"
  | "steps"
  | "lightbulb"
  | "sliders"
  | "layers"
  | "clock";

type IconProps = SVGProps<SVGSVGElement>;

function Svg({ children, className, ...rest }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className ?? "h-4 w-4"}
      aria-hidden
      {...rest}
    >
      {children}
    </svg>
  );
}

function ChartIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 19V9" />
      <path d="M10 19V5" />
      <path d="M16 19v-7" />
      <path d="M22 19H2" />
    </Svg>
  );
}

function SparkleIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3.2 13.6 9l5.9 1.6L13.6 12.2 12 18l-1.6-5.8L4.5 10.6 10.4 9 12 3.2Z" />
      <path d="M19 15.5 19.7 18l2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z" />
    </Svg>
  );
}

function ListIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M8 6h13" />
      <path d="M8 12h13" />
      <path d="M8 18h13" />
      <path d="M3 6h.01" />
      <path d="M3 12h.01" />
      <path d="M3 18h.01" />
    </Svg>
  );
}

function WarningIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
      <path d="M10.3 4.7 2.4 18.2A2 2 0 0 0 4.1 21h15.8a2 2 0 0 0 1.7-2.8L13.7 4.7a2 2 0 0 0-3.4 0Z" />
    </Svg>
  );
}

function CalendarIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M8 3v4" />
      <path d="M16 3v4" />
      <path d="M3 10h18" />
    </Svg>
  );
}

function SwapIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M16 3h5v5" />
      <path d="M21 3 13 11" />
      <path d="M8 21H3v-5" />
      <path d="M3 21l8-8" />
    </Svg>
  );
}

function FlagIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 21V4" />
      <path d="M5 4h9l-1.2 3.5L19 11H5" />
    </Svg>
  );
}

function StepsIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 18h4v-4H4z" />
      <path d="M10 18h4V8h-4z" />
      <path d="M16 18h4V4h-4z" />
    </Svg>
  );
}

function LightbulbIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M9 18h6" />
      <path d="M10 21h4" />
      <path d="M12 3a6 6 0 0 0-3.4 10.9c.9.7 1.4 1.6 1.4 2.6V18h4v-1.5c0-1 .5-1.9 1.4-2.6A6 6 0 0 0 12 3Z" />
    </Svg>
  );
}

function SlidersIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 8h16" />
      <path d="M4 16h16" />
      <circle cx="8" cy="8" r="2" />
      <circle cx="16" cy="16" r="2" />
    </Svg>
  );
}

function LayersIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="m12 3 9 5-9 5-9-5 9-5Z" />
      <path d="m3 12 9 5 9-5" />
      <path d="m3 16 9 5 9-5" />
    </Svg>
  );
}

function ClockIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </Svg>
  );
}

const ICONS: Record<ReportIconName, (props: IconProps) => ReactElement> = {
  chart: ChartIcon,
  sparkle: SparkleIcon,
  list: ListIcon,
  warning: WarningIcon,
  calendar: CalendarIcon,
  swap: SwapIcon,
  flag: FlagIcon,
  steps: StepsIcon,
  lightbulb: LightbulbIcon,
  sliders: SlidersIcon,
  layers: LayersIcon,
  clock: ClockIcon,
};

export default function ReportIcon({
  name,
  className,
}: {
  name: ReportIconName;
  className?: string;
}) {
  const Icon = ICONS[name];
  return <Icon className={className ?? "h-4 w-4"} />;
}
