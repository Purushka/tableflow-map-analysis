// @refresh reset
import { useState, useEffect, useRef, useCallback, type WheelEvent as ReactWheelEvent, type MouseEvent as ReactMouseEvent } from 'react';
import { useMapAnalysisStore, type MapRegion, type MapEntry, type SupplementMeta } from '../store/mapAnalysisStore';
import { X, Minimize2, Maximize2, MapPin, Eye, FileText, Scan, Expand, Shrink, ZoomIn, RefreshCw, CheckCircle, AlertCircle } from 'lucide-react';

/** Build a URL for serving a map crop or preview image */
function cropUrl(path: string): string {
  return `/api/files/map-preview?path=${encodeURIComponent(path)}`;
}

/** Build a URL for a source image thumbnail */
function sourceThumbUrl(path: string, size = 600): string {
  return `/api/files/map-source-thumb?path=${encodeURIComponent(path)}&size=${size}`;
}

/** Color for region type — supplement regions get orange */
function regionColor(type: string, isSupplement = false): string {
  if (isSupplement) return '#f97316'; // orange for supplement
  switch (type) {
    case 'text': return '#ef4444';                       // red
    case 'border': case 'coordinate_strip': return '#3b82f6'; // blue
    case 'map_sample': return '#22c55e';                 // green
    default: return '#a855f7';                           // purple
  }
}

function regionColorBg(type: string, isSupplement = false): string {
  if (isSupplement) return 'rgba(249,115,22,0.2)'; // orange bg
  switch (type) {
    case 'text': return 'rgba(239,68,68,0.15)';
    case 'border': case 'coordinate_strip': return 'rgba(59,130,246,0.15)';
    case 'map_sample': return 'rgba(34,197,94,0.15)';
    default: return 'rgba(168,85,247,0.15)';
  }
}

// ── Zoomable Image ───────────────────────────────────────────────────────────

