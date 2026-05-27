import { useT } from '../../i18n/useI18n';
import { Plus, Trash2 } from 'lucide-react';
import NLAssistant from './NLAssistant';

interface Aggregation {
  column: string;
  function: string;
  output_column?: string;
}

interface Props {
  value: Aggregation[];
  onChange: (aggs: Aggregation[]) => void;
  columns: string[];
  nodeType: string;
}

const AGG_FUNCTIONS = ['count', 'first', 'mode', 'sum', 'min', 'max'];

export default function AggregationsEditor({ value, onChange, columns, nodeType }: Props) {
  const t = useT();
  const aggs = Array.isArray(value) ? value : [];

  const addRow = () => {
    onChange([...aggs, { column: columns[0] || '', function: 'count', output_column: '' }]);
  };

  const updateRow = (i: number, patch: Partial<Aggregation>) => {
    const next = aggs.map((a, idx) => (idx === i ? { ...a, ...patch } : a));
    onChange(next);
  };

  const removeRow = (i: number) => {
    onChange(aggs.filter((_, idx) => idx !== i));
  };

  return (
    <div className="space-y-2">
      {aggs.map((agg, i) => (
        <div key={i} className="flex items-center gap-1.5 p-2 bg-[#0f172a] rounded border border-[#334155]">
          <select
            value={agg.column}
            onChange={(e) => updateRow(i, { column: e.target.value })}
            className="flex-1 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0]"
          >
            <option value="">{t('cfg.selectCol')}</option>
            {columns.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <select
            value={agg.function}
            onChange={(e) => updateRow(i, { function: e.target.value })}
            className="flex-1 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0]"
          >
            {AGG_FUNCTIONS.map((fn) => (
              <option key={fn} value={fn}>{t(`ag.${fn}`, fn)}</option>
            ))}
          </select>
          <input
            type="text"
            value={agg.output_column || ''}
            onChange={(e) => updateRow(i, { output_column: e.target.value })}
            placeholder={t('fl.output_column')}
            className="w-24 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0] placeholder-[#475569]"
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
        fieldName="aggregations"
        columns={columns}
        onResult={(result) => { if (Array.isArray(result)) onChange(result); }}
      />
    </div>
  );
}
