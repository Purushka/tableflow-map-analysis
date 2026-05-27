import { usePipelineStore } from '../store/pipelineStore';
import { useT } from '../i18n/useI18n';
import type { NodeDefinition } from '../types/pipeline';
import {
  FileSpreadsheet, Wand2, Filter, GitBranch, Merge, Calculator, Layers,
  Sparkles, Tags, BookOpen, MapPin, Library, FileDown, FileJson,
  Braces, Globe, Copy, Table2, Shuffle, Puzzle, SearchCheck, WandSparkles,
} from 'lucide-react';

const ICONS: Record<string, any> = {
  FileSpreadsheet, Wand2, Filter, GitBranch, Merge, Calculator, Layers,
  Sparkles, Tags, BookOpen, MapPin, Library, FileDown, FileJson,
  Braces, Globe, Copy, Table2, Shuffle, Puzzle, SearchCheck, WandSparkles,
};

const CATEGORY_ORDER = ['input', 'transform', 'ai', 'lookup', 'output', 'plugin'];
const CATEGORY_COLORS: Record<string, string> = {
  input: '#3b82f6', transform: '#10b981', ai: '#8b5cf6', lookup: '#f59e0b', output: '#ef4444', plugin: '#ec4899',
};

export default function NodePalette() {
  const t = useT();
  const nodeDefinitions = usePipelineStore((s) => s.nodeDefinitions);

  const grouped: Record<string, NodeDefinition[]> = {};
  for (const defn of nodeDefinitions) {
    const cat = defn.plugin ? 'plugin' : defn.category;
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(defn);
  }

  const onDragStart = (e: React.DragEvent, defn: NodeDefinition) => {
    e.dataTransfer.setData('application/reactflow-type', defn.type);
    e.dataTransfer.effectAllowed = 'move';
  };

  return (
    <div className="w-60 bg-[#1e293b] border-r border-[#334155] flex flex-col h-full overflow-hidden">
      <div className="px-4 py-3 border-b border-[#334155]">
        <h2 className="text-sm font-semibold text-white">{t('palette.title')}</h2>
        <p className="text-xs text-[#64748b] mt-0.5">{t('palette.subtitle')}</p>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {CATEGORY_ORDER.map((cat) => (
          grouped[cat] && (
            <div key={cat}>
              <h3
                className="text-xs font-bold uppercase tracking-wider mb-2 px-1"
                style={{ color: CATEGORY_COLORS[cat] }}
              >
                {t(`cat.${cat}`, cat)}
              </h3>
              <div className="space-y-1">
                {grouped[cat].map((defn) => {
                  const Icon = ICONS[defn.icon] || FileSpreadsheet;
                  return (
                    <div
                      key={defn.type}
                      draggable
                      onDragStart={(e) => onDragStart(e, defn)}
                      className="flex items-center gap-2 px-3 py-2 rounded-md cursor-grab active:cursor-grabbing
                                 bg-[#0f172a] hover:bg-[#334155] border border-[#334155] transition-colors"
                      title={t(`nd.${defn.type}`, defn.description)}
                    >
                      <Icon size={14} style={{ color: CATEGORY_COLORS[defn.category] }} />
                      <span className="text-xs text-[#e2e8f0]">{t(`node.${defn.type}`, defn.label)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )
        ))}
      </div>
    </div>
  );
}
