import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { usePipelineStore } from '../store/pipelineStore';
import { useT } from '../i18n/useI18n';
import {
  FileSpreadsheet, Wand2, Filter, GitBranch, Merge, Calculator, Layers,
  Sparkles, Tags, BookOpen, MapPin, Library, FileDown, FileJson,
  Braces, Globe, Copy, Table2, Shuffle, Puzzle, SearchCheck, WandSparkles,
  Eye, Image,
} from 'lucide-react';

const ICONS: Record<string, any> = {
  FileSpreadsheet, Wand2, Filter, GitBranch, Merge, Calculator, Layers,
  Sparkles, Tags, BookOpen, MapPin, Library, FileDown, FileJson,
  Braces, Globe, Copy, Table2, Shuffle, Puzzle, SearchCheck, WandSparkles,
  Eye, Image,
};

const CATEGORY_COLORS: Record<string, string> = {
  input: '#3b82f6',
  transform: '#10b981',
  ai: '#8b5cf6',
  lookup: '#f59e0b',
  output: '#ef4444',
  plugin: '#ec4899',
};

function FlowNode({ id, data, selected }: NodeProps) {
  const t = useT();
  const getNodeDefinition = usePipelineStore((s) => s.getNodeDefinition);
  const selectNode = usePipelineStore((s) => s.selectNode);
  const nodeType = data.nodeType as string;
  const defn = getNodeDefinition(nodeType);

  if (!defn) return <div>Unknown: {nodeType}</div>;

  const IconComp = ICONS[defn.icon] || FileSpreadsheet;
  const color = CATEGORY_COLORS[defn.category] || '#6b7280';
  const status = data.status as string;
  const message = data.message as string;
  const error = data.error as string;

  return (
    <div
      onClick={() => selectNode(id)}
      className={`rounded-lg overflow-hidden shadow-lg min-w-[180px] border transition-all ${
        selected ? 'border-blue-400 ring-2 ring-blue-400/30' : 'border-[#334155]'
      }`}
      style={{ background: '#1e293b' }}
    >
      {/* Header */}
      <div
        className="flex items-center gap-2 px-3 py-2 text-white text-sm font-medium"
        style={{ background: color }}
      >
        <IconComp size={14} />
        <span>{t(`node.${nodeType}`, (data.label as string) || defn.label)}</span>
      </div>

      {/* Status bar */}
      <div className="px-3 py-1.5 text-xs text-[#94a3b8] flex items-center gap-2">
        {status === 'running' && (
          <>
            <span className="inline-block w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
            <span>{message || t('st.running')}</span>
          </>
        )}
        {status === 'success' && (
          <>
            <span className="text-emerald-400">&#10003;</span>
            <span className="text-emerald-400">{message || t('st.done')}</span>
          </>
        )}
        {status === 'error' && (
          <>
            <span className="text-red-400">&#10007;</span>
            <span className="text-red-400 truncate max-w-[140px]" title={error}>{error || t('st.error')}</span>
          </>
        )}
        {status === 'skipped' && (
          <span className="text-yellow-400/60">{t('st.skipped')}</span>
        )}
        {(!status || status === 'idle') && (
          <span className="text-[#475569]">{t(`cat.${defn.category}`, defn.category)}</span>
        )}
      </div>

      {/* Handles */}
      {defn.inputs.map((port, i) => (
        <Handle
          key={`in-${port.name}`}
          type="target"
          position={Position.Left}
          id={port.name}
          style={{ top: `${30 + i * 24}px` }}
          title={port.label}
        />
      ))}
      {defn.outputs.map((port, i) => (
        <Handle
          key={`out-${port.name}`}
          type="source"
          position={Position.Right}
          id={port.name}
          style={{ top: `${30 + i * 24}px` }}
          title={port.label}
        />
      ))}

      {/* Port labels for multi-output */}
      {defn.outputs.length > 1 && (
        <div className="px-3 pb-2">
          {defn.outputs.map((port) => (
            <div key={port.name} className="text-[10px] text-[#64748b] text-right">
              {port.label} &#8594;
            </div>
          ))}
        </div>
      )}
      {defn.inputs.length > 1 && (
        <div className="px-3 pb-2">
          {defn.inputs.map((port) => (
            <div key={port.name} className="text-[10px] text-[#64748b]">
              &#8592; {port.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default memo(FlowNode);
