import type { ReactNode } from 'react';

export interface TabItem {
  id: string;
  label: string;
  icon?: ReactNode;
  badge?: string | null;
}

interface TabsProps {
  items: TabItem[];
  activeId: string;
  onSelect: (id: string) => void;
  className?: string;
}

export default function Tabs({ items, activeId, onSelect, className = '' }: TabsProps) {
  return (
    <div className={`flex items-center gap-0.5 ${className}`}>
      {items.map((tab) => {
        const isActive = tab.id === activeId;
        return (
          <button
            key={tab.id}
            onClick={() => onSelect(tab.id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-[11px] border-b-2 transition-colors ${
              isActive
                ? 'border-blue-500 text-[#e2e8f0]'
                : 'border-transparent text-[#64748b] hover:text-[#94a3b8]'
            }`}
          >
            {tab.icon}
            <span>{tab.label}</span>
            {tab.badge && (
              <span className={`text-[9px] px-1 py-0 rounded-full ${
                isActive ? 'bg-blue-500/20 text-blue-300' : 'bg-[#334155] text-[#64748b]'
              }`}>
                {tab.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
