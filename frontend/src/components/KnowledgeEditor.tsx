import { useEffect, useState, useCallback } from 'react';
import { useT } from '../i18n/useI18n';
import {
  Save, Trash2, Plus, RotateCcw, Check, AlertCircle,
  ChevronDown, ChevronRight, BookOpen,
} from 'lucide-react';

interface KnowledgeEntry {
  id: string;
  title: string;
  phases: string[];
  category: string;
  content: string;
}

interface PhasesMap {
  [key: string]: string;
}

/** Phase badge colors */
const PHASE_COLORS: Record<string, string> = {
  extract: 'bg-sky-500/20 text-sky-400 border-sky-500/30',
  critic: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
};

const CATEGORY_COLORS: Record<string, string> = {
  border: 'text-blue-400',
  identification: 'text-sky-400',
  coordinates: 'text-cyan-400',
  features: 'text-emerald-400',
  quality: 'text-pink-400',
};

/** Single knowledge entry card */
function EntryCard({
  entry,
  phases,
  onSave,
  onDelete,
}: {
  entry: KnowledgeEntry;
  phases: PhasesMap;
  onSave: (id: string, data: Partial<KnowledgeEntry>) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  const [title, setTitle] = useState(entry.title);
  const [content, setContent] = useState(entry.content);
  const [category, setCategory] = useState(entry.category);
  const [selectedPhases, setSelectedPhases] = useState<string[]>(entry.phases);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const isDirty =
    title !== entry.title ||
    content !== entry.content ||
    category !== entry.category ||
    JSON.stringify(selectedPhases.sort()) !== JSON.stringify([...entry.phases].sort());

  // Sync when entry reloads
  useEffect(() => {
    setTitle(entry.title);
    setContent(entry.content);
    setCategory(entry.category);
    setSelectedPhases(entry.phases);
  }, [entry.title, entry.content, entry.category, JSON.stringify(entry.phases)]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      await onSave(entry.id, { title, content, category, phases: selectedPhases });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }, [entry.id, title, content, category, selectedPhases, onSave]);

  const handleDelete = useCallback(async () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      setTimeout(() => setConfirmDelete(false), 3000);
      return;
    }
    await onDelete(entry.id);
  }, [entry.id, confirmDelete, onDelete]);

  const togglePhase = (phase: string) => {
    setSelectedPhases((prev) =>
      prev.includes(phase)
        ? prev.filter((p) => p !== phase)
        : [...prev, phase]
    );
  };

  return (
    <div className="border border-[#334155] rounded-lg bg-[#1e293b]/50 transition-colors">
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
        <BookOpen size={11} className="text-[#475569] shrink-0" />
        <span className="text-[11px] text-[#e2e8f0] flex-1 truncate">{entry.title}</span>

        {/* Phase badges */}
        <div className="flex items-center gap-1 shrink-0">
          {entry.phases.map((p) => (
            <span
              key={p}
              className={`text-[8px] px-1 py-0.5 rounded border ${PHASE_COLORS[p] || 'bg-slate-500/20 text-slate-400 border-slate-500/30'}`}
            >
              {p}
            </span>
          ))}
        </div>

        {entry.category && (
          <span className={`text-[9px] shrink-0 ${CATEGORY_COLORS[entry.category] || 'text-slate-400'}`}>
            {entry.category}
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
          {/* Title */}
          <div>
            <label className="text-[9px] text-[#475569] block mb-0.5">{t('kb.entryTitle')}</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-[#0f172a] border border-[#334155] rounded text-[11px] text-[#cbd5e1] px-2 py-1 focus:border-blue-500/50 focus:outline-none transition-colors"
            />
          </div>

          {/* Category */}
          <div>
            <label className="text-[9px] text-[#475569] block mb-0.5">{t('kb.category')}</label>
            <input
              type="text"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="e.g. border, coordinates, features"
              className="w-full bg-[#0f172a] border border-[#334155] rounded text-[11px] text-[#cbd5e1] px-2 py-1 focus:border-blue-500/50 focus:outline-none transition-colors"
            />
          </div>

          {/* Phase toggles */}
          <div>
            <label className="text-[9px] text-[#475569] block mb-1">{t('kb.phases')}</label>
            <div className="flex flex-wrap gap-1">
              {Object.entries(phases).map(([key, desc]) => {
                const active = selectedPhases.includes(key);
                return (
                  <button
                    key={key}
                    onClick={() => togglePhase(key)}
                    title={desc}
                    className={`text-[9px] px-2 py-0.5 rounded border transition-colors ${
                      active
                        ? PHASE_COLORS[key] || 'bg-blue-500/20 text-blue-400 border-blue-500/30'
                        : 'border-[#334155] text-[#475569] hover:text-[#94a3b8] hover:border-[#475569]'
                    }`}
                  >
                    {key}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Content editor */}
          <div>
            <label className="text-[9px] text-[#475569] block mb-0.5">{t('kb.content')}</label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="w-full bg-[#0f172a] border border-[#334155] rounded text-[11px] text-[#cbd5e1] font-mono p-2 leading-relaxed resize-y focus:border-blue-500/50 focus:outline-none transition-colors"
              style={{ minHeight: 100, maxHeight: 400 }}
              spellCheck={false}
            />
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={handleSave}
              disabled={!isDirty || saving}
              className="flex items-center gap-1 text-[10px] px-2.5 py-1 rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              {saved ? <Check size={10} /> : <Save size={10} />}
              {saved ? t('prompts.saved') : t('prompts.save')}
            </button>
            <button
              onClick={handleDelete}
              className={`flex items-center gap-1 text-[10px] px-2.5 py-1 rounded border transition-colors ${
                confirmDelete
                  ? 'border-red-500 text-red-400 bg-red-500/10'
                  : 'border-[#334155] text-[#94a3b8] hover:text-red-400 hover:border-red-500/50'
              }`}
            >
              <Trash2 size={10} />
              {confirmDelete ? t('kb.confirmDelete') : t('kb.delete')}
            </button>
            {isDirty && (
              <button
                onClick={() => {
                  setTitle(entry.title);
                  setContent(entry.content);
                  setCategory(entry.category);
                  setSelectedPhases(entry.phases);
                }}
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

export default function KnowledgeEditor() {
  const t = useT();
  const [entries, setEntries] = useState<KnowledgeEntry[]>([]);
  const [phases, setPhases] = useState<PhasesMap>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterPhase, setFilterPhase] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const resp = await fetch('/api/map-knowledge/');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setEntries(data.entries);
      setPhases(data.phases);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSave = useCallback(async (id: string, data: Partial<KnowledgeEntry>) => {
    const resp = await fetch(`/api/map-knowledge/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    await loadData();
  }, [loadData]);

  const handleDelete = useCallback(async (id: string) => {
    const resp = await fetch(`/api/map-knowledge/${id}`, {
      method: 'DELETE',
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    await loadData();
  }, [loadData]);

  const handleCreate = useCallback(async () => {
    setAdding(true);
    try {
      const resp = await fetch('/api/map-knowledge/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: 'New Knowledge Entry',
          phases: ['extract'],
          category: '',
          content: '',
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await loadData();
    } finally {
      setAdding(false);
    }
  }, [loadData]);

  const handleResetAll = useCallback(async () => {
    const resp = await fetch('/api/map-knowledge/reset', {
      method: 'POST',
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    await loadData();
  }, [loadData]);

  // Phase counts for filter
  const phaseCounts: Record<string, number> = {};
  for (const entry of entries) {
    for (const p of entry.phases) {
      phaseCounts[p] = (phaseCounts[p] || 0) + 1;
    }
  }

  const filtered = filterPhase
    ? entries.filter((e) => e.phases.includes(filterPhase))
    : entries;

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
      {/* Top bar: phase filter + actions */}
      <div className="flex items-center justify-between px-3 py-1.5 shrink-0 border-b border-[#1e293b]">
        <div className="flex items-center gap-1 overflow-x-auto">
          <button
            onClick={() => setFilterPhase(null)}
            className={`text-[10px] px-2 py-0.5 rounded whitespace-nowrap transition-colors ${
              filterPhase === null
                ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                : 'text-[#64748b] hover:text-[#94a3b8]'
            }`}
          >
            {t('kb.all')} ({entries.length})
          </button>
          {Object.keys(phases).map((phase) => {
            const count = phaseCounts[phase] || 0;
            const colors = PHASE_COLORS[phase]?.split(' ') || [];
            const textColor = colors[1] || 'text-slate-400';
            return (
              <button
                key={phase}
                onClick={() => setFilterPhase(phase === filterPhase ? null : phase)}
                className={`text-[10px] px-2 py-0.5 rounded whitespace-nowrap transition-colors ${
                  filterPhase === phase
                    ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                    : `${textColor} opacity-60 hover:opacity-100`
                }`}
              >
                {phase} ({count})
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={handleCreate}
            disabled={adding}
            className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded bg-emerald-600/80 text-white hover:bg-emerald-500 disabled:opacity-50 transition-colors"
          >
            <Plus size={9} />
            {t('kb.add')}
          </button>
          <button
            onClick={handleResetAll}
            className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border border-[#334155] text-[#94a3b8] hover:text-white hover:border-red-500/50 transition-colors"
          >
            <RotateCcw size={9} />
            {t('kb.resetAll')}
          </button>
        </div>
      </div>

      {/* Entry list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {filtered.length === 0 ? (
          <div className="text-center text-[#475569] text-xs py-8">
            {t('kb.empty')}
          </div>
        ) : (
          filtered.map((entry) => (
            <EntryCard
              key={entry.id}
              entry={entry}
              phases={phases}
              onSave={handleSave}
              onDelete={handleDelete}
            />
          ))
        )}
      </div>
    </div>
  );
}
