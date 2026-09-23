import React from "react";

export interface PillBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "wiki" | "citation" | "protected" | "candidate" | "neutral";
  interactive?: boolean;
}

export const PillBadge: React.FC<PillBadgeProps> = ({
  variant = "neutral",
  interactive = false,
  children,
  className = "",
  ...props
}) => {
  const baseClasses =
    "rounded-full px-2.5 py-0.5 text-xs font-medium inline-flex items-center gap-1 select-none transition-colors border";

  const variantClasses = {
    wiki: "bg-emerald-50 text-emerald-800 border-emerald-200/60 hover:bg-emerald-100",
    citation: "bg-blue-50 text-blue-700 border-blue-200/60 hover:bg-blue-100 font-mono",
    protected: "bg-amber-50 text-amber-800 border-amber-200/80 font-medium",
    candidate: "bg-rose-50 text-rose-700 border-rose-200/60 font-medium",
    neutral: "bg-zinc-100 text-zinc-700 border-zinc-200/80",
  }[variant];

  const interactiveClasses = interactive
    ? "cursor-pointer active:scale-95 transition-transform"
    : "";

  return (
    <span
      className={`${baseClasses} ${variantClasses} ${interactiveClasses} ${className}`}
      {...props}
    >
      {children}
    </span>
  );
};
