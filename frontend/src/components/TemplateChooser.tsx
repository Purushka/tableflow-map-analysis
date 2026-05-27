import { useT } from '../i18n/useI18n';
import { TEMPLATES, type Template } from '../templates/index';
import { X, FileSpreadsheet, Sparkles, Puzzle } from 'lucide-react';

interface Props {
  onSelect: (template: Template) => void;
  onClose: () => void;
}

const CATEGORY_META: Record<string, { label: string; icon: any; color: string }> = {
  general: { label: 'tpl.general', icon: FileSpreadsheet, color: '#3b82f6' },
  ai: { label: 'tpl.ai', icon: Sparkles, color: '#8b5cf6' },
  plugin: { label: 'tpl.plugin', icon: Puzzle, color: '#ec4899' },
};

export default function TemplateChooser({ onSelect, onClose }: Props) {
  const t = useT();

  const grouped: Record<string, Template[]> = {};
  for (const tpl of TEMPLATES) {
    const cat = tpl.category || 'general';
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(tpl);
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center">
      <div className="bg-[#1e293b] rounded-lg border border-[#334155] w-[480px] max-h-[70vh] flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#334155]">
          <h3 className="text-sm font-semibold text-white">{t('tpl.title')}</h3>
          <button onClick={onClose} className="p-1 hover:bg-[#334155] rounded">
            <X size={14} className="text-[#94a3b8]" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {['general', 'ai', 'plugin'].map((cat) => {
            if (!grouped[cat]) return null;
            const meta = CATEGORY_META[cat];
            const Icon = meta.icon;
            return (
              <div key={cat}>
                <div className="flex items-center gap-2 mb-2">
                  <Icon size={14} style={{ color: meta.color }} />
                  <span className="text-xs font-bold uppercase tracking-wider" style={{ color: meta.color }}>
                    {t(meta.label, cat)}
                  </span>
                </div>
                <div className="space-y-2">
                  {grouped[cat].map((tpl) => (
                    <button
                      key={tpl.id}
                      onClick={() => onSelect(tpl)}
                      className="w-full text-left px-3 py-2.5 rounded-md bg-[#0f172a] border border-[#334155]
                                 hover:border-blue-500 hover:bg-[#0f172a]/80 transition-colors"
                    >
                      <div className="text-sm text-white font-medium">{tpl.name}</div>
                      <div className="text-xs text-[#94a3b8] mt-0.5">{tpl.description}</div>
                      <div className="text-xs text-[#475569] mt-1">
                        {tpl.nodes.length} {t('tpl.nodes')} · {tpl.edges.length} {t('tpl.connections')}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
