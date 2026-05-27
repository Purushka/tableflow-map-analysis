import { useT } from '../../i18n/useI18n';
import { Plus, Trash2 } from 'lucide-react';
import NLAssistant from './NLAssistant';

interface Condition {
  column: string;
  operator: string;
  value: string;
}

interface Rule {
  output: string;
  label?: string;
  conditions: Condition[];
}

interface Props {
  value: Rule[];
  onChange: (rules: Rule[]) => void;
  columns: string[];
  nodeType: string;
}

const OPERATORS = [
  'equals', 'not_equals', 'contains', 'not_contains',
  'is_empty', 'is_not_empty', 'regex',
  'greater_than', 'less_than', '>=', '<=',
];

export default function RulesEditor({ value, onChange, columns, nodeType }: Props) {
  const t = useT();
  const rules = Array.isArray(value) ? value : [];

  const addRule = () => {
    const nextOutput = `route_${rules.length + 1}`;
    onChange([...rules, {
      output: nextOutput,
      label: `Route ${rules.length + 1}`,
      conditions: [{ column: columns[0] || '', operator: 'equals', value: '' }],
    }]);
  };

  const removeRule = (i: number) => {
    onChange(rules.filter((_, idx) => idx !== i));
  };

  const updateRule = (i: number, patch: Partial<Rule>) => {
    const next = rules.map((r, idx) => (idx === i ? { ...r, ...patch } : r));
    onChange(next);
  };

  const addCondition = (ri: number) => {
    const rule = rules[ri];
    updateRule(ri, {
      conditions: [...rule.conditions, { column: columns[0] || '', operator: 'equals', value: '' }],
    });
  };

  const updateCondition = (ri: number, ci: number, patch: Partial<Condition>) => {
    const rule = rules[ri];
    const conditions = rule.conditions.map((c, idx) => (idx === ci ? { ...c, ...patch } : c));
    updateRule(ri, { conditions });
  };

  const removeCondition = (ri: number, ci: number) => {
    const rule = rules[ri];
    updateRule(ri, { conditions: rule.conditions.filter((_, idx) => idx !== ci) });
  };

  return (
    <div className="space-y-3">
      {rules.map((rule, ri) => (
        <div key={ri} className="p-2 bg-[#0f172a] rounded border border-[#334155] space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-amber-400">{rule.output}</span>
              <input
                type="text"
                value={rule.label || ''}
                onChange={(e) => updateRule(ri, { label: e.target.value })}
                placeholder="Label"
                className="w-24 px-2 py-0.5 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0] placeholder-[#475569]"
              />
            </div>
            <button onClick={() => removeRule(ri)} className="p-1 text-red-400 hover:bg-red-500/20 rounded">
              <Trash2 size={12} />
            </button>
          </div>

          {rule.conditions.map((cond, ci) => (
            <div key={ci} className="flex items-center gap-1.5">
              <select
                value={cond.column}
                onChange={(e) => updateCondition(ri, ci, { column: e.target.value })}
                className="flex-1 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0]"
              >
                <option value="">{t('cfg.selectCol')}</option>
                {columns.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <select
                value={cond.operator}
                onChange={(e) => updateCondition(ri, ci, { operator: e.target.value })}
                className="w-28 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0]"
              >
                {OPERATORS.map((op) => (
                  <option key={op} value={op}>{t(`op.${op}`, op)}</option>
                ))}
              </select>
              {!['is_empty', 'is_not_empty'].includes(cond.operator) && (
                <input
                  type="text"
                  value={cond.value}
                  onChange={(e) => updateCondition(ri, ci, { value: e.target.value })}
                  placeholder={t('fl.value')}
                  className="w-20 px-2 py-1 text-xs bg-[#1e293b] border border-[#334155] rounded text-[#e2e8f0] placeholder-[#475569]"
                />
              )}
              <button onClick={() => removeCondition(ri, ci)} className="p-0.5 text-red-400 hover:bg-red-500/20 rounded">
                <Trash2 size={10} />
              </button>
            </div>
          ))}

          <button
            onClick={() => addCondition(ri)}
            className="text-xs text-blue-400 hover:text-blue-300"
          >
            + condition
          </button>
        </div>
      ))}

      <button
        onClick={addRule}
        className="flex items-center gap-1 px-2 py-1 text-xs text-emerald-400 hover:bg-emerald-500/10 rounded"
      >
        <Plus size={12} />
        {t('cfg.addRow')}
      </button>
      <NLAssistant
        nodeType={nodeType}
        fieldName="rules"
        columns={columns}
        onResult={(result) => { if (Array.isArray(result)) onChange(result); }}
      />
    </div>
  );
}
