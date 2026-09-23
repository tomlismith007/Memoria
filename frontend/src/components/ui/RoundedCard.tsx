import React from "react";

export interface RoundedCardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "primary" | "item" | "flat" | "amber" | "rose";
  hoverEffect?: boolean;
}

export const RoundedCard: React.FC<RoundedCardProps> = ({
  variant = "primary",
  hoverEffect = false,
  children,
  className = "",
  ...props
}) => {
  const variantClasses = {
    primary:
      "bg-white rounded-3xl border border-zinc-200/80 p-6 md:p-8 shadow-[0_4px_20px_-4px_rgba(0,0,0,0.03)]",
    item: "bg-zinc-50/70 rounded-2xl border border-zinc-100 p-4",
    flat: "bg-white rounded-2xl border border-zinc-200/80 p-5",
    amber: "bg-amber-50/40 rounded-2xl border border-amber-200/60 p-4",
    rose: "bg-rose-50/30 rounded-2xl border border-rose-200/50 p-4",
  }[variant];

  const hoverClasses = hoverEffect
    ? "hover:border-zinc-300 hover:shadow-[0_4px_16px_-4px_rgba(0,0,0,0.06)] transition-all duration-150"
    : "";

  return (
    <div className={`${variantClasses} ${hoverClasses} ${className}`} {...props}>
      {children}
    </div>
  );
};
