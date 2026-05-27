import { useState, useEffect } from 'react';
import { useT } from '../../i18n/useI18n';
import { getNormalizeFunctions } from '../../api/client';
import { Plus, Trash2 } from 'lucide-react';
import NLAssistant from './NLAssistant';

interface Operation {
  column: string;
  function: string;
  params?: Record<string, string>;
  output_column?: string;
}

interface Props {
  value: Operation[];
  onChange: (ops: Operation[]) => void;
  columns: string[];
  nodeType: string;
}

const FALLBACK_FUNCTIONS = [
  'trim', 'lowercase', 'uppercase', 'title_case', 'strip_html',
  'number', 'date', 'regex_extract', 'find_replace',
];

export default function OperationsEditor({ value, onChange, columns, nodeType }: Props) {
  const t = useT();
  const [functions, setFunctions] = useState<string[]>(FALLBACK_FUNCTIONS);

  useEffect(() => {
    getNormalizeFunctions()
      .then((fns) => { if (fns.length) setFunctions(fns); })
      .catch(() => {});
  }, []);
  const ops = Array.isArray(value) ? value : [];

  const addRow = () => {
    onChange([...ops, { column: columns[0] || '', function: 'trim' }]);
  };

  const updateRow = (i: number, patch: Partial<Operation>) => {
    const next = ops.map((op, idx) => (idx === i ? { ...op, ...patch } : op));
    onChange(next);
  };

  const removeRow = (i: number) => {
    onChange(ops.filter((_, idx) => idx !== i));
  };

  return (
    <div className="space-y-2">
      {ops.map((op, i) => (
        <div key={i} className="flex items-center gap-1.5 p-2 bg-[#0f172a] rounded border border-[#334155]">
          <select
            value={op.column}
            onChange={(e) => updateRow(i, { column: e.target.value })}
            className="flex-1 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0]"
          >
            <option value="">{t('cfg.selectCol')}</option>
            <option value="*">{t('cfg.allColumns')}</option>
            {columns.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <select
            value={op.function}
            onChange={(e) => updateRow(i, { function: e.target.value })}
            className="flex-1 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0]"
          >
            {functions.map((fn) => (
              <option key={fn} value={fn}>{t(`fn.${fn}`, fn)}</option>
            ))}
          </select>
          {(op.function === 'regex_extract' || op.function === 'find_replace') && (
            <input
              type="text"
              value={op.params?.pattern || ''}
              onChange={(e) => updateRow(i, { params: { ...op.params, pattern: e.target.value } })}
              placeholder="pattern"
              className="w-20 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0] placeholder-[#475569]"
            />
          )}
          {op.function === 'find_replace' && (
            <input
              type="text"
              value={op.params?.replacement || ''}
              onChange={(e) => updateRow(i, { params: { ...op.params, replacement: e.target.value } })}
              placeholder="replace"
              className="w-20 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0] placeholder-[#475569]"
            />
          )}
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
        fieldName="operations"
        columns={columns}
        onResult={(result) => { if (Array.isArray(result)) onChange(result); }}
      />
    </div>
  );
}
