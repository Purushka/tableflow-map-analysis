import { useState, type ReactNode } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

interface PanelProps {
  title: string;
  icon?: ReactNode;
  defaultCollapsed?: boolean;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

export default function Panel({ title, icon, defaultCollapsed = false, actions, children, className = '' }: PanelProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  return (
    <div className={`bg-[#0f172a] border border-[#334155] rounded-lg overflow-hidden ${className}`}>
      <div
        className="flex items-center justify-between px-3 py-1.5 border-b border-[#334155] cursor-pointer select-none hover:bg-[#1e293b] transition-colors"
        onClick={() => setCollapsed(!collapsed)}
      >
        <div className="flex items-center gap-2 text-xs text-[#94a3b8]">
          {icon}
          <span className="font-medium">{title}</span>
        </div>
        <div className="flex items-center gap-1">
          {actions && <div onClick={(e) => e.stopPropagation()}>{actions}</div>}
          {collapsed ? <ChevronUp size={12} className="text-[#64748b]" /> : <ChevronDown size={12} className="text-[#64748b]" />}
        </div>
      </div>
      {!collapsed && children}
    </div>
  );
}
