import { useEffect, useState, useCallback } from 'react';
import { useT } from '../i18n/useI18n';
import { Save, RotateCcw, Check, AlertCircle, ChevronDown, ChevronRight, Code2 } from 'lucide-react';

interface TemplateMeta {
  key: string;
  level: string;
  role: string;
  label: string;
  description: string;
  placeholders: string[];
  default: string;
  custom: string | null;
  is_custom: boolean;
  effective: string;
}

/** Level colors for visual grouping */
const LEVEL_COLORS: Record<string, string> = {
  L1: 'border-sky-500/30 bg-sky-500/5',
  L2a: 'border-amber-500/30 bg-amber-500/5',
  L2b: 'border-violet-500/30 bg-violet-500/5',
  L3: 'border-cyan-500/30 bg-cyan-500/5',
  Synthesis: 'border-pink-500/30 bg-pink-500/5',
  Post: 'border-indigo-500/30 bg-indigo-500/5',
  Direct: 'border-emerald-500/30 bg-emerald-500/5',
};

const LEVEL_TEXT_COLORS: Record<string, string> = {
  L1: 'text-sky-400',
  L2a: 'text-amber-400',
  L2b: 'text-violet-400',
  L3: 'text-cyan-400',
  Synthesis: 'text-pink-400',
  Post: 'text-indigo-400',
  Direct: 'text-emerald-400',
};

