// @refresh reset
import { useState, useEffect, useRef, useCallback } from 'react';
import { usePipelineStore } from '../store/pipelineStore';
import { uploadFile, getFileColumns } from '../api/client';
import { useT } from '../i18n/useI18n';
import { X, Upload, Trash2, ChevronDown, ChevronRight, GripVertical } from 'lucide-react';
import OperationsEditor from './editors/OperationsEditor';
import AggregationsEditor from './editors/AggregationsEditor';
import RulesEditor from './editors/RulesEditor';
import FieldMappingEditor from './editors/FieldMappingEditor';
import ColumnsEditor from './editors/ColumnsEditor';
import AutofillFieldsEditor from './editors/AutofillFieldsEditor';
import PromptTemplateEditor from './editors/PromptTemplateEditor';
import ModelSelector from './editors/ModelSelector';

// Map (nodeType, fieldName) → visual editor component
const VISUAL_EDITORS: Record<string, string> = {
  'transform_normalize:operations': 'operations',
  'transform_group:aggregations': 'aggregations',
  'transform_split:rules': 'rules',
  'ai_enrich:json_field_mapping': 'fieldMapping',
  'ai_vision:json_field_mapping': 'fieldMapping',
  'output_xlsx:columns': 'columns',
  'ai_autofill:fields_to_fill': 'autofillFields',
};

const PROMPT_FIELDS = new Set([
  'transform_formula:formula',
  'ai_classify:prompt_template',
  'ai_enrich:system_prompt',
  'ai_enrich:user_prompt_template',
  'ai_search:query_template',
  'ai_search:system_prompt',
  'ai_autofill:query_template',
  'ai_autofill:system_prompt',
  'ai_vision:system_prompt',
  'ai_vision:user_prompt_template',
  'ai_cross_match:system_prompt',
]);

const CONFIG_WIDTH_KEY = 'tf-config-panel-width';

function loadWidth(): number {
  try {
    const v = localStorage.getItem(CONFIG_WIDTH_KEY);
    if (v) return Math.max(240, Math.min(600, Number(v)));
  } catch { /* ignore */ }
  return 320;
}

