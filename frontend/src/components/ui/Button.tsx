import type { ReactNode, ButtonHTMLAttributes } from 'react';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';

const variantClasses: Record<Variant, string> = {
  primary: 'bg-emerald-600 hover:bg-emerald-700 text-white',
  secondary: 'bg-[#0f172a] border border-[#334155] text-[#94a3b8] hover:bg-[#334155]',
  ghost: 'text-[#94a3b8] hover:bg-[#334155] hover:text-[#e2e8f0]',
  danger: 'bg-red-600/20 text-red-400 hover:bg-red-600/30',
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  icon?: ReactNode;
  children?: ReactNode;
}

export default function Button({ variant = 'secondary', icon, children, className = '', ...props }: ButtonProps) {
  return (
    <button
      className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors disabled:opacity-50 ${variantClasses[variant]} ${className}`}
      {...props}
    >
      {icon}
      {children}
    </button>
  );
}
