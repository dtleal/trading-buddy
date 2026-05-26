import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      tone: {
        neutral: "bg-zinc-800 text-zinc-200",
        positive: "bg-emerald-950 text-emerald-300 ring-1 ring-emerald-700/50",
        negative: "bg-red-950 text-red-300 ring-1 ring-red-700/50",
        warning: "bg-amber-950 text-amber-300 ring-1 ring-amber-700/50",
        info: "bg-sky-950 text-sky-300 ring-1 ring-sky-700/50",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export { badgeVariants };
