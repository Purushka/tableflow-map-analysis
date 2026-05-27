import type { ReactNode } from 'react';

type Variant = 'success' | 'warning' | 'error' | 'info' | 'default';

const variantClasses: Record<Variant, string> = {
  success: 'bg-emerald-900/50 text-emerald-300',
  warning: 'bg-amber-900/50 text-amber-300',
  error: 'bg-red-900/50 text-red-300',
  info: 'bg-blue-900/50 text-blue-300',
  default: 'bg-[#334155] text-[#94a3b8]',
};

interface BadgeProps {
  variant?: Variant;
  children: ReactNode;
  className?: string;
}

export default function Badge({ variant = 'default', children, className = '' }: BadgeProps) {
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium inline-flex items-center gap-1 ${variantClasses[variant]} ${className}`}>
      {children}
    </span>
  );
}
