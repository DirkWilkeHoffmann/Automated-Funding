"use client";

import { ReactNode } from "react";
import { cn } from "../../lib/utils";

interface TooltipProps {
  children: ReactNode;
  label: string;
  side?: "right" | "top" | "bottom";
  className?: string;
}

export function Tooltip({ children, label, side = "right", className }: TooltipProps) {
  const positionClass =
    side === "right"
      ? "left-full top-1/2 ml-2.5 -translate-y-1/2"
      : side === "top"
      ? "bottom-full left-1/2 mb-2 -translate-x-1/2"
      : "top-full left-1/2 mt-2 -translate-x-1/2";

  return (
    <div className={cn("group relative", className)}>
      {children}
      <div
        className={cn(
          "pointer-events-none absolute z-50 whitespace-nowrap rounded-md bg-slate-900 px-2.5 py-1",
          "text-xs font-medium text-white shadow-lg",
          "opacity-0 transition-opacity duration-150 group-hover:opacity-100",
          positionClass
        )}
        role="tooltip"
      >
        {label}
        {side === "right" && (
          <div className="absolute right-full top-1/2 -translate-y-1/2 border-4 border-transparent border-r-slate-900" />
        )}
      </div>
    </div>
  );
}
