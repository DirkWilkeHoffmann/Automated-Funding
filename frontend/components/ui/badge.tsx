import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide transition",
  {
    variants: {
      variant: {
        muted: "border-slate-200 bg-slate-100 text-slate-700",
        outline: "border-slate-200 text-slate-600",
        accent: "border-brand/40 bg-brand-50 text-orange-800",
        // Eligibility-specific
        "highly-eligible": "border-emerald-200 bg-emerald-50 text-emerald-800",
        eligible: "border-teal-200 bg-teal-50 text-teal-800",
        "possibly-eligible": "border-amber-200 bg-amber-50 text-amber-800",
        "low-match": "border-orange-200 bg-orange-50 text-orange-800",
        "not-eligible": "border-red-200 bg-red-50 text-red-700",
        // Misc
        new: "border-accent-100 bg-accent-50 text-accent animate-new-badge-fade",
        pinned: "border-brand/40 bg-brand-50 text-orange-800",
      },
    },
    defaultVariants: {
      variant: "muted",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
