import { useEffect, useRef, useState, useMemo } from 'react';
import { usePipelineStore } from '../store/pipelineStore';
import { useT } from '../i18n/useI18n';
import { Eye, ChevronDown, ChevronUp, Trash2 } from 'lucide-react';

interface VisionProgressPanelProps {
  inline?: boolean;
}

export default function VisionProgressPanel({ inline }: VisionProgressPanelProps) {
  const t = useT();
  const logs = usePipelineStore((s) => s.aiDebugLogs);
  const clearLogs = usePipelineStore((s) => s.clearAiDebugLogs);
  const isRunning = usePipelineStore((s) => s.isRunning);
  const [collapsed, setCollapsed] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Build vision cards: group by image, show response results
  const visionCards = useMemo(() => {
    const cards: {
      filename: string;
      image_path: string;
      result?: Record<string, string>;
      phase: string;
      row: number;
      total: number;
    }[] = [];
    const seen = new Set<string>();

    // Process response logs first (they have results), then prompts for "in progress"
    const responseLogs = logs.filter((l) => l.image_path && l.phase === 'response');
    const promptLogs = logs.filter((l) => l.image_path && l.phase === 'prompt');

    for (const log of responseLogs) {
      const key = log.image_path!;
      if (seen.has(key)) continue;
      seen.add(key);
      cards.push({
        filename: log.filename || key.split('/').pop() || '',
        image_path: log.image_path!,
        result: log.result,
        phase: 'response',
        row: log.row,
        total: log.total,
      });
    }

    // Add currently-processing images (prompt sent, no response yet)
    for (const log of promptLogs) {
      const key = log.image_path!;
      if (seen.has(key)) continue;
      seen.add(key);
      cards.push({
        filename: log.filename || key.split('/').pop() || '',
        image_path: log.image_path!,
        phase: 'prompt',
        row: log.row,
        total: log.total,
      });
    }

    return cards;
  }, [logs]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [visionCards.length]);

  // Don't show if no vision logs
  if (visionCards.length === 0 && !isRunning) return null;
  if (visionCards.length === 0) return null;

  const completed = visionCards.filter((c) => c.phase === 'response').length;
  const total = visionCards.length > 0 ? visionCards[0].total : 0;

  // Card grid content (shared between inline and standalone)
  const cardGrid = (
    <div
      ref={scrollRef}
      className="flex-1 overflow-y-auto p-2 grid grid-cols-2 gap-2 auto-rows-min"
    >
      {visionCards.map((card, i) => (
        <div
          key={card.image_path + i}
          className={`flex gap-2 p-2 rounded-md border ${
            card.phase === 'prompt'
              ? 'border-violet-500/40 bg-violet-500/5 animate-pulse'
              : 'border-[#334155] bg-[#1e293b]'
          }`}
        >
          <div className="shrink-0 w-[80px] h-[60px] rounded overflow-hidden bg-[#0f172a] flex items-center justify-center">
            <img
              src={`/api/files/thumbnail?path=${encodeURIComponent(card.image_path)}`}
              alt={card.filename}
              className="w-full h-full object-cover"
              loading="lazy"
              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
            />
          </div>
          <div className="flex-1 min-w-0 overflow-hidden">
            <p className="text-[11px] font-medium text-[#e2e8f0] truncate" title={card.filename}>{card.filename}</p>
            {card.phase === 'prompt' && (
              <p className="text-[10px] text-violet-400 mt-0.5">{t('vision.analyzing')}</p>
            )}
            {card.phase === 'response' && card.result && (
              <div className="mt-0.5 space-y-0.5">
                {Object.entries(card.result).slice(0, 4).map(([key, val]) => (
                  <div key={key} className="flex gap-1 text-[10px] leading-tight">
                    <span className="text-[#64748b] shrink-0">{key}:</span>
                    <span className="text-emerald-400 truncate" title={val}>{val}</span>
                  </div>
                ))}
              </div>
            )}
            {card.phase === 'response' && !card.result && (
              <p className="text-[10px] text-[#475569] mt-0.5">{t('vision.noResult')}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );

  // Inline mode: just the card grid
  if (inline) {
    return <div className="h-full flex flex-col overflow-hidden">{cardGrid}</div>;
  }

  // Standalone mode
  return (
    <div className="bg-[#0f172a] border-t border-[#334155] flex flex-col"
         style={{ height: collapsed ? 32 : 280 }}>
      <div className="flex items-center justify-between px-3 py-1 border-b border-[#334155] shrink-0">
        <div className="flex items-center gap-2 text-xs text-[#94a3b8]">
          <Eye size={12} className="text-violet-400" />
          <span className="font-medium">{t('vision.title')}</span>
          <span className="text-[#475569]">({completed}/{total})</span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={clearLogs} className="p-1 text-[#64748b] hover:text-red-400 transition-colors" title={t('debug.clear')}>
            <Trash2 size={11} />
          </button>
          <button onClick={() => setCollapsed(!collapsed)} className="p-1 text-[#64748b] hover:text-[#94a3b8] transition-colors">
            {collapsed ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        </div>
      </div>
      {!collapsed && cardGrid}
    </div>
  );
}
