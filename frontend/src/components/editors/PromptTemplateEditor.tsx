import { useRef } from 'react';
import { useT } from '../../i18n/useI18n';
import NLAssistant from './NLAssistant';

interface Props {
  value: string;
  onChange: (val: string) => void;
  columns: string[];
  nodeType: string;
  fieldName: string;
  rows?: number;
}

export default function PromptTemplateEditor({ value, onChange, columns, nodeType, fieldName, rows = 4 }: Props) {
  const t = useT();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const insertColumn = (col: string) => {
    const el = textareaRef.current;
    if (!el) return;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const text = value || '';
    const insertion = `{${col}}`;
    const next = text.slice(0, start) + insertion + text.slice(end);
    onChange(next);
    // Restore cursor after insertion
    requestAnimationFrame(() => {
      el.selectionStart = el.selectionEnd = start + insertion.length;
      el.focus();
    });
  };

  return (
    <div className="space-y-2">
      {/* Column chips */}
      {columns.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {columns.map((col) => (
            <button
              key={col}
              onClick={() => insertColumn(col)}
              className="px-1.5 py-0.5 text-[10px] bg-blue-500/20 text-blue-300 rounded
                         hover:bg-blue-500/30 transition-colors border border-blue-500/30"
              title={`Insert {${col}}`}
            >
              {col}
            </button>
          ))}
        </div>
      )}

      <textarea
        ref={textareaRef}
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        placeholder={t(`nl.${fieldName}`, '')}
        rows={rows}
        className="w-full px-3 py-2 text-sm bg-[#0f172a] border border-[#334155] rounded-md
                   text-[#e2e8f0] placeholder-[#475569] focus:border-blue-500 focus:outline-none
                   font-mono resize-y"
      />

      <NLAssistant
        nodeType={nodeType}
        fieldName={fieldName}
        columns={columns}
        onResult={(result) => {
          if (typeof result === 'string') onChange(result);
        }}
      />
    </div>
  );
}
