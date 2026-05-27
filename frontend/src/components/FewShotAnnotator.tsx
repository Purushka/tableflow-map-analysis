import { useEffect, useState, useRef, useCallback } from 'react';
import { useT } from '../i18n/useI18n';
import {
  Upload, Save, Trash2, Plus, Check, X, Eye,
  ChevronDown, ChevronRight, Image as ImageIcon,
} from 'lucide-react';

/* ── Types ─────────────────────────────────────────────────────────────── */

type RegionType = 'text_region' | 'coordinate_strip' | 'map_sample';

interface Region {
  label: string;
  type: RegionType;
  bbox: [number, number, number, number]; // [x%, y%, w%, h%]
  hint: string;
}

interface FewShotExample {
  id: string;
  thumb_file: string;
  thumb_url: string;
  description: string;
  phases: string[];
  regions: Region[];
}

/* ── Quick-label presets ───────────────────────────────────────────────── */

// L1: text region labels
const TEXT_LABELS = [
  { label: 'main_title',       short: 'Title',     hint: 'main map title text', type: 'text_region' as RegionType },
  { label: 'subtitle',         short: 'Subtitle',  hint: 'subtitle or secondary title line', type: 'text_region' as RegionType },
  { label: 'legend',           short: 'Legend',     hint: 'legend or key text', type: 'text_region' as RegionType },
  { label: 'scale_text',       short: 'Scale',     hint: 'scale description text', type: 'text_region' as RegionType },
  { label: 'publisher_info',   short: 'Publisher', hint: 'publisher, printer, or engraver info', type: 'text_region' as RegionType },
  { label: 'date_text',        short: 'Date',      hint: 'date or year text', type: 'text_region' as RegionType },
  { label: 'margin_notes',     short: 'Notes',     hint: 'margin notes or annotations', type: 'text_region' as RegionType },
];

// L2b: coordinate strip labels
const COORD_LABELS = [
  { label: 'longitude_labels_top',    short: 'Lon Top',    hint: 'longitude/easting labels along top edge', type: 'coordinate_strip' as RegionType },
  { label: 'longitude_labels_bottom', short: 'Lon Bottom', hint: 'longitude/easting labels along bottom edge', type: 'coordinate_strip' as RegionType },
  { label: 'latitude_labels_left',    short: 'Lat Left',   hint: 'latitude/northing labels along left edge', type: 'coordinate_strip' as RegionType },
  { label: 'latitude_labels_right',   short: 'Lat Right',  hint: 'latitude/northing labels along right edge', type: 'coordinate_strip' as RegionType },
  { label: 'scale_bar',              short: 'Scale',       hint: 'scale bar or scale indicator', type: 'coordinate_strip' as RegionType },
];

// L2b: map sample labels
const SAMPLE_LABELS = [
  { label: 'map_sample_1', short: 'Sample 1', hint: 'map body content area', type: 'map_sample' as RegionType },
  { label: 'map_sample_2', short: 'Sample 2', hint: 'map body content area', type: 'map_sample' as RegionType },
  { label: 'map_sample_3', short: 'Sample 3', hint: 'map body content area', type: 'map_sample' as RegionType },
];

/* ── Color scheme ──────────────────────────────────────────────────────── */

const TYPE_COLORS: Record<string, { border: string; bg: string; text: string }> = {
  text_region:      { border: '#ef4444', bg: 'rgba(239,68,68,0.15)',  text: '#f87171' },
  coordinate_strip: { border: '#f59e0b', bg: 'rgba(245,158,11,0.15)', text: '#fbbf24' },
  map_sample:       { border: '#06b6d4', bg: 'rgba(6,182,212,0.15)',  text: '#22d3ee' },
};

/* ── AnnotationCanvas: the drag-to-draw interactive area ───────────────── */

