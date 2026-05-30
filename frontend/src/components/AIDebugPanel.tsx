import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { usePipelineStore } from '../store/pipelineStore';
import { useT } from '../i18n/useI18n';
import { Bug, Trash2, ChevronDown, ChevronUp, Download, Archive, FileText, Map as MapIcon } from 'lucide-react';

interface AIDebugPanelProps {
  inline?: boolean;
}

type LogEntry = {
  ts: number;
  row: number;
  total: number;
  phase: string;
  text: string;
  image_path?: string;
  filename?: string;
  result?: Record<string, string>;
  raw?: Record<string, any>;
};

/** Download current logs as JSON */
function downloadLogsAsJson(logs: LogEntry[]) {
  const blob = new Blob(
    [JSON.stringify(logs, null, 2)],
    { type: 'application/json' },
  );
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `debug_logs_${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

/** Group logs by filename (map) */
function groupByMap(logs: LogEntry[]): Map<string, LogEntry[]> {
  const groups = new window.Map<string, LogEntry[]>();
  for (const log of logs) {
    const key = log.filename || log.raw?.filename || '_unknown';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(log);
  }
  return groups;
}

/** Prompt viewer modal */
function PromptViewer({ path, onClose }: { path: string; onClose: () => void }) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/files/map-debug/prompt?path=${encodeURIComponent(path)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.text();
      })
      .then(setContent)
      .catch((e) => setError(e.message));
  }, [path]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="bg-[#1e293b] border border-[#334155] rounded-lg shadow-2xl w-[90vw] max-w-4xl max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-2 border-b border-[#334155] shrink-0">
          <div className="flex items-center gap-2 text-xs text-[#94a3b8]">
            <FileText size={12} />
            <span className="font-mono">{path.split(/[\\/]/).pop()}</span>
          </div>
          <button onClick={onClose} className="text-[#64748b] hover:text-[#e2e8f0] text-sm px-2">&#x2715;</button>
        </div>
        <div className="flex-1 overflow-auto p-4">
          {error && <div className="text-red-400 text-xs">Error: {error}</div>}
          {content === null && !error && <div className="text-[#475569] text-xs">Loading...</div>}
          {content !== null && (
            <pre className="text-[11px] text-[#cbd5e1] font-mono whitespace-pre-wrap break-all leading-relaxed">
              {content}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

/** Phase badge for visual grouping of log entries */
function PhaseBadge({ phase }: { phase: string }) {
  const bg = phaseBgColor(phase);
  const label = phaseLabel(phase);
  return (
    <span className={`inline-block text-[9px] px-1.5 py-0.5 rounded font-medium mr-1.5 ${bg}`}>
      {label}
    </span>
  );
}

export default function AIDebugPanel({ inline }: AIDebugPanelProps) {
  const t = useT();
  const logs = usePipelineStore((s) => s.aiDebugLogs);
  const clearLogs = usePipelineStore((s) => s.clearAiDebugLogs);
  const isRunning = usePipelineStore((s) => s.isRunning);
  const [collapsed, setCollapsed] = useState(false);
  const [promptPath, setPromptPath] = useState<string | null>(null);
  const [selectedMap, setSelectedMap] = useState<string | null>(null); // null = show all
  const [expandedMaps, setExpandedMaps] = useState<Set<string>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

  // Group logs by map
  const grouped = useMemo(() => groupByMap(logs), [logs]);
  const mapNames = useMemo(() => Array.from(grouped.keys()), [grouped]);

  // Auto-expand latest map
  useEffect(() => {
    if (mapNames.length > 0) {
      const latest = mapNames[mapNames.length - 1];
      setExpandedMaps((prev) => {
        const next = new Set(prev);
        next.add(latest);
        return next;
      });
    }
  }, [mapNames.length]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs.length]);

  const handleDownload = useCallback(() => downloadLogsAsJson(logs), [logs]);

  const handleArchiveDownload = useCallback(async () => {
    try {
      const resp = await fetch('/api/files/map-debug/archives');
      const data = await resp.json();
      if (data.archives && data.archives.length > 0) {
        const latest = data.archives[0];
        window.open(`/api/files/map-debug/archive?path=${encodeURIComponent(latest.path)}`, '_blank');
      } else {
        alert('No debug archives found. Run a map analysis first.');
      }
    } catch {
      alert('Failed to fetch archives');
    }
  }, []);

  const toggleMapExpanded = useCallback((mapName: string) => {
    setExpandedMaps((prev) => {
      const next = new Set(prev);
      if (next.has(mapName)) next.delete(mapName);
      else next.add(mapName);
      return next;
    });
  }, []);

  if (logs.length === 0 && !isRunning) return null;

  const renderLogEntry = (log: LogEntry, i: number) => {
    const p = log.phase || '';
    const color = phaseColor(p);
    const rawPromptPath = log.raw?.prompt_path as string | undefined;
    return (
      <div key={i} className={`py-0.5 ${color} group`}>
        <PhaseBadge phase={p} />
        <span className="whitespace-pre-wrap break-all">{log.text}</span>
        {rawPromptPath && (
          <button
            onClick={() => setPromptPath(rawPromptPath)}
            className="ml-2 text-[9px] px-1.5 py-0.5 rounded bg-[#1e293b] border border-[#334155] text-blue-400 hover:text-blue-300 hover:border-blue-500/50 transition-colors opacity-0 group-hover:opacity-100"
            title="View full prompt"
          >
            <FileText size={9} className="inline mr-0.5" />
            prompt
          </button>
        )}
      </div>
    );
  };

  /** Render a single map group */
  const renderMapGroup = (mapName: string, mapLogs: LogEntry[]) => {
    const isExpanded = expandedMaps.has(mapName);
    const shortName = mapName.replace(/\.[^/.]+$/, ''); // strip extension
    const phasesSeen = new Set(mapLogs.map((l) => l.phase));
    const hasError = phasesSeen.has('error');
    const isDone = phasesSeen.has('done');

    return (
      <div key={mapName} className="border-b border-[#1e293b] last:border-b-0">
        <button
          onClick={() => toggleMapExpanded(mapName)}
          className="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-[#1e293b]/50 transition-colors text-left"
        >
          {isExpanded ? <ChevronDown size={10} className="text-[#475569] shrink-0" /> : <ChevronUp size={10} className="text-[#475569] shrink-0 rotate-90" />}
          <MapIcon size={10} className={`shrink-0 ${hasError ? 'text-red-400' : isDone ? 'text-emerald-400' : 'text-blue-400'}`} />
          <span className="text-[11px] text-[#e2e8f0] font-medium truncate flex-1">{shortName}</span>
          <span className="text-[9px] text-[#475569] shrink-0">{mapLogs.length} {t('debug.entries')}</span>
          {hasError && <span className="text-[8px] px-1 py-0.5 rounded bg-red-500/20 text-red-400">ERR</span>}
          {isDone && !hasError && <span className="text-[8px] px-1 py-0.5 rounded bg-emerald-500/20 text-emerald-400">OK</span>}
        </button>
        {isExpanded && (
          <div className="pl-5 pr-2 pb-1 space-y-0.5">
            {mapLogs.map(renderLogEntry)}
          </div>
        )}
      </div>
    );
  };

  // Filter logs based on selectedMap
  const visibleGroups = selectedMap
    ? [[selectedMap, grouped.get(selectedMap) || []] as [string, LogEntry[]]]
    : Array.from(grouped.entries());

  const toolbarButtons = (
    <div className="flex items-center gap-1">
      <button
        onClick={handleArchiveDownload}
        className="p-1 text-[#64748b] hover:text-blue-400 transition-colors"
        title="Download server archive"
      >
        <Archive size={11} />
      </button>
      <button
        onClick={handleDownload}
        className="p-1 text-[#64748b] hover:text-blue-400 transition-colors"
        title="Download logs as JSON"
      >
        <Download size={11} />
      </button>
      <button onClick={clearLogs} className="p-1 text-[#64748b] hover:text-red-400 transition-colors" title={t('debug.clear')}>
        <Trash2 size={11} />
      </button>
    </div>
  );

  // Inline mode (used in BottomPanelManager tab)
  if (inline) {
    return (
      <div className="h-full flex flex-col overflow-hidden">
        {/* Map filter bar */}
        <div className="flex items-center justify-between px-3 py-1 shrink-0 border-b border-[#1e293b]">
          <div className="flex items-center gap-1 flex-1 min-w-0 overflow-x-auto">
            <button
              onClick={() => setSelectedMap(null)}
              className={`text-[10px] px-2 py-0.5 rounded whitespace-nowrap transition-colors ${
                selectedMap === null
                  ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                  : 'text-[#64748b] hover:text-[#94a3b8]'
              }`}
            >
              {t('debug.allMaps')} ({mapNames.length})
            </button>
            {mapNames.map((name) => {
              const shortName = name.replace(/\.[^/.]+$/, '');
              const mapLogs = grouped.get(name) || [];
              const hasErr = mapLogs.some((l) => l.phase === 'error');
              return (
                <button
                  key={name}
                  onClick={() => setSelectedMap(name === selectedMap ? null : name)}
                  className={`text-[10px] px-2 py-0.5 rounded whitespace-nowrap transition-colors max-w-[120px] truncate ${
                    selectedMap === name
                      ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                      : hasErr
                        ? 'text-red-400/70 hover:text-red-400'
                        : 'text-[#64748b] hover:text-[#94a3b8]'
                  }`}
                  title={name}
                >
                  {shortName}
                </button>
              );
            })}
          </div>
          {toolbarButtons}
        </div>
        {/* Log content grouped by map */}
        <div className="flex-1 overflow-y-auto font-mono text-[11px] leading-relaxed">
          {visibleGroups.map(([mapName, mapLogs]) =>
            renderMapGroup(mapName, mapLogs)
          )}
          <div ref={bottomRef} />
        </div>
        {promptPath && <PromptViewer path={promptPath} onClose={() => setPromptPath(null)} />}
      </div>
    );
  }

  // Standalone mode
  return (
    <div className="bg-[#0f172a] border-t border-[#334155] flex flex-col"
         style={{ height: collapsed ? 32 : 280 }}>
      <div className="flex items-center justify-between px-3 py-1 border-b border-[#334155] shrink-0">
        <div className="flex items-center gap-2 text-xs text-[#94a3b8]">
          <Bug size={12} className="text-amber-400" />
          <span className="font-medium">{t('debug.title')}</span>
          <span className="text-[#475569]">({logs.length})</span>
        </div>
        <div className="flex items-center gap-1">
          {toolbarButtons}
          <button onClick={() => setCollapsed(!collapsed)} className="p-1 text-[#64748b] hover:text-[#94a3b8] transition-colors">
            {collapsed ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        </div>
      </div>
      {!collapsed && (
        <>
          {/* Map filter */}
          <div className="flex items-center gap-1 px-3 py-1 overflow-x-auto shrink-0 border-b border-[#1e293b]">
            <button
              onClick={() => setSelectedMap(null)}
              className={`text-[10px] px-2 py-0.5 rounded whitespace-nowrap ${
                selectedMap === null ? 'bg-blue-500/20 text-blue-400' : 'text-[#64748b] hover:text-[#94a3b8]'
              }`}
            >
              {t('debug.allMaps')}
            </button>
            {mapNames.map((name) => (
              <button
                key={name}
                onClick={() => setSelectedMap(name === selectedMap ? null : name)}
                className={`text-[10px] px-2 py-0.5 rounded whitespace-nowrap max-w-[100px] truncate ${
                  selectedMap === name ? 'bg-blue-500/20 text-blue-400' : 'text-[#64748b] hover:text-[#94a3b8]'
                }`}
                title={name}
              >
                {name.replace(/\.[^/.]+$/, '')}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto font-mono text-[11px] leading-relaxed">
            {visibleGroups.map(([mapName, mapLogs]) =>
              renderMapGroup(mapName, mapLogs)
            )}
            <div ref={bottomRef} />
          </div>
        </>
      )}
      {promptPath && <PromptViewer path={promptPath} onClose={() => setPromptPath(null)} />}
    </div>
  );
}

function phaseColor(p: string): string {
  if (p === 'error' || p === 'evidence_preview_error') return 'text-red-400';
  if (p === 'response' || p === 'done') return 'text-emerald-400';
  if (p === 'extract_start' || p === 'extract_result') return 'text-sky-400';
  if (p === 'critic_start' || p === 'critic_review') return 'text-amber-400';
  if (p === 'correction_sent' || p === 'correction_result') return 'text-violet-400';
  if (p === 'evidence_preview' || p === 'region_preview') return 'text-green-400';
  if (p === 'debug_archive') return 'text-indigo-400';
  return 'text-[#94a3b8]';
}

function phaseBgColor(p: string): string {
  if (p === 'error' || p === 'evidence_preview_error') return 'bg-red-500/15 text-red-400';
  if (p === 'done') return 'bg-emerald-500/15 text-emerald-400';
  if (p === 'extract_start' || p === 'extract_result') return 'bg-sky-500/15 text-sky-400';
  if (p === 'critic_start' || p === 'critic_review') return 'bg-amber-500/15 text-amber-400';
  if (p === 'correction_sent' || p === 'correction_result') return 'bg-violet-500/15 text-violet-400';
  if (p === 'evidence_preview' || p === 'region_preview') return 'bg-green-500/15 text-green-400';
  if (p === 'debug_archive') return 'bg-indigo-500/15 text-indigo-400';
  return 'bg-slate-500/15 text-[#94a3b8]';
}

function phaseLabel(p: string): string {
  const map: Record<string, string> = {
    'extract_start': 'Extract',
    'extract_result': 'Extract',
    'critic_start': 'Critic',
    'critic_review': 'Critic',
    'correction_sent': 'Correct',
    'correction_result': 'Correct',
    'evidence_preview': 'Preview',
    'evidence_preview_error': 'Error',
    'region_preview': 'Preview',
    'done': 'Done',
    'error': 'Error',
    'debug_archive': 'Archive',
  };
  return map[p] || p;
}