/** A simple zoomable/pannable image wrapper. Scroll to zoom, drag to pan. */
function ZoomableImage({ src, alt, className }: { src: string; alt: string; className?: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const isPanning = useRef(false);
  const lastMouse = useRef({ x: 0, y: 0 });

  const handleWheel = useCallback((e: ReactWheelEvent) => {
    e.stopPropagation();
    const delta = e.deltaY > 0 ? -0.15 : 0.15;
    setScale((s) => Math.min(8, Math.max(1, s + delta * s)));
  }, []);

  // Reset pan when zooming back to 1x
  useEffect(() => {
    if (scale <= 1) setPan({ x: 0, y: 0 });
  }, [scale]);

  const handleMouseDown = useCallback((e: ReactMouseEvent) => {
    if (scale <= 1) return;
    e.preventDefault();
    isPanning.current = true;
    lastMouse.current = { x: e.clientX, y: e.clientY };
  }, [scale]);

  const handleMouseMove = useCallback((e: ReactMouseEvent) => {
    if (!isPanning.current) return;
    const dx = e.clientX - lastMouse.current.x;
    const dy = e.clientY - lastMouse.current.y;
    lastMouse.current = { x: e.clientX, y: e.clientY };
    setPan((p) => ({ x: p.x + dx, y: p.y + dy }));
  }, []);

  const handleMouseUp = useCallback(() => {
    isPanning.current = false;
  }, []);

  const resetZoom = useCallback(() => {
    setScale(1);
    setPan({ x: 0, y: 0 });
  }, []);

  return (
    <div
      ref={containerRef}
      className={`relative overflow-hidden ${className || ''}`}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      style={{ cursor: scale > 1 ? (isPanning.current ? 'grabbing' : 'grab') : 'default' }}
    >
      <img
        src={src}
        alt={alt}
        className="w-full h-full object-contain"
        draggable={false}
        style={{
          transform: `scale(${scale}) translate(${pan.x / scale}px, ${pan.y / scale}px)`,
          transformOrigin: 'center center',
          transition: isPanning.current ? 'none' : 'transform 0.1s ease-out',
        }}
      />
      {scale > 1.05 && (
        <button
          onClick={resetZoom}
          className="absolute top-1 right-1 z-10 px-1.5 py-0.5 rounded bg-[#0f172a]/80 text-[10px] text-[#94a3b8] hover:text-[#e2e8f0] transition-colors flex items-center gap-1"
          title="Reset zoom (double-click)"
        >
          <ZoomIn size={10} /> {scale.toFixed(1)}x
        </button>
      )}
    </div>
  );
}

// ── Image with correctly-positioned region overlays ──────────────────────────

interface ImageWithOverlaysProps {
  src: string;
  alt: string;
  regions: MapRegion[];
  selectedRegion?: { filename: string; label: string } | null;
  filename: string;
  onSelectRegion: (filename: string, label: string) => void;
  /** Fill the full container (for fullscreen mode) */
  fill?: boolean;
}

/**
 * Renders a map image with region overlay boxes that correctly track the
 * rendered image position, even when the image is letter-boxed by
 * object-contain. Supports scroll-wheel zoom and drag-to-pan.
 */
function ImageWithOverlays({
  src,
  alt,
  regions,
  selectedRegion,
  filename,
  onSelectRegion,
  fill,
}: ImageWithOverlaysProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [imgRect, setImgRect] = useState<{
    offsetX: number;
    offsetY: number;
    width: number;
    height: number;
  } | null>(null);
  const [hoveredRegion, setHoveredRegion] = useState<string | null>(null);

  // Zoom/pan state
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const isPanningRef = useRef(false);
  const lastMouseRef = useRef({ x: 0, y: 0 });

  const updateRect = useCallback(() => {
    const container = containerRef.current;
    const img = imgRef.current;
    if (!container || !img || !img.naturalWidth) return;

    const containerW = container.clientWidth;
    const containerH = container.clientHeight;
    const naturalW = img.naturalWidth;
    const naturalH = img.naturalHeight;

    // Reproduce object-contain math
    const scale = Math.min(containerW / naturalW, containerH / naturalH);
    const renderedW = naturalW * scale;
    const renderedH = naturalH * scale;
    const offsetX = (containerW - renderedW) / 2;
    const offsetY = (containerH - renderedH) / 2;

    setImgRect({ offsetX, offsetY, width: renderedW, height: renderedH });
  }, []);

  // Recalculate when image loads or container resizes
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(updateRect);
    ro.observe(container);
    return () => ro.disconnect();
  }, [updateRect]);

  // Reset pan when zoom returns to 1
  useEffect(() => {
    if (zoom <= 1) setPan({ x: 0, y: 0 });
  }, [zoom]);

  const handleWheel = useCallback((e: ReactWheelEvent) => {
    e.stopPropagation();
    const delta = e.deltaY > 0 ? -0.15 : 0.15;
    setZoom((z) => Math.min(8, Math.max(1, z + delta * z)));
  }, []);

  const handleMouseDown = useCallback((e: ReactMouseEvent) => {
    if (zoom <= 1) return;
    e.preventDefault();
    isPanningRef.current = true;
    lastMouseRef.current = { x: e.clientX, y: e.clientY };
  }, [zoom]);

  const handleMouseMove = useCallback((e: ReactMouseEvent) => {
    if (!isPanningRef.current) return;
    const dx = e.clientX - lastMouseRef.current.x;
    const dy = e.clientY - lastMouseRef.current.y;
    lastMouseRef.current = { x: e.clientX, y: e.clientY };
    setPan((p) => ({ x: p.x + dx, y: p.y + dy }));
  }, []);

  const handleMouseUp = useCallback(() => {
    isPanningRef.current = false;
  }, []);

  const resetZoom = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  const isSelected = (label: string) =>
    selectedRegion?.filename === filename && selectedRegion?.label === label;

  return (
    <div
      ref={containerRef}
      className={`relative bg-[#0f172a] rounded overflow-hidden ${fill ? 'w-full h-full' : 'flex-1'}`}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      style={{ cursor: zoom > 1 ? (isPanningRef.current ? 'grabbing' : 'grab') : 'default' }}
    >
      {/* Zoomable layer: image + overlays move together */}
      <div
        style={{
          width: '100%',
          height: '100%',
          transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
          transformOrigin: 'center center',
          transition: isPanningRef.current ? 'none' : 'transform 0.1s ease-out',
        }}
      >
        <img
          ref={imgRef}
          src={src}
          alt={alt}
          className="w-full h-full object-contain"
          onLoad={updateRect}
          draggable={false}
        />

        {/* Region overlay boxes — positioned relative to the rendered image */}
        {imgRect &&
          regions.map((region) => {
            const [xPct, yPct, wPct, hPct] = region.bbox;
            const active = isSelected(region.label) || hoveredRegion === region.label;
            const isSupp = !!region.supplementMeta || region.label.startsWith('Supp:');
            const color = regionColor(region.type, isSupp);
            const bgColor = regionColorBg(region.type, isSupp);
            return (
              <div
                key={region.label}
                className={`absolute cursor-pointer transition-all duration-150 ${
                  isSupp ? 'border-[3px] border-dashed' : 'border-2'
                }`}
                style={{
                  left: imgRect.offsetX + (xPct / 100) * imgRect.width,
                  top: imgRect.offsetY + (yPct / 100) * imgRect.height,
                  width: (wPct / 100) * imgRect.width,
                  height: (hPct / 100) * imgRect.height,
                  borderColor: color,
                  backgroundColor: active ? bgColor : isSupp ? 'rgba(249,115,22,0.08)' : 'transparent',
                  opacity: region.status === 'done' ? 1 : 0.6,
                  boxShadow: isSupp && active ? `0 0 12px ${color}40` : undefined,
                }}
                title={`${region.label} (${region.type})${isSupp ? ' — Supplement crop' : ''}`}
                onClick={() => onSelectRegion(filename, region.label)}
                onMouseEnter={() => setHoveredRegion(region.label)}
                onMouseLeave={() => setHoveredRegion(null)}
              >
                <span
                  className="absolute -top-3.5 left-0 text-[8px] font-mono px-0.5 rounded whitespace-nowrap"
                  style={{ color, backgroundColor: '#0f172aee' }}
                >
                  {isSupp && '🔍 '}
                  {region.label.length > 25 ? region.label.slice(0, 25) + '...' : region.label}
                </span>
              </div>
            );
          })}
      </div>

      {/* Zoom indicator (stays fixed, not zoomed) */}
      {zoom > 1.05 && (
        <button
          onClick={resetZoom}
          className="absolute top-1 right-1 z-10 px-1.5 py-0.5 rounded bg-[#0f172a]/80 text-[10px] text-[#94a3b8] hover:text-[#e2e8f0] transition-colors flex items-center gap-1"
          title="Reset zoom"
        >
          <ZoomIn size={10} /> {zoom.toFixed(1)}x
        </button>
      )}
    </div>
  );
}

// ── Single Map Panel (floating mode — original) ──────────────────────────────

interface MapPanelProps {
  filename: string;
}