export default function ConfigPanel() {
  const t = useT();
  const selectedNodeId = usePipelineStore((s) => s.selectedNodeId);
  const nodes = usePipelineStore((s) => s.nodes);
  const edges = usePipelineStore((s) => s.edges);
  const getNodeDefinition = usePipelineStore((s) => s.getNodeDefinition);
  const updateNodeConfig = usePipelineStore((s) => s.updateNodeConfig);
  const selectNode = usePipelineStore((s) => s.selectNode);
  const deleteSelected = usePipelineStore((s) => s.deleteSelected);

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  const nodeType = selectedNode?.data.nodeType as string || '';
  const defn = selectedNode ? getNodeDefinition(nodeType) : null;

  const [upstreamColumns, setUpstreamColumns] = useState<string[]>([]);
  const [showExample, setShowExample] = useState(false);
  const [width, setWidth] = useState(loadWidth);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startW = useRef(0);

  const onResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    startX.current = e.clientX;
    startW.current = width;

    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      // Dragging left edge: moving left increases width
      const delta = startX.current - ev.clientX;
      const newW = Math.max(240, Math.min(600, startW.current + delta));
      setWidth(newW);
    };
    const onUp = () => {
      dragging.current = false;
      try { localStorage.setItem(CONFIG_WIDTH_KEY, String(width)); } catch { /* ignore */ }
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }, [width]);

  // Resolve upstream columns by tracing edges
  useEffect(() => {
    if (!selectedNodeId) return;

    const cols = new Set<string>();
    const visited = new Set<string>();

    function traceBack(nodeId: string) {
      if (visited.has(nodeId)) return;
      visited.add(nodeId);
      const incoming = edges.filter((e) => e.target === nodeId);
      for (const e of incoming) {
        const srcNode = nodes.find((n) => n.id === e.source);
        const srcConfig = srcNode?.data?.config as Record<string, any> | undefined;
        if (srcConfig?.file_id) {
          getFileColumns(srcConfig.file_id).then((res) => {
            res.columns.forEach((c: string) => cols.add(c));
            setUpstreamColumns(Array.from(cols));
          });
        }
        traceBack(e.source);
      }
    }

    traceBack(selectedNodeId);
  }, [selectedNodeId, edges, nodes]);

  if (!selectedNode || !defn) {
    return (
      <div className="bg-[#1e293b] border-l border-[#334155] p-4 flex items-center justify-center"
           style={{ width }}>
        <p className="text-sm text-[#64748b]">{t('cfg.selectNode')}</p>
      </div>
    );
  }

  const config = selectedNode.data.config as Record<string, any> || {};

  const handleChange = (name: string, value: any) => {
    updateNodeConfig(selectedNodeId!, { [name]: value });
  };

  const handleFileUpload = async (name: string, file: File) => {
    const result = await uploadFile(file);
    handleChange(name, result.file_id);
  };

  const handleJsonChange = (name: string, value: any) => {
    // For visual editors, store the structured value directly
    // The backend will receive the structured data
    handleChange(name, typeof value === 'string' ? value : JSON.stringify(value));
  };

  const parseJsonValue = (val: any): any => {
    if (typeof val === 'string') {
      try { return JSON.parse(val); } catch { return val; }
    }
    return val;
  };

  const exampleKey = `ex.${nodeType}`;
  const exampleText = t(exampleKey, '');

  return (
    <div className="bg-[#1e293b] border-l border-[#334155] flex flex-col h-full overflow-hidden relative"
         style={{ width }}>
      {/* Resize handle (left edge) */}
      <div
        className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize z-10 hover:bg-blue-500/30 transition-colors group flex items-center"
        onMouseDown={onResizeMouseDown}
      >
        <GripVertical size={10} className="text-[#334155] group-hover:text-blue-400 -ml-0.5" />
      </div>
      {/* Header */}
      <div className="px-4 py-3 border-b border-[#334155] flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-white">{t(`node.${nodeType}`, defn.label)}</h2>
          <p className="text-xs text-[#64748b]">{t(`nd.${nodeType}`, defn.description)}</p>
        </div>
        <div className="flex gap-1">
          <button
            onClick={deleteSelected}
            className="p-1.5 rounded hover:bg-red-500/20 text-red-400 transition-colors"
            title={t('cfg.deleteNode')}
          >
            <Trash2 size={14} />
          </button>
          <button
            onClick={() => selectNode(null)}
            className="p-1.5 rounded hover:bg-[#334155] text-[#94a3b8] transition-colors"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Usage example (collapsible) */}
      {exampleText && (
        <div className="px-4 py-2 border-b border-[#334155]">
          <button
            onClick={() => setShowExample(!showExample)}
            className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
          >
            {showExample ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            {t('cfg.examples')}
          </button>
          {showExample && (
            <p className="mt-1 text-xs text-[#94a3b8] leading-relaxed">{exampleText}</p>
          )}
        </div>
      )}

      {/* Config Fields */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {defn.config_fields.map((field) => {
          const editorKey = `${nodeType}:${field.name}`;
          const hasVisualEditor = VISUAL_EDITORS[editorKey];
          const isPromptField = PROMPT_FIELDS.has(editorKey);

          // Hide LLM-only fields when match_mode is "hybrid"
          const LLM_ONLY_FIELDS = ['model', 'system_prompt', 'batch_size', 'max_tokens', 'concurrency'];
          if (config.match_mode === 'hybrid' && LLM_ONLY_FIELDS.includes(field.name)) return null;

          return (
            <div key={field.name}>
              <label className="block text-xs font-medium text-[#94a3b8] mb-1">
                {t(`fl.${field.name}`, field.label)}
                {field.required && <span className="text-red-400 ml-1">*</span>}
              </label>

              {/* Visual editors for JSON fields */}
              {hasVisualEditor === 'operations' && (
                <OperationsEditor
                  value={parseJsonValue(config[field.name]) || []}
                  onChange={(v) => handleJsonChange(field.name, v)}
                  columns={upstreamColumns}
                  nodeType={nodeType}
                />
              )}

              {hasVisualEditor === 'aggregations' && (
                <AggregationsEditor
                  value={parseJsonValue(config[field.name]) || []}
                  onChange={(v) => handleJsonChange(field.name, v)}
                  columns={upstreamColumns}
                  nodeType={nodeType}
                />
              )}

              {hasVisualEditor === 'rules' && (
                <RulesEditor
                  value={parseJsonValue(config[field.name]) || []}
                  onChange={(v) => handleJsonChange(field.name, v)}
                  columns={upstreamColumns}
                  nodeType={nodeType}
                />
              )}

              {hasVisualEditor === 'fieldMapping' && (
                <FieldMappingEditor
                  value={parseJsonValue(config[field.name]) || {}}
                  onChange={(v) => handleJsonChange(field.name, v)}
                  columns={upstreamColumns}
                  nodeType={nodeType}
                />
              )}

              {hasVisualEditor === 'columns' && (
                <ColumnsEditor
                  value={parseJsonValue(config[field.name]) || []}
                  onChange={(v) => handleJsonChange(field.name, v)}
                  columns={upstreamColumns}
                  nodeType={nodeType}
                />
              )}

              {hasVisualEditor === 'autofillFields' && (
                <AutofillFieldsEditor
                  value={parseJsonValue(config[field.name]) || []}
                  onChange={(v) => handleJsonChange(field.name, v)}
                  columns={upstreamColumns}
                  nodeType={nodeType}
                />
              )}

              {/* Enhanced prompt template editor */}
              {!hasVisualEditor && isPromptField && (
                <PromptTemplateEditor
                  value={config[field.name] ?? field.default ?? ''}
                  onChange={(v) => handleChange(field.name, v)}
                  columns={upstreamColumns}
                  nodeType={nodeType}
                  fieldName={field.name}
                  rows={field.type === 'json' ? 6 : 4}
                />
              )}

              {/* Standard field types (only if no visual editor) */}
              {!hasVisualEditor && !isPromptField && field.type === 'text' && (
                <input
                  type="text"
                  value={config[field.name] ?? field.default ?? ''}
                  onChange={(e) => handleChange(field.name, e.target.value)}
                  placeholder={field.placeholder}
                  className="w-full px-3 py-2 text-sm bg-[#0f172a] border border-[#334155] rounded-md
                             text-[#e2e8f0] placeholder-[#475569] focus:border-blue-500 focus:outline-none"
                />
              )}

              {!hasVisualEditor && !isPromptField && field.type === 'number' && (
                <input
                  type="number"
                  value={config[field.name] ?? field.default ?? 0}
                  onChange={(e) => handleChange(field.name, Number(e.target.value))}
                  className="w-full px-3 py-2 text-sm bg-[#0f172a] border border-[#334155] rounded-md
                             text-[#e2e8f0] focus:border-blue-500 focus:outline-none"
                />
              )}

              {!hasVisualEditor && !isPromptField && field.type === 'boolean' && (
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={config[field.name] ?? field.default ?? false}
                    onChange={(e) => handleChange(field.name, e.target.checked)}
                    className="rounded border-[#334155] bg-[#0f172a] text-blue-500 focus:ring-blue-500"
                  />
                  <span className="text-sm text-[#e2e8f0]">{field.description || t('cfg.enabled')}</span>
                </label>
              )}

              {!hasVisualEditor && !isPromptField && field.type === 'select' && field.name === 'model' && (
                <ModelSelector
                  value={config[field.name] ?? field.default ?? ''}
                  onChange={(v) => handleChange(field.name, v)}
                />
              )}

              {!hasVisualEditor && !isPromptField && field.type === 'select' && field.name !== 'model' && (
                <select
                  value={config[field.name] ?? field.default ?? ''}
                  onChange={(e) => handleChange(field.name, e.target.value)}
                  className="w-full px-3 py-2 text-sm bg-[#0f172a] border border-[#334155] rounded-md
                             text-[#e2e8f0] focus:border-blue-500 focus:outline-none"
                >
                  <option value="">{t('cfg.select')}</option>
                  {field.options.map((opt) => {
                    const val = typeof opt === 'object' && opt !== null ? opt.value : opt;
                    const label = typeof opt === 'object' && opt !== null ? opt.label : opt;
                    return <option key={val} value={val}>{label}</option>;
                  })}
                </select>
              )}

              {!hasVisualEditor && !isPromptField && field.type === 'column_select' && (
                <select
                  value={config[field.name] ?? ''}
                  onChange={(e) => handleChange(field.name, e.target.value)}
                  className="w-full px-3 py-2 text-sm bg-[#0f172a] border border-[#334155] rounded-md
                             text-[#e2e8f0] focus:border-blue-500 focus:outline-none"
                >
                  <option value="">{t('cfg.selectCol')}</option>
                  {upstreamColumns.map((col) => (
                    <option key={col} value={col}>{col}</option>
                  ))}
                </select>
              )}

              {!hasVisualEditor && !isPromptField && field.type === 'file' && (
                <div className="flex gap-2 items-center">
                  <input
                    type="file"
                    accept={field.accept || ".csv,.xlsx,.xls,.json,.zip"}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) handleFileUpload(field.name, f);
                    }}
                    className="hidden"
                    id={`file-${field.name}`}
                  />
                  <label
                    htmlFor={`file-${field.name}`}
                    className="flex items-center gap-2 px-3 py-2 text-sm bg-[#0f172a] border border-[#334155]
                               rounded-md text-[#e2e8f0] cursor-pointer hover:bg-[#334155] transition-colors"
                  >
                    <Upload size={14} />
                    {config[field.name] ? t('cfg.uploaded') : t('cfg.upload')}
                  </label>
                  {config[field.name] && (
                    <span className="text-xs text-emerald-400 truncate max-w-[120px]">
                      {config[field.name]}
                    </span>
                  )}
                </div>
              )}

              {/* Fallback: plain prompt_template / json that didn't match any special editor */}
              {!hasVisualEditor && !isPromptField && (field.type === 'prompt_template' || field.type === 'json') && (
                <textarea
                  value={config[field.name] ?? field.default ?? ''}
                  onChange={(e) => handleChange(field.name, e.target.value)}
                  placeholder={field.placeholder}
                  rows={field.type === 'json' ? 6 : 4}
                  className="w-full px-3 py-2 text-sm bg-[#0f172a] border border-[#334155] rounded-md
                             text-[#e2e8f0] placeholder-[#475569] focus:border-blue-500 focus:outline-none
                             font-mono resize-y"
                />
              )}

              {field.description && field.type !== 'boolean' && !hasVisualEditor && !isPromptField && (
                <p className="text-xs text-[#475569] mt-1">{field.description}</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
