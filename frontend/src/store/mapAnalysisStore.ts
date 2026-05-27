import { create } from 'zustand';

/** Supplement crop metadata */
export interface SupplementMeta {
  field: string;
  reason: string;
  value: string;
  confident: boolean;
}

/** A region (text/border/map_sample) on a map image */
export interface MapRegion {
  label: string;
  type: 'text' | 'border' | 'coordinate_strip' | 'map_sample';
  bbox: [number, number, number, number]; // [x%, y%, w%, h%]
  cropPath?: string;
  position?: string;
  promptPreview?: string;
  llmOutput?: string;
  supplementMeta?: SupplementMeta;
  status: 'pending' | 'processing' | 'done' | 'error';
}

/** Phase transition record */
export interface PhaseRecord {
  phase: string;
  ts: number;  // Date.now()
}

/** Critic audit entry per field */
export interface CriticAuditEntry {
  evidence: string;   // 'directly_visible' | 'inferred_correct' | 'inferred_questionable' | 'from_external_knowledge' | 'cannot_verify'
  note: string;
}

/** One map being analyzed (one row in the pipeline) */
export interface MapEntry {
  row: number;
  total: number;
  filename: string;
  sourceImage?: string;       // absolute path to source image
  previewPath?: string;       // region preview PNG path
  regions: MapRegion[];
  phase: string;              // current phase: L1_scan, L2a_ocr, etc.
  phaseHistory: PhaseRecord[]; // all phase transitions with timestamps
  done: boolean;
  fieldsFilled?: number;
  synthesisResult?: Record<string, string>; // final structured output from synthesis
  tokenUsage?: { input_tokens: number; output_tokens: number; total_tokens: number };
  postProcessRefined?: string[];  // fields refined by post-processing
  criticAudit?: Record<string, CriticAuditEntry>;   // critic verdict per field
  criticCorrections?: Array<{ field: string; oldValue: string; note: string }>;  // demoted fields
}

interface MapAnalysisState {
  maps: Record<string, MapEntry>;  // keyed by filename
  activePanels: string[];          // filenames of open panels
  selectedRegion: { filename: string; label: string } | null;
  fullscreen: boolean;
  expectedTotal: number;           // total maps expected (from first SSE event)
  postProcessPhase: 'idle' | 'running' | 'done'; // post-processing status

  // Actions
  updateMap: (filename: string, update: Partial<MapEntry>) => void;
  addOrUpdateRegion: (filename: string, region: Partial<MapRegion> & { label: string }) => void;
  openPanel: (filename: string) => void;
  closePanel: (filename: string) => void;
  selectRegion: (filename: string, label: string) => void;
  clearSelection: () => void;
  setFullscreen: (v: boolean) => void;
  setExpectedTotal: (n: number) => void;
  setPostProcessPhase: (p: 'idle' | 'running' | 'done') => void;
  clear: () => void;
}

export const useMapAnalysisStore = create<MapAnalysisState>((set, get) => ({
  maps: {},
  activePanels: [],
  selectedRegion: null,
  fullscreen: false,
  expectedTotal: 0,
  postProcessPhase: 'idle',

  updateMap: (filename, update) => {
    const { maps } = get();
    const existing = maps[filename] || {
      row: 0, total: 0, filename, regions: [], phase: '', phaseHistory: [], done: false,
    };
    // Track phase transitions
    if (update.phase && update.phase !== existing.phase) {
      existing.phaseHistory = [...existing.phaseHistory, { phase: update.phase, ts: Date.now() }];
    }
    set({
      maps: {
        ...maps,
        [filename]: { ...existing, ...update },
      },
    });
  },

  addOrUpdateRegion: (filename, regionUpdate) => {
    const { maps } = get();
    const entry = maps[filename];
    if (!entry) return;

    const idx = entry.regions.findIndex((r) => r.label === regionUpdate.label);
    let newRegions: MapRegion[];
    if (idx >= 0) {
      newRegions = [...entry.regions];
      newRegions[idx] = { ...newRegions[idx], ...regionUpdate };
    } else {
      const defaults: MapRegion = {
        label: regionUpdate.label,
        type: 'text',
        bbox: [0, 0, 100, 100],
        status: 'pending',
      };
      newRegions = [
        ...entry.regions,
        { ...defaults, ...regionUpdate } as MapRegion,
      ];
    }
    set({
      maps: {
        ...maps,
        [filename]: { ...entry, regions: newRegions },
      },
    });
  },

  openPanel: (filename) => {
    const { activePanels } = get();
    if (!activePanels.includes(filename)) {
      set({ activePanels: [...activePanels, filename] });
    }
  },

  closePanel: (filename) => {
    set({
      activePanels: get().activePanels.filter((f) => f !== filename),
      selectedRegion:
        get().selectedRegion?.filename === filename ? null : get().selectedRegion,
    });
  },

  selectRegion: (filename, label) => {
    set({ selectedRegion: { filename, label } });
  },

  clearSelection: () => set({ selectedRegion: null }),

  setFullscreen: (v) => set({ fullscreen: v }),

  setExpectedTotal: (n) => set({ expectedTotal: n }),

  setPostProcessPhase: (p) => set({ postProcessPhase: p }),

  clear: () => set({ maps: {}, activePanels: [], selectedRegion: null, fullscreen: false, expectedTotal: 0, postProcessPhase: 'idle' }),
}));