function AnnotationCanvas({
  imageUrl,
  regions,
  onAddRegion,
  onDeleteRegion,
  selectedIdx,
  onSelect,
}: {
  imageUrl: string;
  regions: Region[];
  onAddRegion: (bbox: [number, number, number, number]) => void;
  onDeleteRegion: (idx: number) => void;
  selectedIdx: number | null;
  onSelect: (idx: number | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [drawing, setDrawing] = useState(false);
  const [startPt, setStartPt] = useState<{ x: number; y: number } | null>(null);
  const [currentPt, setCurrentPt] = useState<{ x: number; y: number } | null>(null);

  // Convert mouse event to percentage coordinates relative to image
  const toPercent = useCallback((e: React.MouseEvent): { x: number; y: number } | null => {
    const img = imgRef.current;
    if (!img) return null;
    const rect = img.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;
    return {
      x: Math.max(0, Math.min(100, x)),
      y: Math.max(0, Math.min(100, y)),
    };
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    // Ignore if clicking on an existing region overlay
    if ((e.target as HTMLElement).dataset?.regionIdx) return;
    const pt = toPercent(e);
    if (!pt) return;
    e.preventDefault();
    setDrawing(true);
    setStartPt(pt);
    setCurrentPt(pt);
    onSelect(null);
  }, [toPercent, onSelect]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!drawing) return;
    const pt = toPercent(e);
    if (pt) setCurrentPt(pt);
  }, [drawing, toPercent]);

  const handleMouseUp = useCallback(() => {
    if (!drawing || !startPt || !currentPt) {
      setDrawing(false);
      return;
    }
    setDrawing(false);

    // Calculate bbox
    const x = Math.min(startPt.x, currentPt.x);
    const y = Math.min(startPt.y, currentPt.y);
    const w = Math.abs(currentPt.x - startPt.x);
    const h = Math.abs(currentPt.y - startPt.y);

    // Ignore tiny accidental drags
    if (w < 1.5 && h < 1.5) return;

    onAddRegion([
      Math.round(x * 10) / 10,
      Math.round(y * 10) / 10,
      Math.round(w * 10) / 10,
      Math.round(h * 10) / 10,
    ]);

    setStartPt(null);
    setCurrentPt(null);
  }, [drawing, startPt, currentPt, onAddRegion]);

  // Drawing preview rect
  const previewRect = drawing && startPt && currentPt ? {
    left: `${Math.min(startPt.x, currentPt.x)}%`,
    top: `${Math.min(startPt.y, currentPt.y)}%`,
    width: `${Math.abs(currentPt.x - startPt.x)}%`,
    height: `${Math.abs(currentPt.y - startPt.y)}%`,
  } : null;

  return (
    <div
      ref={containerRef}
      className="relative select-none"
      style={{ cursor: drawing ? 'crosshair' : 'crosshair' }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <img
        ref={imgRef}
        src={imageUrl}
        alt="Map"
        className="w-full h-auto block rounded"
        draggable={false}
      />

      {/* Existing region overlays */}
      {regions.map((r, i) => {
        const colors = TYPE_COLORS[r.type];
        const isSelected = selectedIdx === i;
        return (
          <div
            key={i}
            data-region-idx={i}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(isSelected ? null : i);
            }}
            style={{
              position: 'absolute',
              left: `${r.bbox[0]}%`,
              top: `${r.bbox[1]}%`,
              width: `${r.bbox[2]}%`,
              height: `${r.bbox[3]}%`,
              border: `2px solid ${isSelected ? '#fff' : colors.border}`,
              backgroundColor: colors.bg,
              cursor: 'pointer',
              zIndex: isSelected ? 10 : 5,
            }}
          >
            {/* Label tag */}
            <div
              className="absolute -top-4 left-0 text-[8px] px-1 rounded whitespace-nowrap"
              style={{
                backgroundColor: colors.border,
                color: '#000',
                fontWeight: 600,
              }}
            >
              {r.label}
            </div>
            {/* Delete button */}
            {isSelected && (
              <button
                className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 rounded-full flex items-center justify-center z-20"
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteRegion(i);
                }}
              >
                <X size={8} className="text-white" />
              </button>
            )}
          </div>
        );
      })}

      {/* Drawing preview */}
      {previewRect && (
        <div
          style={{
            position: 'absolute',
            ...previewRect,
            border: '2px dashed #fff',
            backgroundColor: 'rgba(255,255,255,0.1)',
            pointerEvents: 'none',
            zIndex: 20,
          }}
        />
      )}
    </div>
  );
}

/* ── LabelPicker: appears after drawing a box ──────────────────────────── */