function MapPanel({ filename }: MapPanelProps) {
  const entry = useMapAnalysisStore((s) => s.maps[filename]);
  const selectedRegion = useMapAnalysisStore((s) => s.selectedRegion);
  const selectRegion = useMapAnalysisStore((s) => s.selectRegion);
  const closePanel = useMapAnalysisStore((s) => s.closePanel);
  const [minimized, setMinimized] = useState(false);

  if (!entry) return null;

  const phaseBadge = entry.done
    ? '✅ Done'
    : entry.phase
      ? `⏳ ${entry.phase}`
      : '...';

  return (
    <div
      className="bg-[#1e293b] border border-[#334155] rounded-lg shadow-2xl flex flex-col overflow-hidden"
      style={{ width: 720, maxHeight: minimized ? 40 : 600 }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#0f172a] border-b border-[#334155] cursor-move shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <MapPin size={14} className="text-blue-400 shrink-0" />
          <span className="text-xs font-medium text-[#e2e8f0] truncate" title={filename}>
            {filename.length > 50 ? `...${filename.slice(-50)}` : filename}
          </span>
          <span className="text-[10px] text-[#64748b] shrink-0">
            ({entry.row}/{entry.total})
          </span>
          <span
            className={`text-[10px] px-1.5 py-0.5 rounded ${
              entry.done ? 'bg-emerald-900/50 text-emerald-300' : 'bg-amber-900/50 text-amber-300'
            }`}
          >
            {phaseBadge}
          </span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => setMinimized(!minimized)}
            className="p-1 text-[#64748b] hover:text-[#e2e8f0] transition-colors"
          >
            {minimized ? <Maximize2 size={12} /> : <Minimize2 size={12} />}
          </button>
          <button
            onClick={() => closePanel(filename)}
            className="p-1 text-[#64748b] hover:text-red-400 transition-colors"
          >
            <X size={12} />
          </button>
        </div>
      </div>

      {/* Body */}
      {!minimized && (
        <div className="flex flex-1 overflow-hidden" style={{ minHeight: 300 }}>
          {/* Map image with overlays */}
          <div className="flex-1 p-2 flex flex-col min-w-0">
            <div className="text-[10px] text-[#64748b] mb-1 flex items-center gap-1">
              <Eye size={10} /> Map Overview
            </div>
            {entry.sourceImage ? (
              <ImageWithOverlays
                src={sourceThumbUrl(entry.sourceImage)}
                alt={filename}
                regions={entry.regions}
                selectedRegion={selectedRegion}
                filename={filename}
                onSelectRegion={selectRegion}
              />
            ) : entry.previewPath ? (
              <img src={cropUrl(entry.previewPath)} alt="Region preview" className="w-full h-full object-contain" />
            ) : (
              <div className="flex items-center justify-center flex-1 text-[#475569] text-xs">
                <Scan size={20} className="animate-pulse" />
              </div>
            )}
          </div>

          {/* Sidebar: region list + detail */}
          <div className="w-[260px] shrink-0 border-l border-[#334155] flex flex-col overflow-hidden">
            {/* Region list */}
            <div className="max-h-[140px] overflow-y-auto border-b border-[#334155] shrink-0">
              {entry.regions.map((region) => {
                const sel = selectedRegion?.filename === filename && selectedRegion?.label === region.label;
                const isSupp = !!region.supplementMeta || region.label.startsWith('Supp:');
                return (
                  <button
                    key={region.label}
                    className={`w-full text-left px-2 py-0.5 text-[10px] font-mono flex items-center gap-1.5 transition-colors ${
                      sel ? 'bg-[#334155] text-[#e2e8f0]' : 'text-[#94a3b8] hover:bg-[#1e293b]'
                    }`}
                    onClick={() => selectRegion(filename, region.label)}
                  >
                    <span
                      className={`w-2 h-2 shrink-0 ${isSupp ? 'rounded-sm' : 'rounded-full'}`}
                      style={{ backgroundColor: regionColor(region.type, isSupp) }}
                    />
                    <span className="truncate">{region.label}</span>
                    {region.status === 'processing' && <span className="text-amber-400 animate-pulse ml-auto">⏳</span>}
                    {region.status === 'done' && <span className="text-emerald-400 ml-auto">✓</span>}
                  </button>
                );
              })}
            </div>
            {/* Detail */}
            <div className="flex-1 p-2 overflow-y-auto">
              {(() => {
                const activeRegion = entry.regions.find(
                  (r) => selectedRegion?.filename === filename && selectedRegion?.label === r.label
                );
                return activeRegion ? (
                  <RegionDetail region={activeRegion} />
                ) : (
                  <div className="flex items-center justify-center h-full text-[#475569] text-xs">
                    Click a region to see details
                  </div>
                );
              })()}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Region Detail ─────────────────────────────────────────────────────────────

function RegionDetail({ region }: { region: MapRegion }) {
  const isSupplement = !!region.supplementMeta;

  return (
    <div className="space-y-2">
      {/* Region header */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: regionColor(region.type) }} />
        <span className="text-sm font-medium text-[#e2e8f0]">{region.label}</span>
        <span className="text-[10px] text-[#64748b] uppercase">{region.type}</span>
        {region.position && <span className="text-[10px] text-[#94a3b8]">📍 {region.position}</span>}
        {isSupplement && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-900/50 text-orange-300 flex items-center gap-1">
            <RefreshCw size={8} /> Supplement
          </span>
        )}
      </div>

      {/* Supplement metadata card */}
      {isSupplement && region.supplementMeta && (
        <div className="bg-[#1a1a2e] border border-[#334155] rounded-lg p-2 space-y-1.5">
          <div className="flex items-center gap-2 text-[11px]">
            <span className="text-[#64748b] w-[50px] shrink-0">Field</span>
            <span className="text-orange-300 font-mono">{region.supplementMeta.field}</span>
          </div>
          <div className="flex items-center gap-2 text-[11px]">
            <span className="text-[#64748b] w-[50px] shrink-0">Reason</span>
            <span className="text-[#94a3b8]">{region.supplementMeta.reason}</span>
          </div>
          {region.supplementMeta.value && (
            <div className="flex items-start gap-2 text-[11px]">
              <span className="text-[#64748b] w-[50px] shrink-0">Value</span>
              <span className="text-[#e2e8f0] break-words">{region.supplementMeta.value}</span>
            </div>
          )}
          {region.status === 'done' && (
            <div className="flex items-center gap-1.5 text-[10px] mt-1">
              {region.supplementMeta.confident ? (
                <span className="flex items-center gap-1 text-emerald-400">
                  <CheckCircle size={10} /> Confident
                </span>
              ) : (
                <span className="flex items-center gap-1 text-amber-400">
                  <AlertCircle size={10} /> Low confidence
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Crop image — zoomable */}
      {region.cropPath && (
        <ZoomableImage
          src={cropUrl(region.cropPath)}
          alt={region.label}
          className="bg-[#0f172a] rounded max-h-[200px]"
        />
      )}

      {/* Prompt — collapsed by default */}
      {region.promptPreview && <CollapsibleText label="Prompt" text={region.promptPreview} />}

      {/* LLM Output */}
      {region.llmOutput && (
        <div>
          <div className="text-[10px] text-[#64748b] mb-0.5 flex items-center gap-1">
            <Scan size={10} /> LLM Output
          </div>
          <pre className="text-[10px] text-emerald-300 bg-[#0f172a] rounded p-2 whitespace-pre-wrap break-all max-h-[160px] overflow-y-auto font-mono">
            {formatJson(region.llmOutput)}
          </pre>
        </div>
      )}

      {/* Status */}
      {region.status === 'processing' && (
        <div className="text-xs text-amber-400 animate-pulse flex items-center gap-1.5">
          <RefreshCw size={10} className="animate-spin" />
          {isSupplement ? 'Re-analyzing crop...' : 'Processing...'}
        </div>
      )}
    </div>
  );
}

/** Collapsible text section — shows first 2 lines, expand to see all */
function CollapsibleText({ label, text }: { label: string; text: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-[10px] text-[#64748b] mb-0.5 flex items-center gap-1 hover:text-[#94a3b8] transition-colors"
      >
        <FileText size={10} />
        {label}
        <span className="text-[9px]">{expanded ? '▲' : '▼'}</span>
      </button>
      {expanded && (
        <pre className="text-[10px] text-[#94a3b8] bg-[#0f172a] rounded p-2 whitespace-pre-wrap break-all max-h-[120px] overflow-y-auto font-mono">
          {text}
        </pre>
      )}
    </div>
  );
}

/** Try to pretty-print JSON, fallback to raw string */
function formatJson(s: string): string {
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return s;
  }
}

// ── Map List Sidebar (shared between inline and fullscreen) ───────────────────

function MapListSidebar({
  allFiles,
  maps,
  activePanels,
}: {
  allFiles: string[];
  maps: Record<string, MapEntry>;
  activePanels: string[];
}) {
  return (
    <div className="w-[180px] shrink-0 border-r border-[#334155] overflow-y-auto bg-[#0f172a]">
      {allFiles.map((filename) => {
        const entry = maps[filename];
        if (!entry) return null;
        const isOpen = activePanels.includes(filename);
        return (
          <button
            key={filename}
            onClick={() => {
              const store = useMapAnalysisStore.getState();
              if (isOpen) {
                store.closePanel(filename);
              } else {
                activePanels.forEach((f) => store.closePanel(f));
                store.openPanel(filename);
              }
            }}
            className={`w-full text-left px-3 py-2 text-[11px] border-b border-[#334155]/50 transition-colors ${
              isOpen ? 'bg-[#1e293b] text-[#e2e8f0]' : 'text-[#94a3b8] hover:bg-[#1e293b]/50'
            }`}
          >
            <div className="flex items-center gap-1.5">
              <MapPin size={10} className={isOpen ? 'text-blue-400' : 'text-[#475569]'} />
              <span className="truncate">{filename.length > 25 ? `...${filename.slice(-25)}` : filename}</span>
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[9px] text-[#475569]">
                ({entry.row}/{entry.total})
              </span>
              <span
                className={`text-[9px] px-1 py-0 rounded ${
                  entry.done ? 'bg-emerald-900/50 text-emerald-300' : 'bg-amber-900/50 text-amber-300'
                }`}
              >
                {entry.done ? 'Done' : entry.phase || '...'}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ── Phase Timeline ────────────────────────────────────────────────────────────

const GROUNDED_PHASE_GROUPS = [
  { key: 'extract', label: 'Extract', phases: ['extract_start', 'extract_result'] },
  { key: 'critic', label: 'Critic', phases: ['critic_start', 'critic_review'] },
  { key: 'correct', label: 'Correct', phases: ['correction_sent', 'correction_result'] },
  { key: 'evidence', label: 'Evidence', phases: ['evidence_preview'] },
  { key: 'done', label: 'Done', phases: ['done'] },
];

// Legacy groups kept so old archived runs replay correctly
const MULTILEVEL_PHASE_GROUPS = [
  { key: 'L1', label: 'L1', phases: ['L1_scan', 'L1_result'] },
  { key: 'L2a', label: 'L2a', phases: ['L2a_ocr', 'L2a_result'] },
  { key: 'L2b', label: 'L2b', phases: ['L2b_planning', 'L2b_result'] },
  { key: 'L3', label: 'L3', phases: ['L3_crop', 'L3_result'] },
  { key: 'synth', label: 'Synth', phases: ['synthesis', 'done'] },
];

const DIRECT_PHASE_GROUPS = [
  { key: 'scan', label: 'Scan', phases: ['L1_scan'] },
  { key: 'direct', label: 'Direct', phases: ['direct_result'] },
  { key: 'supp', label: 'Supplement', phases: ['supplement_crop', 'supplement_result'] },
  { key: 'done', label: 'Done', phases: ['done'] },
];

function PhaseTimeline({ entry }: { entry: MapEntry }) {
  const reached = new Set(entry.phaseHistory.map((p) => p.phase));
  const currentPhase = entry.phase;

  // Auto-detect pipeline shape based on which phases have actually fired.
  const isGrounded = reached.has('extract_start') || reached.has('extract_result')
    || reached.has('critic_review') || reached.has('evidence_preview');
  const isDirect = !isGrounded && (reached.has('direct_result') || reached.has('direct_main'));
  const PHASE_GROUPS = isGrounded
    ? GROUNDED_PHASE_GROUPS
    : isDirect
      ? DIRECT_PHASE_GROUPS
      : MULTILEVEL_PHASE_GROUPS;

  function groupElapsed(group: (typeof PHASE_GROUPS)[number]): string | null {
    const records = entry.phaseHistory.filter((r) => group.phases.includes(r.phase));
    if (records.length < 2) return null;
    const ms = records[records.length - 1].ts - records[0].ts;
    return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
  }

  // Total elapsed time
  const totalElapsed = entry.phaseHistory.length >= 2
    ? entry.phaseHistory[entry.phaseHistory.length - 1].ts - entry.phaseHistory[0].ts
    : null;

  return (
    <div className="flex items-center gap-1 px-3 py-1.5 border-b border-[#334155] shrink-0 overflow-x-auto">
      {PHASE_GROUPS.map((group, i) => {
        const allDone = group.phases.every((p) => reached.has(p));
        const isActive = group.phases.some((p) => p === currentPhase) && !allDone;
        const elapsed = groupElapsed(group);
        return (
          <div key={group.key} className="flex items-center gap-1">
            {i > 0 && <span className="text-[#475569] text-[10px] mx-0.5">→</span>}
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                allDone
                  ? 'bg-emerald-900/40 text-emerald-300'
                  : isActive
                    ? 'bg-amber-900/40 text-amber-300 animate-pulse'
                    : 'bg-[#1e293b] text-[#475569]'
              }`}
            >
              {allDone ? '✓' : isActive ? '●' : '○'} {group.label}
              {elapsed && <span className="ml-1 text-[9px] opacity-70">({elapsed})</span>}
            </span>
          </div>
        );
      })}
      {/* Total time + tokens */}
      {entry.done && (
        <div className="flex items-center gap-2 ml-2 text-[9px] text-[#475569]">
          {totalElapsed !== null && <span>{(totalElapsed / 1000).toFixed(1)}s total</span>}
          {entry.tokenUsage && (
            <span>{entry.tokenUsage.total_tokens.toLocaleString()} tok</span>
          )}
        </div>
      )}
    </div>
  );
}

// ── Synthesis Summary Card ────────────────────────────────────────────────────

function SynthesisSummary({ result }: { result: Record<string, string> }) {
  const displayFields = [
    { key: 'country', label: 'Country' },
    { key: 'province_or_state', label: 'Province' },
    { key: 'city', label: 'City' },
    { key: 'district_or_county', label: 'District' },
    { key: 'map_title', label: 'Title' },
    { key: 'estimated_date', label: 'Date' },
    { key: 'place_names', label: 'Places' },
    { key: 'geographic_coverage', label: 'Coverage' },
    { key: 'notable_features', label: 'Features' },
    { key: 'map_type', label: 'Type' },
    { key: 'language', label: 'Language' },
  ];

  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-[#e2e8f0] flex items-center gap-1.5">
        <MapPin size={12} className="text-blue-400" />
        Synthesis Result
      </div>
      <div className="bg-[#0f172a] rounded-lg p-3 space-y-1.5">
        {displayFields.map(({ key, label }) => {
          const val = result[key];
          if (!val) return null;
          return (
            <div key={key} className="flex gap-2 text-[11px]">
              <span className="text-[#64748b] w-[70px] shrink-0">{label}</span>
              <span className="text-[#e2e8f0] break-words">{val}</span>
            </div>
          );
        })}
        {/* Extra keys */}
        {Object.entries(result)
          .filter(([k]) => !displayFields.some((f) => f.key === k))
          .map(([k, v]) => (
            <div key={k} className="flex gap-2 text-[11px]">
              <span className="text-[#64748b] w-[70px] shrink-0">{k}</span>
              <span className="text-[#94a3b8] break-words">{v}</span>
            </div>
          ))}
      </div>
    </div>
  );
}

// ── Container ─────────────────────────────────────────────────────────────────

interface MapAnalysisPanelProps {
  inline?: boolean;
}

export default function MapAnalysisPanel({ inline }: MapAnalysisPanelProps) {
  const activePanels = useMapAnalysisStore((s) => s.activePanels);
  const maps = useMapAnalysisStore((s) => s.maps);
  const fullscreen = useMapAnalysisStore((s) => s.fullscreen);
  const setFullscreen = useMapAnalysisStore((s) => s.setFullscreen);

  // Escape key to exit fullscreen
  useEffect(() => {
    if (!fullscreen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFullscreen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [fullscreen, setFullscreen]);

  // Keyboard navigation: arrow up/down to switch maps
  useEffect(() => {
    if (!fullscreen) return;
    const allFiles = Object.keys(maps);
    if (allFiles.length < 2) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
      const currentFile = activePanels[0];
      const idx = allFiles.indexOf(currentFile);
      if (idx < 0) return;
      const nextIdx = e.key === 'ArrowDown' ? Math.min(idx + 1, allFiles.length - 1) : Math.max(idx - 1, 0);
      if (nextIdx !== idx) {
        const store = useMapAnalysisStore.getState();
        store.closePanel(currentFile);
        store.openPanel(allFiles[nextIdx]);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [fullscreen, maps, activePanels]);

  // Inline mode: render inside BottomPanelManager
  if (inline) {
    const allFiles = Object.keys(maps);
    if (allFiles.length === 0) {
      return <div className="flex items-center justify-center h-full text-[#475569] text-xs">No map analysis data</div>;
    }

    // Fullscreen overlay
    if (fullscreen) {
      const doneCount = allFiles.filter((f) => maps[f]?.done).length;
      const expectedTotal = useMapAnalysisStore.getState().expectedTotal;
      const totalCount = Math.max(allFiles.length, expectedTotal);
      const totalTokens = allFiles.reduce((sum, f) => sum + (maps[f]?.tokenUsage?.total_tokens || 0), 0);
      const allDone = doneCount === totalCount && totalCount > 0;
      const postProcessPhase = useMapAnalysisStore.getState().postProcessPhase;

      // Build progress slots: known maps + pending placeholders
      const progressSlots: Array<{ filename: string; status: 'done' | 'active' | 'pending' }> = [];
      for (const f of allFiles) {
        progressSlots.push({
          filename: f,
          status: maps[f]?.done ? 'done' : maps[f]?.phase ? 'active' : 'pending',
        });
      }
      // Add placeholders for maps not yet started
      for (let i = allFiles.length; i < totalCount; i++) {
        progressSlots.push({ filename: `pending-${i}`, status: 'pending' });
      }

      return (
        <div className="fixed inset-0 z-[60] bg-[#0f172a] flex flex-col">
          {/* Fullscreen header */}
          <div className="flex items-center justify-between px-4 py-2 border-b border-[#334155] shrink-0 bg-[#1e293b]">
            <div className="flex items-center gap-3 text-sm text-[#e2e8f0]">
              <MapPin size={14} className="text-blue-400" />
              <span className="font-medium">Map Analysis</span>
              {/* Stepped progress — shows ALL expected maps */}
              <div className="flex items-center gap-2 ml-2">
                <div className="flex gap-[2px]">
                  {progressSlots.map((slot, i) => (
                    <div
                      key={i}
                      className={`h-2 rounded-[1px] transition-all duration-300 ${
                        slot.status === 'done'
                          ? 'bg-emerald-500'
                          : slot.status === 'active'
                            ? 'bg-amber-500 animate-pulse'
                            : 'bg-[#334155]'
                      }`}
                      style={{ width: Math.max(4, Math.min(20, 160 / totalCount)) }}
                      title={slot.status === 'pending' ? 'Pending' : `${slot.filename}: ${slot.status}`}
                    />
                  ))}
                  {/* Post-process indicator */}
                  <div className="mx-0.5" />
                  <div
                    className={`h-2 w-3 rounded-[1px] transition-all duration-300 ${
                      postProcessPhase === 'done'
                        ? 'bg-emerald-500'
                        : postProcessPhase === 'running'
                          ? 'bg-violet-500 animate-pulse'
                          : 'bg-[#334155]'
                    }`}
                    title={`Post-process: ${postProcessPhase}`}
                  />
                </div>
                <span className={`text-[10px] font-mono ${allDone ? 'text-emerald-400' : 'text-[#64748b]'}`}>
                  {doneCount}/{totalCount}
                </span>
                {postProcessPhase === 'running' && (
                  <span className="text-[10px] text-violet-400 animate-pulse">PP</span>
                )}
                {postProcessPhase === 'done' && (
                  <span className="text-[10px] text-emerald-400">PP</span>
                )}
                {totalTokens > 0 && (
                  <span className="text-[10px] text-[#475569]">
                    {totalTokens.toLocaleString()} tok
                  </span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-[#475569]">ESC to exit / Arrow keys to navigate</span>
              <button
                onClick={() => setFullscreen(false)}
                className="p-1.5 rounded hover:bg-[#334155] text-[#94a3b8] hover:text-[#e2e8f0] transition-colors"
              >
                <Shrink size={14} />
              </button>
            </div>
          </div>
          <div className="flex flex-1 overflow-hidden">
            <MapListSidebar allFiles={allFiles} maps={maps} activePanels={activePanels} />
            <div className="flex-1 overflow-hidden">
              {activePanels.length > 0 && maps[activePanels[0]] ? (
                <MapPanelInline filename={activePanels[0]} />
              ) : (
                <div className="flex items-center justify-center h-full text-[#475569] text-xs">
                  Select a map to view analysis
                </div>
              )}
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="h-full flex overflow-hidden">
        <MapListSidebar allFiles={allFiles} maps={maps} activePanels={activePanels} />
        {/* Fullscreen toggle */}
        <div className="flex-1 overflow-hidden relative">
          <button
            onClick={() => setFullscreen(true)}
            className="absolute top-1 right-1 z-10 p-1 rounded bg-[#1e293b]/80 text-[#64748b] hover:text-[#e2e8f0] transition-colors"
            title="Fullscreen (Esc to exit)"
          >
            <Expand size={12} />
          </button>
          {activePanels.length > 0 && maps[activePanels[0]] ? (
            <MapPanelInline filename={activePanels[0]} />
          ) : (
            <div className="flex items-center justify-center h-full text-[#475569] text-xs">
              Select a map to view analysis
            </div>
          )}
        </div>
      </div>
    );
  }

  // Standalone floating mode (original)
  if (activePanels.length === 0) return null;

  return (
    <div className="fixed bottom-0 right-0 z-50 flex flex-col-reverse items-end gap-2 p-3 pointer-events-none max-h-screen overflow-y-auto">
      {activePanels.map(
        (filename) =>
          maps[filename] && (
            <div key={filename} className="pointer-events-auto">
              <MapPanel filename={filename} />
            </div>
          )
      )}
    </div>
  );
}

// ── Inline MapPanel — image + results layout ──────────────────────────────────
//
// Layout:
// ┌──────────────────────────────────────────────┬──────────────────────────────┐
// │ Phase Timeline (Scan→Direct→Supp→Done)       │ Phase Timeline               │
// ├──────────────────────────────────────────────┤──────────────────────────────┤
// │                                              │  Synthesis Results           │
// │           MAP IMAGE (PRIMARY)                │  (auto-updating key-value)   │
// │           with region overlays               │──────────────────────────────│
// │                                              │  Region list + Detail        │
// │                                              │  (supplement crops, etc.)    │
// └──────────────────────────────────────────────┴──────────────────────────────┘

function MapPanelInline({ filename }: { filename: string }) {
  const entry = useMapAnalysisStore((s) => s.maps[filename]);
  const selectedRegion = useMapAnalysisStore((s) => s.selectedRegion);
  const selectRegion = useMapAnalysisStore((s) => s.selectRegion);
  const postProcessPhase = useMapAnalysisStore((s) => s.postProcessPhase);

  if (!entry) return null;

  const activeRegion = entry.regions.find(
    (r) => selectedRegion?.filename === filename && selectedRegion?.label === r.label
  );

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Phase timeline */}
      <PhaseTimeline entry={entry} />

      <div className="flex flex-1 overflow-hidden min-h-0">
        {/* LEFT: Map image — PRIMARY area */}
        <div className="flex-[3] min-w-0 p-2 flex flex-col">
          <div className="text-[10px] text-[#64748b] mb-1 flex items-center gap-1">
            <Eye size={10} /> Map Overview
            {entry.done && <span className="text-emerald-400 ml-1">({entry.fieldsFilled} fields)</span>}
            {entry.postProcessRefined && entry.postProcessRefined.length > 0 && (
              <span className="text-violet-400 ml-1">(PP: {entry.postProcessRefined.join(', ')})</span>
            )}
          </div>

          {entry.sourceImage ? (
            <ImageWithOverlays
              src={sourceThumbUrl(entry.sourceImage, 1200)}
              alt={filename}
              regions={entry.regions}
              selectedRegion={selectedRegion}
              filename={filename}
              onSelectRegion={selectRegion}
            />
          ) : entry.previewPath ? (
            <div className="flex-1 bg-[#0f172a] rounded overflow-hidden">
              <img src={cropUrl(entry.previewPath)} alt="Region preview" className="w-full h-full object-contain" />
            </div>
          ) : (
            <div className="flex items-center justify-center flex-1 text-[#475569] text-xs">
              <Scan size={20} className="animate-pulse" />
            </div>
          )}
        </div>

        {/* RIGHT: Results + regions panel */}
        <div className="flex-[2] min-w-[280px] max-w-[420px] border-l border-[#334155] flex flex-col overflow-hidden">
          {/* Synthesis result — live-updating */}
          {entry.synthesisResult && (
            <div className="border-b border-[#334155] shrink-0 max-h-[50%] overflow-y-auto">
              <div className="px-3 py-1.5 bg-[#0f172a] border-b border-[#334155]/50 flex items-center gap-1.5 sticky top-0 z-[1]">
                <MapPin size={10} className="text-blue-400" />
                <span className="text-[10px] font-medium text-[#e2e8f0]">Analysis Result</span>
                {entry.criticCorrections && entry.criticCorrections.length > 0 && (
                  <span className="text-[9px] text-amber-400 ml-auto" title="Critic demoted hallucinated fields">
                    critic: {entry.criticCorrections.length} demoted
                  </span>
                )}
                {postProcessPhase === 'running' && (
                  <span className="text-[9px] text-violet-400 animate-pulse ml-auto">refining...</span>
                )}
                {postProcessPhase === 'done' && entry.postProcessRefined && entry.postProcessRefined.length > 0 && (
                  <span className="text-[9px] text-violet-400 ml-auto">
                    refined: {entry.postProcessRefined.length} fields
                  </span>
                )}
              </div>
              <SynthesisResultTable
                result={entry.synthesisResult}
                refined={entry.postProcessRefined}
                criticAudit={entry.criticAudit}
                criticCorrections={entry.criticCorrections}
              />
            </div>
          )}

          {/* Region list + detail */}
          <div className="flex flex-col flex-1 overflow-hidden">
            {entry.regions.length > 0 && (
              <div className="max-h-[120px] overflow-y-auto border-b border-[#334155] shrink-0">
                {entry.regions.map((region) => {
                  const sel = selectedRegion?.filename === filename && selectedRegion?.label === region.label;
                  const isSupp = !!region.supplementMeta || region.label.startsWith('Supp:');
                  return (
                    <button
                      key={region.label}
                      className={`w-full text-left px-2 py-0.5 text-[10px] font-mono flex items-center gap-1.5 transition-colors ${
                        sel ? 'bg-[#334155] text-[#e2e8f0]' : 'text-[#94a3b8] hover:bg-[#1e293b]'
                      }`}
                      onClick={() => selectRegion(filename, region.label)}
                    >
                      <span
                        className={`w-2 h-2 shrink-0 ${isSupp ? 'rounded-sm' : 'rounded-full'}`}
                        style={{ backgroundColor: regionColor(region.type, isSupp) }}
                      />
                      <span className="truncate">{region.label}</span>
                      {region.status === 'processing' && <span className="text-amber-400 animate-pulse ml-auto">...</span>}
                      {region.status === 'done' && isSupp && region.supplementMeta?.confident && (
                        <span className="text-emerald-400 ml-auto">ok</span>
                      )}
                      {region.status === 'done' && isSupp && !region.supplementMeta?.confident && (
                        <span className="text-amber-400 ml-auto">?</span>
                      )}
                      {region.status === 'done' && !isSupp && <span className="text-emerald-400 ml-auto">ok</span>}
                    </button>
                  );
                })}
              </div>
            )}

            {/* Detail panel */}
            <div className="flex-1 p-2 overflow-y-auto">
              {activeRegion ? (
                <RegionDetail region={activeRegion} />
              ) : !entry.synthesisResult && !entry.done ? (
                <div className="flex items-center justify-center h-full text-[#475569] text-xs">
                  {entry.phase ? (
                    <div className="flex items-center gap-2">
                      <Scan size={14} className="animate-pulse" />
                      <span>Analyzing...</span>
                    </div>
                  ) : (
                    'Waiting for analysis...'
                  )}
                </div>
              ) : entry.regions.length > 0 ? (
                <div className="flex items-center justify-center h-full text-[#475569] text-xs">
                  Click a region to see details
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Table display for synthesis results — shows all fields with refinement + critic highlights */
function SynthesisResultTable({
  result,
  refined,
  criticAudit,
  criticCorrections,
}: {
  result: Record<string, string>;
  refined?: string[];
  criticAudit?: Record<string, { evidence: string; note: string }>;
  criticCorrections?: Array<{ field: string; oldValue: string; note: string }>;
}) {
  const refinedSet = new Set(refined || []);
  const audit = criticAudit || {};

  // Synthesis key → critic JSON key mapping
  const synthesisToCriticKey = (k: string): string => {
    if (k === 'map_title') return 'title';
    if (k === 'estimated_date') return 'date_text';
    if (k === 'province_or_state') return 'province';
    if (k === 'district_or_county') return 'district';
    if (k === 'geographic_coverage') return 'coverage';
    if (k === 'notable_features') return 'subject';
    if (k.startsWith('ts_')) return `type_specific.${k.slice(3)}`;
    return k;
  };

  // Map synthesis keys to display labels
  const fieldLabels: Record<string, string> = {
    map_title: 'Title',
    estimated_date: 'Date',
    country: 'Country',
    province_or_state: 'Province',
    city: 'City',
    district_or_county: 'District',
    map_type: 'Type',
    language: 'Language',
    place_names: 'Places',
    geographic_coverage: 'Coverage',
    notable_features: 'Features',
  };

  // ts_ field display labels (snake_case → Title Case)
  const tsLabel = (k: string) => k.replace(/^ts_/, '').replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());

  // Category grouping for ts_ fields
  const tsCategories: [string, string[]][] = [
    ['Grid / Coordinate', ['grid_system', 'grid_zone', 'grid_interval', 'grid_easting_range',
      'grid_northing_range', 'magnetic_declination', 'coordinate_system', 'datum']],
    ['Terrain / Elevation', ['contour_interval', 'elevation_range', 'elevation_unit',
      'highest_point', 'relief']],
    ['Hydrographic', ['depth_range', 'depth_unit', 'tidal_datum', 'navigation_aids', 'chart_number']],
    ['Geological', ['rock_types', 'geological_period', 'stratigraphic_units', 'mineral_deposits']],
    ['Survey / Cadastral', ['lot_numbers', 'parish', 'hundred', 'land_parcels', 'surveyor',
      'survey_date', 'survey_reference']],
    ['Plan / Engineering', ['plan_number', 'drawing_number', 'engineer', 'approval_date']],
    ['Thematic', ['theme', 'data_source', 'classification_method']],
    ['Celestial', ['star_magnitude_range', 'epoch']],
  ];

  // Separate core fields from type_specific
  const coreEntries = Object.entries(result).filter(([k]) => !k.startsWith('ts_'));
  const tsEntries = Object.entries(result).filter(([k, v]) => k.startsWith('ts_') && v && v !== 'N/A');

  // Group ts_ entries by category
  const knownKeys = new Set(tsCategories.flatMap(([, keys]) => keys));
  const tsGroups: { cat: string; items: [string, string][] }[] = [];
  for (const [cat, keys] of tsCategories) {
    const items = keys
      .map(k => [`ts_${k}`, result[`ts_${k}`]] as [string, string])
      .filter(([, v]) => v && v !== 'N/A');
    if (items.length > 0) tsGroups.push({ cat, items });
  }
  // Uncategorised ts_ fields
  const uncatItems = tsEntries.filter(([k]) => !knownKeys.has(k.replace(/^ts_/, '')));
  if (uncatItems.length > 0) tsGroups.push({ cat: 'Other', items: uncatItems as [string, string][] });

  const renderRow = (key: string, val: string, label: string) => {
    const criticKey = synthesisToCriticKey(key);
    const isRefined = refinedSet.has(key) || refinedSet.has(criticKey);
    const auditInfo = audit[criticKey];
    const isQuestionable = auditInfo?.evidence === 'inferred_questionable';
    const isVisible = auditInfo?.evidence === 'directly_visible';
    return (
      <div key={key} className="flex gap-2 px-3 py-1 text-[11px] hover:bg-[#1e293b]/50">
        <span className="text-[#64748b] w-[65px] shrink-0">{label}</span>
        <span className={`break-words min-w-0 ${isRefined ? 'text-violet-300' : 'text-[#e2e8f0]'}`}>
          {isRefined && <span className="text-violet-500 mr-1" title="Refined by post-process">*</span>}
          {isQuestionable && (
            <span className="text-amber-400 mr-1" title={`Critic: questionable inference — ${auditInfo?.note || ''}`}>⚠</span>
          )}
          {isVisible && (
            <span className="text-emerald-500/80 mr-1" title="Critic: directly visible in scan">✓</span>
          )}
          {val}
        </span>
      </div>
    );
  };

  return (
    <div className="divide-y divide-[#334155]/30">
      {coreEntries.map(([key, val]) => {
        if (!val || val === 'N/A') return null;
        return renderRow(key, val, fieldLabels[key] || key);
      })}
      {tsGroups.map(({ cat, items }) => (
        <div key={cat}>
          <div className="px-3 py-1 text-[10px] font-semibold text-amber-400/70 uppercase tracking-wider bg-[#1e293b]/30 border-t border-[#334155]/50 mt-1">
            {cat}
          </div>
          {items.map(([key, val]) => renderRow(key, val, tsLabel(key)))}
        </div>
      ))}
      {criticCorrections && criticCorrections.length > 0 && (
        <div>
          <div className="px-3 py-1 text-[10px] font-semibold text-red-400/80 uppercase tracking-wider bg-[#2a0f0f]/40 border-t border-red-900/40 mt-1">
            Critic — demoted (likely hallucinated)
          </div>
          {criticCorrections.map((c) => (
            <div key={c.field} className="flex gap-2 px-3 py-1 text-[11px] bg-red-950/20" title={c.note}>
              <span className="text-red-400/80 w-[65px] shrink-0 truncate">{c.field}</span>
              <span className="break-words min-w-0 text-red-300/70 line-through">
                {c.oldValue}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
