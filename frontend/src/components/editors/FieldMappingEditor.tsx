import { useT } from '../../i18n/useI18n';
import { Plus, Trash2, ArrowRight } from 'lucide-react';
import NLAssistant from './NLAssistant';

interface Props {
  value: Record<string, string>;
  onChange: (mapping: Record<string, string>) => void;
  columns: string[];
  nodeType: string;
}

export default function FieldMappingEditor({ value, onChange, columns, nodeType }: Props) {
  const t = useT();
  const entries = Object.entries(value || {});

  const addRow = () => {
    onChange({ ...value, '': '' });
  };

  const updateKey = (oldKey: string, newKey: string) => {
    const next: Record<string, string> = {};
    for (const [k, v] of Object.entries(value || {})) {
      next[k === oldKey ? newKey : k] = v;
    }
    onChange(next);
  };

  const updateValue = (key: string, newVal: string) => {
    onChange({ ...(value || {}), [key]: newVal });
  };

  const removeRow = (key: string) => {
    const next = { ...(value || {}) };
    delete next[key];
    onChange(next);
  };

  return (
    <div className="space-y-2">
      {entries.map(([key, val], i) => (
        <div key={i} className="flex items-center gap-1.5 p-2 bg-[#0f172a] rounded border border-[#334155]">
          <input
            type="text"
            value={key}
            onChange={(e) => updateKey(key, e.target.value)}
            placeholder="AI field"
            className="flex-1 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0] placeholder-[#475569]"
          />
          <ArrowRight size={12} className="text-[#475569] shrink-0" />
          <input
            type="text"
            value={val}
            onChange={(e) => updateValue(key, e.target.value)}
            placeholder={t('fl.output_column')}
            className="flex-1 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0] placeholder-[#475569]"
          />
          <button onClick={() => removeRow(key)} className="p-1 text-red-400 hover:bg-red-500/20 rounded">
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
        fieldName="json_field_mapping"
        columns={columns}
        onResult={(result) => {
          if (result && typeof result === 'object' && !Array.isArray(result)) onChange(result);
        }}
      />
    </div>
  );
}
