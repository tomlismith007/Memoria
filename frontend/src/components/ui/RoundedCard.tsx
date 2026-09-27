import React from "react";

interface RoundedCardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "primary" | "item" | "amber" | "rose";
}

export const RoundedCard: React.FC<RoundedCardProps> = ({
  variant = "primary",
  children,
  className = "",
  ...props
}) => {
  const variantClasses = {
    primary:
      "bg-white rounded-3xl border border-zinc-200/80 p-6 md:p-8 shadow-[0_4px_20px_-4px_rgba(0,0,0,0.03)]",
    item: "bg-zinc-50/70 rounded-2xl border border-zinc-100 p-4",
    amber: "bg-amber-50/40 rounded-2xl border border-amber-200/60 p-4",
    rose: "bg-rose-50/30 rounded-2xl border border-rose-200/50 p-4",
  }[variant];

  return (
    <div className={`${variantClasses} ${className}`} {...props}>
      {children}
    </div>
  );
};
