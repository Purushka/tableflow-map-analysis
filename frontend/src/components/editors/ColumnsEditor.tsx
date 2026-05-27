import { useT } from '../../i18n/useI18n';
import { Plus, Trash2, ArrowUp, ArrowDown } from 'lucide-react';
import NLAssistant from './NLAssistant';

interface ColumnEntry {
  source: string;
  display_name?: string;
}

interface Props {
  value: ColumnEntry[];
  onChange: (cols: ColumnEntry[]) => void;
  columns: string[];
  nodeType: string;
}

export default function ColumnsEditor({ value, onChange, columns, nodeType }: Props) {
  const t = useT();
  const entries = Array.isArray(value) ? value : [];

  const addRow = () => {
    onChange([...entries, { source: columns[0] || '', display_name: '' }]);
  };

  const updateRow = (i: number, patch: Partial<ColumnEntry>) => {
    const next = entries.map((e, idx) => (idx === i ? { ...e, ...patch } : e));
    onChange(next);
  };

  const removeRow = (i: number) => {
    onChange(entries.filter((_, idx) => idx !== i));
  };

  const moveRow = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= entries.length) return;
    const next = [...entries];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };

  return (
    <div className="space-y-2">
      {entries.map((entry, i) => (
        <div key={i} className="flex items-center gap-1.5 p-2 bg-[#0f172a] rounded border border-[#334155]">
          <select
            value={entry.source}
            onChange={(e) => updateRow(i, { source: e.target.value })}
            className="flex-1 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0]"
          >
            <option value="">{t('cfg.selectCol')}</option>
            {columns.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <input
            type="text"
            value={entry.display_name || ''}
            onChange={(e) => updateRow(i, { display_name: e.target.value })}
            placeholder="Display name"
            className="flex-1 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0] placeholder-[#475569]"
          />
          <button
            onClick={() => moveRow(i, -1)}
            disabled={i === 0}
            className="p-0.5 text-[#94a3b8] hover:bg-[#334155] rounded disabled:opacity-30"
          >
            <ArrowUp size={10} />
          </button>
          <button
            onClick={() => moveRow(i, 1)}
            disabled={i === entries.length - 1}
            className="p-0.5 text-[#94a3b8] hover:bg-[#334155] rounded disabled:opacity-30"
          >
            <ArrowDown size={10} />
          </button>
          <button onClick={() => removeRow(i)} className="p-1 text-red-400 hover:bg-red-500/20 rounded">
            <Trash2 size={12} />
          </button>
        </div>
      ))}
      <button
        onClick={addRow}
        className="flex items-center gap-1 px-2 py-1 text-xs text-emerald-400 hover:bg-emerald-500/10 rounded"
      >
        <Plus size={12} />
        {t('cfg.addRow')}
      </button>
      <NLAssistant
        nodeType={nodeType}
        fieldName="columns"
        columns={columns}
        onResult={(result) => { if (Array.isArray(result)) onChange(result); }}
      />
    </div>
  );
}