/** Single template editor card */
function TemplateCard({
  tmpl,
  onSave,
  onReset,
}: {
  tmpl: TemplateMeta;
  onSave: (key: string, content: string) => Promise<void>;
  onReset: (key: string) => Promise<void>;
}) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  const [value, setValue] = useState(tmpl.effective);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const isDirty = value !== tmpl.effective;
  const isModified = tmpl.is_custom;
  const levelColor = LEVEL_COLORS[tmpl.level] || 'border-slate-500/30 bg-slate-500/5';
  const levelText = LEVEL_TEXT_COLORS[tmpl.level] || 'text-slate-400';

  // Sync when template reloads
  useEffect(() => {
    setValue(tmpl.effective);
  }, [tmpl.effective]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      await onSave(tmpl.key, value);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }, [tmpl.key, value, onSave]);

  const handleReset = useCallback(async () => {
    await onReset(tmpl.key);
    setValue(tmpl.default);
  }, [tmpl.key, tmpl.default, onReset]);

  return (
    <div className={`border rounded-lg ${levelColor} transition-colors`}>
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-white/5 transition-colors rounded-t-lg"
      >
        {expanded ? (
          <ChevronDown size={12} className="text-[#64748b] shrink-0" />
        ) : (
          <ChevronRight size={12} className="text-[#64748b] shrink-0" />
        )}
        <span className={`text-[10px] font-bold ${levelText} shrink-0`}>{tmpl.level}</span>
        <span className="text-[10px] text-[#475569] shrink-0">{tmpl.role === 'system' ? 'SYS' : 'USR'}</span>
        <span className="text-[11px] text-[#e2e8f0] flex-1 truncate">{tmpl.label}</span>
        {isModified && (
          <span className="text-[8px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 shrink-0">
            {t('prompts.modified')}
          </span>
        )}
        {isDirty && (
          <span className="text-[8px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 shrink-0">
            {t('prompts.editing')}
          </span>
        )}
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          {/* Description */}
          <p className="text-[10px] text-[#64748b] leading-relaxed">{tmpl.description}</p>

          {/* Placeholders */}
          {tmpl.placeholders.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap">
              <Code2 size={10} className="text-[#475569] shrink-0" />
              <span className="text-[9px] text-[#475569] mr-1">{t('prompts.placeholders')}:</span>
              {tmpl.placeholders.map((ph) => (
                <span
                  key={ph}
                  className="text-[9px] px-1 py-0.5 rounded bg-[#0f172a] text-emerald-400 font-mono border border-[#1e293b]"
                >
                  {ph}
                </span>
              ))}
            </div>
          )}

          {/* Editor */}
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-full bg-[#0f172a] border border-[#334155] rounded text-[11px] text-[#cbd5e1] font-mono p-2 leading-relaxed resize-y focus:border-blue-500/50 focus:outline-none transition-colors"
            style={{ minHeight: 120, maxHeight: 500 }}
            spellCheck={false}
          />

          {/* Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={handleSave}
              disabled={!isDirty && !isModified || saving}
              className="flex items-center gap-1 text-[10px] px-2.5 py-1 rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              {saved ? <Check size={10} /> : <Save size={10} />}
              {saved ? t('prompts.saved') : t('prompts.save')}
            </button>
            {isModified && (
              <button
                onClick={handleReset}
                className="flex items-center gap-1 text-[10px] px-2.5 py-1 rounded border border-[#334155] text-[#94a3b8] hover:text-white hover:border-[#475569] transition-colors"
              >
                <RotateCcw size={10} />
                {t('prompts.reset')}
              </button>
            )}
            {isDirty && (
              <button
                onClick={() => setValue(tmpl.effective)}
                className="text-[10px] text-[#64748b] hover:text-[#94a3b8] transition-colors"
              >
                {t('prompts.noChanges')}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function PromptEditor() {
  const t = useT();
  const [templates, setTemplates] = useState<TemplateMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterLevel, setFilterLevel] = useState<string | null>(null);

  const loadTemplates = useCallback(async () => {
    try {
      const resp = await fetch('/api/prompt-templates/');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setTemplates(data.templates);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  const handleSave = useCallback(async (key: string, content: string) => {
    const resp = await fetch(`/api/prompt-templates/${key}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    await loadTemplates();
  }, [loadTemplates]);

  const handleReset = useCallback(async (key: string) => {
    const resp = await fetch(`/api/prompt-templates/${key}`, {
      method: 'DELETE',
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    await loadTemplates();
  }, [loadTemplates]);

  const handleResetAll = useCallback(async () => {
    const resp = await fetch('/api/prompt-templates/reset-all', {
      method: 'POST',
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    await loadTemplates();
  }, [loadTemplates]);

  // Get unique levels for filtering
  const levels = Array.from(new Set(templates.map((t) => t.level)));
  const hasCustom = templates.some((t) => t.is_custom);

  const filtered = filterLevel
    ? templates.filter((t) => t.level === filterLevel)
    : templates;

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-[#475569] text-xs">
        Loading...
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center text-red-400 text-xs gap-2">
        <AlertCircle size={14} />
        {error}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Top bar: level filter + reset all */}
      <div className="flex items-center justify-between px-3 py-1.5 shrink-0 border-b border-[#1e293b]">
        <div className="flex items-center gap-1 overflow-x-auto">
          <button
            onClick={() => setFilterLevel(null)}
            className={`text-[10px] px-2 py-0.5 rounded whitespace-nowrap transition-colors ${
              filterLevel === null
                ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                : 'text-[#64748b] hover:text-[#94a3b8]'
            }`}
          >
            All ({templates.length})
          </button>
          {levels.map((level) => {
            const textColor = LEVEL_TEXT_COLORS[level] || 'text-slate-400';
            const count = templates.filter((t) => t.level === level).length;
            return (
              <button
                key={level}
                onClick={() => setFilterLevel(level === filterLevel ? null : level)}
                className={`text-[10px] px-2 py-0.5 rounded whitespace-nowrap transition-colors ${
                  filterLevel === level
                    ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                    : `${textColor} opacity-60 hover:opacity-100`
                }`}
              >
                {level} ({count})
              </button>
            );
          })}
        </div>
        {hasCustom && (
          <button
            onClick={handleResetAll}
            className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border border-[#334155] text-[#94a3b8] hover:text-white hover:border-red-500/50 transition-colors shrink-0"
          >
            <RotateCcw size={9} />
            {t('prompts.resetAll')}
          </button>
        )}
      </div>

      {/* Template list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {filtered.map((tmpl) => (
          <TemplateCard
            key={tmpl.key}
            tmpl={tmpl}
            onSave={handleSave}
            onReset={handleReset}
          />
        ))}
      </div>
    </div>
  );
}