function LabelPicker({
  onPick,
  onCancel,
}: {
  onPick: (label: string, type: RegionType, hint: string) => void;
  onCancel: () => void;
}) {
  const t = useT();
  return (
    <div className="bg-[#1e293b] border border-[#334155] rounded-lg p-2 shadow-xl">
      <div className="text-[9px] text-[#64748b] mb-1.5">{t('fewshot.pickLabel')}</div>
      {/* L1: Text regions */}
      <div className="text-[8px] text-red-400/70 mb-0.5">L1 — Text Regions</div>
      <div className="flex flex-wrap gap-1 mb-1.5">
        {TEXT_LABELS.map((c) => (
          <button
            key={c.label}
            onClick={() => onPick(c.label, c.type, c.hint)}
            className="text-[10px] px-2 py-1 rounded bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30 transition-colors"
          >
            {c.short}
          </button>
        ))}
      </div>
      {/* L2b: Coordinate strips */}
      <div className="text-[8px] text-amber-400/70 mb-0.5">L2b — Coordinate Strips</div>
      <div className="flex flex-wrap gap-1 mb-1.5">
        {COORD_LABELS.map((c) => (
          <button
            key={c.label}
            onClick={() => onPick(c.label, c.type, c.hint)}
            className="text-[10px] px-2 py-1 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30 hover:bg-amber-500/30 transition-colors"
          >
            {c.short}
          </button>
        ))}
      </div>
      {/* L2b: Map samples */}
      <div className="text-[8px] text-cyan-400/70 mb-0.5">L2b — Map Samples</div>
      <div className="flex flex-wrap gap-1 mb-1.5">
        {SAMPLE_LABELS.map((c) => (
          <button
            key={c.label}
            onClick={() => onPick(c.label, c.type, c.hint)}
            className="text-[10px] px-2 py-1 rounded bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 hover:bg-cyan-500/30 transition-colors"
          >
            {c.short}
          </button>
        ))}
      </div>
      <button
        onClick={onCancel}
        className="text-[9px] text-[#64748b] hover:text-white transition-colors"
      >
        {t('toolbar.cancel')}
      </button>
    </div>
  );
}

/* ── ExampleListItem ───────────────────────────────────────────────────── */

function ExampleListItem({
  example,
  onDelete,
  onSelect,
}: {
  example: FewShotExample;
  onDelete: (id: string) => void;
  onSelect: (ex: FewShotExample) => void;
}) {
  const textCount = example.regions.filter(r => r.type === 'text_region').length;
  const coordCount = example.regions.filter(r => r.type === 'coordinate_strip').length;
  const sampleCount = example.regions.filter(r => r.type === 'map_sample').length;
  const [confirmDel, setConfirmDel] = useState(false);

  return (
    <div className="flex items-center gap-2 px-2 py-1.5 border border-[#334155] rounded-lg bg-[#1e293b]/50 hover:bg-[#1e293b] transition-colors">
      {/* Tiny thumbnail */}
      <img
        src={example.thumb_url}
        alt=""
        className="w-10 h-10 object-cover rounded shrink-0 cursor-pointer"
        onClick={() => onSelect(example)}
      />
      <div className="flex-1 min-w-0">
        <div className="text-[10px] text-[#e2e8f0] truncate">
          {example.description || example.id}
        </div>
        <div className="flex items-center gap-2 text-[9px] text-[#64748b]">
          {textCount > 0 && (
            <span className="text-red-400">{textCount} text</span>
          )}
          {coordCount > 0 && (
            <span className="text-amber-400">{coordCount} coord</span>
          )}
          {sampleCount > 0 && (
            <span className="text-cyan-400">{sampleCount} sample</span>
          )}
          {example.phases && (
            <span className="text-[#475569]">[{example.phases.join(',')}]</span>
          )}
        </div>
      </div>
      <button
        onClick={() => onSelect(example)}
        className="text-[#64748b] hover:text-white p-1 transition-colors"
        title="View/Edit"
      >
        <Eye size={12} />
      </button>
      <button
        onClick={() => {
          if (!confirmDel) {
            setConfirmDel(true);
            setTimeout(() => setConfirmDel(false), 3000);
          } else {
            onDelete(example.id);
          }
        }}
        className={`p-1 transition-colors ${confirmDel ? 'text-red-400' : 'text-[#64748b] hover:text-red-400'}`}
        title="Delete"
      >
        <Trash2 size={12} />
      </button>
    </div>
  );
}

