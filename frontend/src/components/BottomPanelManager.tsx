// @refresh reset
import { useState, useRef, useCallback, useEffect } from 'react';
import { usePipelineStore } from '../store/pipelineStore';
import { useMapAnalysisStore } from '../store/mapAnalysisStore';
import { useT } from '../i18n/useI18n';
import { Table2, Eye, Bug, MapPin, ChevronDown, ChevronUp, GripHorizontal, FileEdit, BookOpen, Crosshair } from 'lucide-react';
import DataTable from './DataTable';
import VisionProgressPanel from './VisionProgressPanel';
import AIDebugPanel from './AIDebugPanel';
import MapAnalysisPanel from './MapAnalysisPanel';
import PromptEditor from './PromptEditor';
import KnowledgeEditor from './KnowledgeEditor';
import FewShotAnnotator from './FewShotAnnotator';

type TabId = 'data' | 'vision' | 'map' | 'debug' | 'prompts' | 'knowledge' | 'fewshot';

interface TabDef {
  id: TabId;
  icon: React.ReactNode;
  labelKey: string;
  badge?: () => string | null;
}

const TAB_DEFS: TabDef[] = [
  {
    id: 'data',
    icon: <Table2 size={12} />,
    labelKey: 'live.title',
    badge: () => {
      const lp = usePipelineStore.getState().livePreview;
      return lp ? `${lp.total_rows}` : null;
    },
  },
  {
    id: 'map',
    icon: <MapPin size={12} />,
    labelKey: 'Map Analysis',
    badge: () => {
      const maps = useMapAnalysisStore.getState().maps;
      const count = Object.keys(maps).length;
      return count > 0 ? `${count}` : null;
    },
  },
  {
    id: 'vision',
    icon: <Eye size={12} />,
    labelKey: 'vision.title',
  },
  {
    id: 'debug',
    icon: <Bug size={12} />,
    labelKey: 'debug.title',
    badge: () => {
      const count = usePipelineStore.getState().aiDebugLogs.length;
      return count > 0 ? `${count}` : null;
    },
  },
  {
    id: 'prompts',
    icon: <FileEdit size={12} />,
    labelKey: 'prompts.title',
  },
  {
    id: 'knowledge',
    icon: <BookOpen size={12} />,
    labelKey: 'kb.title',
  },
  {
    id: 'fewshot',
    icon: <Crosshair size={12} />,
    labelKey: 'fewshot.title',
  },
];

const STORAGE_KEY = 'tf-bottom-panel';

function loadPrefs(): { height: number; collapsed: boolean; activeTab: TabId } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { height: 280, collapsed: true, activeTab: 'data' };
}

function savePrefs(prefs: { height: number; collapsed: boolean; activeTab: TabId }) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs)); } catch { /* ignore */ }
}

