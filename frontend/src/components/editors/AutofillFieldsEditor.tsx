import { useT } from '../../i18n/useI18n';
import { Plus, Trash2 } from 'lucide-react';
import NLAssistant from './NLAssistant';

interface FieldEntry {
  column: string;
  description: string;
}

interface Props {
  value: FieldEntry[];
  onChange: (fields: FieldEntry[]) => void;
  columns: string[];
  nodeType: string;
}

export default function AutofillFieldsEditor({ value, onChange, columns, nodeType }: Props) {
  const t = useT();
  const entries = Array.isArray(value) ? value : [];

  const addRow = () => {
    onChange([...entries, { column: columns[0] || '', description: '' }]);
  };

  const updateRow = (i: number, patch: Partial<FieldEntry>) => {
    const next = entries.map((e, idx) => (idx === i ? { ...e, ...patch } : e));
    onChange(next);
  };

  const removeRow = (i: number) => {
    onChange(entries.filter((_, idx) => idx !== i));
  };

  return (
    <div className="space-y-2">
      {entries.map((entry, i) => (
        <div key={i} className="flex items-center gap-1.5 p-2 bg-[#0f172a] rounded border border-[#334155]">
          <select
            value={entry.column}
            onChange={(e) => updateRow(i, { column: e.target.value })}
            className="w-[40%] px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0]"
          >
            <option value="">{t('cfg.selectCol')}</option>
            {columns.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <input
            type="text"
            value={entry.description || ''}
            onChange={(e) => updateRow(i, { description: e.target.value })}
            placeholder={t('cfg.fieldDesc')}
            className="flex-1 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0] placeholder-[#475569]"
          />
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
        fieldName="fields_to_fill"
        columns={columns}
        onResult={(result) => { if (Array.isArray(result)) onChange(result); }}
      />
    </div>
  );
}