/* ── Main Component ────────────────────────────────────────────────────── */

export default function FewShotAnnotator() {
  const t = useT();

  // State
  const [examples, setExamples] = useState<FewShotExample[]>([]);
  const [loading, setLoading] = useState(true);

  // Annotation state
  const [mode, setMode] = useState<'list' | 'annotate'>('list');
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [tempId, setTempId] = useState<string | null>(null);
  const [thumbFile, setThumbFile] = useState<string | null>(null);
  const [regions, setRegions] = useState<Region[]>([]);
  const [pendingBbox, setPendingBbox] = useState<[number, number, number, number] | null>(null);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load examples
  const loadExamples = useCallback(async () => {
    try {
      const resp = await fetch('/api/fewshot/');
      if (!resp.ok) return;
      const data = await resp.json();
      setExamples(data.examples);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadExamples(); }, [loadExamples]);

  // Upload image
  const handleFileChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const form = new FormData();
    form.append('file', file);

    const resp = await fetch('/api/fewshot/upload', { method: 'POST', body: form });
    if (!resp.ok) return;
    const data = await resp.json();

    setTempId(data.temp_id);
    setThumbFile(data.thumb_file);
    setImageUrl(data.thumb_url);
    setRegions([]);
    setDescription('');
    setEditingId(null);
    setMode('annotate');

    // Reset file input
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, []);

  // Add region (after drawing bbox)
  const handleAddBbox = useCallback((bbox: [number, number, number, number]) => {
    setPendingBbox(bbox);
  }, []);

  // Label the pending bbox
  const handleLabelPick = useCallback((label: string, type: RegionType, hint: string) => {
    if (!pendingBbox) return;
    setRegions(prev => [...prev, { label, type, bbox: pendingBbox, hint }]);
    setPendingBbox(null);
    setSelectedIdx(null);
  }, [pendingBbox]);

  // Delete region
  const handleDeleteRegion = useCallback((idx: number) => {
    setRegions(prev => prev.filter((_, i) => i !== idx));
    setSelectedIdx(null);
  }, []);

  // Auto-compute phases from region types
  const computePhases = useCallback((regs: Region[]): string[] => {
    const phases: string[] = [];
    if (regs.some(r => r.type === 'text_region')) phases.push('L1');
    if (regs.some(r => r.type === 'coordinate_strip' || r.type === 'map_sample')) phases.push('L2b');
    return phases.length > 0 ? phases : ['L2b'];
  }, []);

  // Save example
  const handleSave = useCallback(async () => {
    if (!tempId || !thumbFile || regions.length === 0) return;
    setSaving(true);
    const phases = computePhases(regions);
    try {
      if (editingId) {
        // Update existing
        await fetch(`/api/fewshot/${editingId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ description, phases, regions }),
        });
      } else {
        // Create new
        await fetch('/api/fewshot/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            temp_id: tempId,
            thumb_file: thumbFile,
            description,
            phases,
            regions,
          }),
        });
      }
      await loadExamples();
      setMode('list');
    } finally {
      setSaving(false);
    }
  }, [tempId, thumbFile, regions, description, editingId, loadExamples]);

  // Edit existing
  const handleEditExample = useCallback((ex: FewShotExample) => {
    setEditingId(ex.id);
    setTempId(ex.id);
    setThumbFile(ex.thumb_file);
    setImageUrl(ex.thumb_url);
    setRegions(ex.regions as Region[]);
    setDescription(ex.description);
    setMode('annotate');
  }, []);

  // Delete example
  const handleDeleteExample = useCallback(async (id: string) => {
    await fetch(`/api/fewshot/${id}`, { method: 'DELETE' });
    await loadExamples();
  }, [loadExamples]);

  /* ── Render ──────────────────────────────────────────────────────────── */

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-[#475569] text-xs">
        Loading...
      </div>
    );
  }

  // ── Annotation mode ──
  if (mode === 'annotate' && imageUrl) {
    return (
      <div className="h-full flex overflow-hidden">
        {/* Left: Canvas */}
        <div className="flex-1 overflow-auto p-2">
          <AnnotationCanvas
            imageUrl={imageUrl}
            regions={regions}
            onAddRegion={handleAddBbox}
            onDeleteRegion={handleDeleteRegion}
            selectedIdx={selectedIdx}
            onSelect={setSelectedIdx}
          />

          {/* Label picker overlay */}
          {pendingBbox && (
            <div className="mt-2">
              <LabelPicker
                onPick={handleLabelPick}
                onCancel={() => setPendingBbox(null)}
              />
            </div>
          )}
        </div>

        {/* Right: Region list + save */}
        <div className="w-56 border-l border-[#1e293b] p-2 flex flex-col gap-2 overflow-y-auto shrink-0">
          <div className="text-[10px] text-[#94a3b8] font-medium">
            {t('fewshot.instructions')}
          </div>

          {/* Description */}
          <div>
            <label className="text-[9px] text-[#475569] block mb-0.5">{t('fewshot.description')}</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. 19th century lithograph map"
              className="w-full bg-[#0f172a] border border-[#334155] rounded text-[10px] text-[#cbd5e1] px-2 py-1 focus:border-blue-500/50 focus:outline-none"
            />
          </div>

          {/* Region list */}
          <div className="text-[9px] text-[#475569]">
            {t('fewshot.regions')} ({regions.length})
          </div>
          <div className="space-y-1 flex-1 overflow-y-auto">
            {regions.map((r, i) => {
              const colors = TYPE_COLORS[r.type];
              return (
                <div
                  key={i}
                  className={`flex items-center gap-1 px-1.5 py-1 rounded text-[9px] cursor-pointer transition-colors ${
                    selectedIdx === i ? 'bg-white/10 border border-white/20' : 'bg-[#0f172a] border border-[#334155]'
                  }`}
                  onClick={() => setSelectedIdx(selectedIdx === i ? null : i)}
                >
                  <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: colors.border }} />
                  <span className="flex-1 truncate" style={{ color: colors.text }}>{r.label}</span>
                  <span className="text-[8px] text-[#475569]">
                    [{r.bbox.map(v => v.toFixed(0)).join(',')}]
                  </span>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDeleteRegion(i); }}
                    className="text-[#475569] hover:text-red-400 transition-colors"
                  >
                    <X size={9} />
                  </button>
                </div>
              );
            })}
          </div>

          {/* Action buttons */}
          <div className="flex flex-col gap-1.5 pt-2 border-t border-[#1e293b]">
            <button
              onClick={handleSave}
              disabled={regions.length === 0 || saving}
              className="flex items-center justify-center gap-1 text-[10px] px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <Save size={10} />
              {saving ? '...' : editingId ? t('prompts.save') : t('fewshot.saveExample')}
            </button>
            <button
              onClick={() => setMode('list')}
              className="text-[10px] text-[#64748b] hover:text-white transition-colors"
            >
              {t('toolbar.cancel')}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── List mode ──
  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center justify-between px-3 py-1.5 shrink-0 border-b border-[#1e293b]">
        <div className="text-[10px] text-[#94a3b8]">
          {t('fewshot.count', { count: String(examples.length) })}
        </div>
        <div>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleFileChange}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1 text-[10px] px-2.5 py-1 rounded bg-emerald-600/80 text-white hover:bg-emerald-500 transition-colors"
          >
            <Plus size={9} />
            {t('fewshot.addNew')}
          </button>
        </div>
      </div>

      {/* Example list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1.5">
        {examples.length === 0 ? (
          <div className="text-center py-8">
            <ImageIcon size={24} className="mx-auto text-[#334155] mb-2" />
            <div className="text-[11px] text-[#475569] mb-1">{t('fewshot.empty')}</div>
            <div className="text-[9px] text-[#334155]">{t('fewshot.emptyHint')}</div>
          </div>
        ) : (
          examples.map((ex) => (
            <ExampleListItem
              key={ex.id}
              example={ex}
              onDelete={handleDeleteExample}
              onSelect={handleEditExample}
            />
          ))
        )}
      </div>
    </div>
  );
}