export default function BottomPanelManager() {
  const t = useT();
  const liveData = usePipelineStore((s) => s.livePreview);
  const logs = usePipelineStore((s) => s.aiDebugLogs);
  const maps = useMapAnalysisStore((s) => s.maps);
  const isRunning = usePipelineStore((s) => s.isRunning);

  const prefs = loadPrefs();
  const [activeTab, setActiveTab] = useState<TabId>(prefs.activeTab);
  const [collapsed, setCollapsed] = useState(prefs.collapsed);
  const [height, setHeight] = useState(prefs.height);
  const dragging = useRef(false);
  const startY = useRef(0);
  const startH = useRef(0);

  // Auto-show panel when data arrives
  const hasLiveData = liveData !== null;
  const hasMapData = Object.keys(maps).length > 0;

  useEffect(() => {
    if (hasLiveData) {
      setCollapsed(false);
      setActiveTab('data');
    }
  }, [hasLiveData]);

  useEffect(() => {
    if (hasMapData) {
      setCollapsed(false);
      setActiveTab('map');
      // Auto-enter fullscreen for map analysis
      useMapAnalysisStore.getState().setFullscreen(true);
    }
  }, [hasMapData]);

  // Save preferences
  useEffect(() => {
    savePrefs({ height, collapsed, activeTab });
  }, [height, collapsed, activeTab]);

  // Always show — user may want to edit prompts or view logs even before running

  // Drag resize
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    startY.current = e.clientY;
    startH.current = height;

    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const delta = startY.current - ev.clientY;
      const newH = Math.max(120, Math.min(600, startH.current + delta));
      setHeight(newH);
    };
    const onUp = () => {
      dragging.current = false;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }, [height]);

  const switchTab = (id: TabId) => {
    if (activeTab === id && !collapsed) {
      setCollapsed(true);
    } else {
      setActiveTab(id);
      setCollapsed(false);
      // Auto-fullscreen for Map Analysis tab
      if (id === 'map' && Object.keys(maps).length > 0) {
        useMapAnalysisStore.getState().setFullscreen(true);
      }
    }
  };

  // Get badge for a tab
  const getBadge = (tab: TabDef): string | null => {
    if (!tab.badge) return null;
    return tab.badge();
  };

  return (
    <div className="border-t border-[#334155] bg-[#0f172a] flex flex-col shrink-0"
         style={{ height: collapsed ? 33 : height }}>
      {/* Resize handle */}
      {!collapsed && (
        <div
          className="h-1 cursor-row-resize flex items-center justify-center hover:bg-blue-500/20 transition-colors group"
          onMouseDown={onMouseDown}
        >
          <GripHorizontal size={10} className="text-[#334155] group-hover:text-blue-400" />
        </div>
      )}

      {/* Tab bar */}
      <div className="flex items-center border-b border-[#334155] shrink-0 px-1">
        {TAB_DEFS.map((tab) => {
          const badge = getBadge(tab);
          const isActive = activeTab === tab.id && !collapsed;
          return (
            <button
              key={tab.id}
              onClick={() => switchTab(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-[11px] border-b-2 transition-colors ${
                isActive
                  ? 'border-blue-500 text-[#e2e8f0]'
                  : 'border-transparent text-[#64748b] hover:text-[#94a3b8]'
              }`}
            >
              {tab.icon}
              <span>{tab.labelKey.includes('.') ? t(tab.labelKey as any) : tab.labelKey}</span>
              {badge && (
                <span className={`text-[9px] px-1 py-0 rounded-full ${
                  isActive ? 'bg-blue-500/20 text-blue-300' : 'bg-[#334155] text-[#64748b]'
                }`}>
                  {badge}
                </span>
              )}
            </button>
          );
        })}

        <div className="flex-1" />

        <button
          onClick={() => setCollapsed(!collapsed)}
          className="p-1 text-[#64748b] hover:text-[#94a3b8] transition-colors"
        >
          {collapsed ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
      </div>

      {/* Tab content */}
      {!collapsed && (
        <div className="flex-1 overflow-hidden">
          {activeTab === 'data' && <LivePreviewInline />}
          {activeTab === 'vision' && <VisionProgressInline />}
          {activeTab === 'map' && <MapAnalysisPanelInline />}
          {activeTab === 'debug' && <AIDebugInline />}
          {activeTab === 'prompts' && <PromptEditor />}
          {activeTab === 'knowledge' && <KnowledgeEditor />}
          {activeTab === 'fewshot' && <FewShotAnnotator />}
        </div>
      )}
    </div>
  );
}

// ── Inline wrappers (render content without their own chrome/headers) ──

function LivePreviewInline() {
  const liveData = usePipelineStore((s) => s.livePreview);
  const isRunning = usePipelineStore((s) => s.isRunning);

  if (!liveData) {
    return <div className="flex items-center justify-center h-full text-[#475569] text-xs">No data preview available</div>;
  }

  const { columns, new_columns, rows, total_rows, processed_rows, partial_file } = liveData;
  const isProcessing = isRunning && processed_rows !== null && processed_rows < total_rows;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {isProcessing && (
        <div className="h-0.5 bg-[#1e293b] shrink-0">
          <div className="h-full bg-blue-500 transition-all duration-300" style={{ width: `${(processed_rows! / total_rows) * 100}%` }} />
        </div>
      )}
      <DataTable
        columns={columns}
        rows={rows}
        highlightColumns={new_columns}
        totalRows={total_rows}
        showSearch={rows.length > 20}
      />
      {partial_file && (
        <div className="shrink-0 px-3 py-1 border-t border-[#334155] flex items-center gap-2">
          <span className="text-[10px] text-amber-400">Partial results available</span>
          <button
            onClick={() => window.open(`/api/files/${partial_file}/download`, '_blank')}
            className="text-[10px] text-amber-400 underline hover:text-amber-300"
          >
            Download
          </button>
        </div>
      )}
    </div>
  );
}

function VisionProgressInline() {
  return <VisionProgressPanel inline />;
}

function AIDebugInline() {
  return <AIDebugPanel inline />;
}

function MapAnalysisPanelInline() {
  return <MapAnalysisPanel inline />;
}
