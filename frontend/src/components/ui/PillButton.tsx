import React from "react";

interface PillButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "outline" | "danger";
  size?: "sm" | "md";
  icon?: React.ReactNode;
}

export const PillButton: React.FC<PillButtonProps> = ({
  variant = "primary",
  size = "md",
  icon,
  children,
  className = "",
  disabled,
  ...props
}) => {
  const baseClasses =
    "rounded-full font-medium whitespace-nowrap inline-flex items-center justify-center gap-1.5 transition-all duration-150 select-none pill-active cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none";

  const sizeClasses = {
    sm: "px-3.5 py-1 text-xs",
    md: "px-5 py-2 text-sm",
  }[size];

  const variantClasses = {
    primary: "bg-zinc-900 text-zinc-50 hover:bg-zinc-800 shadow-sm",
    secondary: "bg-zinc-100 hover:bg-zinc-200/80 text-zinc-800",
    outline: "border border-zinc-200 bg-white hover:bg-zinc-50 text-zinc-700",
    danger: "bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200/60",
  }[variant];

  return (
    <button
      className={`${baseClasses} ${sizeClasses} ${variantClasses} ${className}`}
      disabled={disabled}
      {...props}
    >
      {icon && <span className="shrink-0">{icon}</span>}
      {children}
    </button>
  );
};
