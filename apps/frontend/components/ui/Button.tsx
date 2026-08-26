"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "default" | "sm";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: ReactNode;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-accent text-white hover:bg-accent-hover dark:text-stone-950",
  secondary:
    "border border-border-strong bg-surface text-foreground hover:bg-surface-muted",
  ghost: "bg-transparent text-muted hover:bg-surface-muted hover:text-foreground",
  danger: "bg-danger text-white hover:bg-danger/90 dark:text-stone-950",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  default: "h-10 px-4 py-2.5 text-sm font-semibold leading-5",
  sm: "h-8 px-2.5 py-1.5 text-xs font-semibold leading-4",
};

/**
 * Shared button — primary / secondary / ghost / danger.
 * Used by chat composer, plan card, and empty-state CTAs.
 */
export default function Button({
  variant = "primary",
  size = "default",
  className = "",
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center gap-1.5 rounded-xl [transition:transform_120ms_cubic-bezier(0.23,1,0.32,1),background-color_150ms_ease,opacity_150ms_ease] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/20 ${VARIANT_CLASSES[variant]} ${SIZE_CLASSES[size]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
