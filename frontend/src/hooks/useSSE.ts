/**
 * useSSE — extracts all SSE stream handling logic from Toolbar.
 * Returns { handleRun } which triggers a pipeline run with real-time event processing.
 */

import { usePipelineStore } from '../store/pipelineStore';
import { useSettingsStore } from '../store/settingsStore';
import { useMapAnalysisStore } from '../store/mapAnalysisStore';
import {
  createPipeline, updatePipeline, runPipelineSSE,
} from '../api/client';

// ── format ai_debug text from event data ──

function formatAiDebugText(phase: string, d: Record<string, any>): string {
  switch (phase) {
    case 'prompt':
      return `[PROMPT] sys: ${(d.system_prompt || '').slice(0, 200)}...\nuser: ${(d.user_prompt || '').slice(0, 400)}`;
    case 'response':
      return `[RESPONSE] ${d.raw_response || '(empty)'}`;
    case 'error':
      return `[ERROR] ${d.error || 'unknown'}`;
    case 'L1_scan':
      return `[L1 SCAN] ${d.filename || ''} (${d.full_size} → thumb ${d.thumb_size}, ${d.format || ''})`;
    case 'L1_result':
      return `[L1 RESULT] ${d.filename || ''}: ${d.text_regions || 0} text regions [${(d.labels || []).join(', ')}]`;
    case 'L2a_ocr':
      return `[L2a OCR] ${d.filename || ''} → "${d.region}" crop ${d.crop_size} (${d.format || ''})`;
    case 'L2a_result':
      return `[L2a TEXT] ${d.filename || ''} → "${d.region}": ${(d.text_preview || '').slice(0, 200)}`;
    case 'L2b_planning':
      return `[L2b PLAN] ${d.filename || ''}: read ${d.ocr_regions_read || 0} text regions, planning map exploration...`;
    case 'L2b_result': {
      const rc = d.map_regions || {};
      const counts = Object.entries(rc).map(([k, v]) => `${k}:${v}`).join(' ');
      return `[L2b RESULT] ${d.filename || ''}: "${(d.understanding || '').slice(0, 200)}" → regions: ${counts} [${(d.labels || []).join(', ')}]`;
    }
    case 'region_preview':
      return `[PREVIEW] ${d.filename || ''}: ${d.num_regions || 0} regions visualized`;
    case 'L3_crop':
      return `[L3 ${(d.type || '').toUpperCase()}] ${d.filename || ''} → "${d.region}" crop ${d.crop_size} (${d.format || ''})`;
    case 'L3_result':
      return `[L3 RESULT] ${d.filename || ''} → "${d.region}" [${d.type}]: ${(d.preview || '').slice(0, 200)}`;
    case 'synthesis':
      return `[SYNTHESIS] ${d.filename || ''}: text=${d.text_ocr || 0} coord=${d.coordinate_strips || 0} samples=${d.samples || 0}`;
    case 'supplement_crop':
      return `[SUPP CROP] ${d.filename || ''} → field="${d.field}" bbox=[${d.bbox}] crop=${d.crop_size || ''}`;
    case 'supplement_result':
      return `[SUPP RESULT] ${d.filename || ''} → field="${d.field}" value="${(d.value || '').slice(0, 100)}" confident=${d.confident}`;
    case 'extract_start':
      return `[EXTRACT START] ${d.filename || ''} (${d.full_size} → encoded ${d.encoded_size})`;
    case 'extract_result':
      return `[EXTRACT R${d.round ?? 0}] ${d.filename || ''}: ${d.fields_count || 0} grounded fields + ${d.type_specific_count || 0} ts — [${(d.field_names || []).slice(0, 10).join(', ')}]`;
    case 'critic_start':
      return `[CRITIC START] ${d.filename || ''} model=${d.critic_model || ''} claims=${d.claim_count || 0}`;
    case 'critic_review': {
      const flagged = d.flagged_count ?? (d.flagged_fields?.length || 0);
      const tok = d.tokens ? ` tokens=${d.tokens.input_tokens || 0}in+${d.tokens.output_tokens || 0}out` : '';
      return `[CRITIC] ${d.filename || ''} flagged=${flagged}${tok}${flagged ? ` → [${(d.flagged_fields || []).join(', ')}]` : ''}`;
    }
    case 'correction_sent':
      return `[CORRECTION R${d.round ?? 0}] ${d.filename || ''}: sent ${(d.flagged_fields || []).length} flagged fields back to extractor`;
    case 'correction_result':
      return `[CORRECTION R${d.round ?? 0}] ${d.filename || ''}: extractor returned ${d.fields_count || 0} fields + ${d.type_specific_count || 0} ts`;
    case 'evidence_preview':
      return `[EVIDENCE] ${d.filename || ''}: ${d.num_regions || 0} bboxes visualized`;
    case 'evidence_preview_error':
      return `[EVIDENCE ERROR] ${d.error || ''}`;
    case 'critic_correction':
      return `[CRITIC FIX] ${d.filename || ''} field="${d.field}" demoted (was: "${(d.old_value || '').slice(0, 80)}") — ${d.note || ''}`;
    case 'done': {
      const usage = d.token_usage;
      const tokenInfo = usage
        ? ` | tokens: ${usage.input_tokens?.toLocaleString()}in + ${usage.output_tokens?.toLocaleString()}out = ${usage.total_tokens?.toLocaleString()}`
        : '';
      return `[DONE] ${d.filename || ''}: ${d.fields_filled || 0} fields filled${tokenInfo}`;
    }
    case 'post_process_start':
      return `[POST_PROCESS_START] map_count=${d.map_count || 0}`;
    case 'post_process_refined':
      return `[POST_PROCESS_REFINED] ${d.filename || ''}: fields_refined=[${(d.fields_refined || []).join(',')}]`;
    case 'post_process_done':
      return `[POST_PROCESS_DONE] map_count=${d.map_count || 0}`;
    case 'debug_archive':
      return `[ARCHIVE] Debug logs archived: ${d.entry_count || 0} entries → ${d.archive_path || ''}`;
    case 'region_preview_error':
      return `[PREVIEW ERROR] ${d.error || ''}`;
    default: {
      const parts = Object.entries(d)
        .filter(([k]) => !['row', 'total', 'phase'].includes(k))
        .map(([k, v]) => `${k}=${typeof v === 'string' ? v.slice(0, 100) : JSON.stringify(v)}`)
        .join(' ');
      return `[${phase.toUpperCase()}] ${parts}`;
    }
  }
}

// ── feed structured data to MapAnalysisStore ──

function feedMapAnalysis(phase: string, d: Record<string, any>) {
  const mapStore = useMapAnalysisStore.getState();
  const fn = d.filename as string | undefined;
  if (!fn) return;

  const MAP_PHASES = [
    // Grounded extraction + critic loop
    'extract_start', 'extract_result',
    'critic_start', 'critic_review',
    'correction_sent', 'correction_result',
    'evidence_preview', 'done',
    // Legacy phases — kept so old archived runs replay correctly
    'L1_scan', 'L1_result', 'L2a_ocr', 'L2a_result',
    'L2b_planning', 'L2b_result', 'L3_crop', 'L3_result',
    'region_preview', 'synthesis',
    'direct_main', 'direct_result', 'supplement_crop', 'supplement_result',
    'critic_correction',
    'post_process_start', 'post_process_refined', 'post_process_done',
  ];
  if (!MAP_PHASES.includes(phase)) return;

  // Track expected total from first event
  if (d.total && d.total > mapStore.expectedTotal) {
    mapStore.setExpectedTotal(d.total);
  }

  // Handle post-process phases (no per-map update needed)
  if (phase === 'post_process_start') {
    mapStore.setPostProcessPhase('running');
    return;
  }
  if (phase === 'post_process_done') {
    mapStore.setPostProcessPhase('done');
    return;
  }
  if (phase === 'post_process_refined') {
    // Update the refined fields list on the map entry
    const refinedFields = d.fields_refined as string[] | undefined;
    if (refinedFields && refinedFields.length > 0) {
      const existing = mapStore.maps[fn];
      if (existing) {
        mapStore.updateMap(fn, {
          postProcessRefined: refinedFields,
        });
      }
    }
    return;
  }

  mapStore.updateMap(fn, {
    row: d.row || 0,
    total: d.total || 0,
    filename: fn,
    phase,
  });

  if (phase === 'extract_start' || phase === 'L1_scan' || phase === 'direct_main') {
    mapStore.updateMap(fn, { sourceImage: d.source_image });
    mapStore.openPanel(fn);
  } else if (phase === 'evidence_preview' || phase === 'region_preview') {
    mapStore.updateMap(fn, { previewPath: d.preview_path });
    const regions = d.regions as Array<{ label: string; type: string; bbox: number[] }>;
    if (regions) {
      for (const r of regions) {
        mapStore.addOrUpdateRegion(fn, {
          label: r.label,
          type: r.type as 'text' | 'border' | 'coordinate_strip' | 'map_sample',
          bbox: r.bbox as [number, number, number, number],
          status: 'pending',
        });
      }
    }
  } else if (phase === 'L2a_ocr' || phase === 'L3_crop') {
    const regionLabel = d.region as string;
    if (regionLabel) {
      mapStore.addOrUpdateRegion(fn, {
        label: regionLabel,
        cropPath: d.crop_path,
        bbox: d.bbox,
        position: d.position,
        promptPreview: d.prompt_preview,
        status: 'processing',
      });
    }
  } else if (phase === 'L2a_result' || phase === 'L3_result') {
    const regionLabel = d.region as string;
    if (regionLabel) {
      mapStore.addOrUpdateRegion(fn, {
        label: regionLabel,
        cropPath: d.crop_path,
        bbox: d.bbox,
        llmOutput: d.llm_output || d.text_preview,
        promptPreview: d.prompt_preview,
        status: 'done',
      });
    }
  } else if (phase === 'supplement_crop') {
    const field = d.field as string;
    if (field) {
      mapStore.addOrUpdateRegion(fn, {
        label: `Supp: ${field}`,
        type: ('coord' in field || 'bbox' in field || 'scale' in field)
          ? 'coordinate_strip' : 'map_sample',
        bbox: d.bbox,
        cropPath: d.crop_path,
        promptPreview: d.prompt_preview,
        status: 'processing',
      });
    }
  } else if (phase === 'supplement_result') {
    const field = d.field as string;
    if (field) {
      mapStore.addOrUpdateRegion(fn, {
        label: `Supp: ${field}`,
        type: ('coord' in field || 'bbox' in field || 'scale' in field)
          ? 'coordinate_strip' : 'map_sample',
        bbox: d.bbox,
        cropPath: d.crop_path,
        promptPreview: d.prompt_preview,
        llmOutput: d.llm_output,
        supplementMeta: {
          field,
          reason: d.reason || '',
          value: d.value || '',
          confident: !!d.confident,
        },
        status: 'done',
      });
    }
  } else if (phase === 'critic_review') {
    // New grounding-critic verdicts shape: {ok, issue, what_you_see}
    const verdicts = d.verdicts as Record<string, { ok: boolean; issue: string; what_you_see: string }> | undefined;
    if (verdicts) {
      const auditCompat: Record<string, { evidence: string; note: string }> = {};
      for (const [k, v] of Object.entries(verdicts)) {
        auditCompat[k] = {
          evidence: v.ok ? 'directly_visible' : 'inferred_questionable',
          note: v.ok ? '' : `${v.issue || ''}${v.what_you_see ? ` — sees: ${v.what_you_see}` : ''}`,
        };
      }
      mapStore.updateMap(fn, { criticAudit: auditCompat });
    } else if (d.audit) {
      // Legacy audit shape
      mapStore.updateMap(fn, { criticAudit: d.audit });
    }
  } else if (phase === 'critic_correction') {
    const field = d.field as string | undefined;
    if (field) {
      const existing = mapStore.maps[fn];
      const corrections = (existing?.criticCorrections || []).slice();
      corrections.push({
        field,
        oldValue: String(d.old_value || ''),
        note: String(d.note || ''),
      });
      mapStore.updateMap(fn, { criticCorrections: corrections });
    }
  } else if (phase === 'done') {
    mapStore.updateMap(fn, {
      done: true,
      fieldsFilled: d.fields_filled,
      synthesisResult: d.synthesis_result || undefined,
      tokenUsage: d.token_usage || undefined,
    });
  }
}

// ── main hook ──

export function useSSE() {
  const handleSave = async () => {
    const { pipelineId, pipelineName, nodes, edges, setPipeline } =
      usePipelineStore.getState();
    const data = {
      name: pipelineName,
      nodes: nodes.map((n) => ({
        id: n.id,
        type: n.data.nodeType,
        position: n.position,
        data: { label: n.data.label, config: n.data.config || {} },
      })),
      edges: edges.map((e) => ({
        id: e.id,
        source: e.source,
        sourceHandle: e.sourceHandle || 'output',
        target: e.target,
        targetHandle: e.targetHandle || 'input',
      })),
    };

    if (pipelineId) {
      await updatePipeline(pipelineId, data);
    } else {
      const result = await createPipeline(data);
      setPipeline(result.id, result.name, nodes, edges);
    }
  };

  const handleRun = async () => {
    await handleSave();
    const store = usePipelineStore.getState();
    const pid = store.pipelineId;
    if (!pid) return;

    const apiKeys = useSettingsStore.getState().getAllApiKeys();
    store.setIsRunning(true);
    store.resetStatuses();
    store.setLivePreview(null);
    store.setOutputFiles([]);
    store.clearAiDebugLogs();
    useMapAnalysisStore.getState().clear();

    let completedNodes = 0;
    let totalNodes = 0;
    let hasError = false;

    try {
      const response = await runPipelineSSE(pid, apiKeys);
      const reader = response.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const event = JSON.parse(line.slice(6));
            const { setRunProgress, updateNodeStatus, setLivePreview, setOutputFiles, addAiDebugLog } =
              usePipelineStore.getState();

            if (event.event === 'pipeline_start') {
              totalNodes = event.data.total_nodes || 0;
              completedNodes = 0;
              hasError = false;
              setRunProgress({ totalNodes, completedNodes: 0, currentNodeId: null, currentNodeLabel: '', currentMessage: '', hasError: false });
            } else if (event.event === 'node_status') {
              const { node_id, status, message, error } = event.data;
              updateNodeStatus(node_id, status, message, error);

              const storeNodes = usePipelineStore.getState().nodes;
              const label = (storeNodes.find((n) => n.id === node_id)?.data?.label as string) || node_id;

              if (status === 'running') {
                setRunProgress({ totalNodes, completedNodes, currentNodeId: node_id, currentNodeLabel: label, currentMessage: message || '', hasError });
              } else if (status === 'success') {
                completedNodes++;
                setRunProgress({ totalNodes, completedNodes, currentNodeId: node_id, currentNodeLabel: label, currentMessage: message || '', hasError });
              } else if (status === 'error') {
                completedNodes++;
                hasError = true;
                setRunProgress({ totalNodes, completedNodes, currentNodeId: node_id, currentNodeLabel: label, currentMessage: error || message || '', hasError: true });
              }
            } else if (event.event === 'node_data_preview') {
              setLivePreview({
                columns: event.data.columns || [],
                new_columns: event.data.new_columns || [],
                rows: event.data.rows || [],
                total_rows: event.data.total_rows || 0,
                processed_rows: event.data.processed_rows ?? null,
                node_id: event.data.node_id || '',
                node_label: event.data.node_label || '',
                partial_file: null,
              });
            } else if (event.event === 'ai_debug') {
              const d = event.data;
              const phase = d.phase || '';
              const text = formatAiDebugText(phase, d);

              addAiDebugLog({
                ts: Date.now(),
                row: d.row || 0,
                total: d.total || 0,
                phase,
                text,
                image_path: d.image_path || undefined,
                filename: d.filename || undefined,
                result: d.result || undefined,
                raw: d,
              });

              feedMapAnalysis(phase, d);
            } else if (event.event === 'pipeline_complete') {
              const partialFile = event.data.partial_file || null;
              if (partialFile) {
                const prev = usePipelineStore.getState().livePreview;
                if (prev) setLivePreview({ ...prev, partial_file: partialFile });
              }
              const files = event.data.output_files || [];
              if (files.length > 0) setOutputFiles(files);
              setRunProgress({ totalNodes, completedNodes: totalNodes, currentNodeId: null, currentNodeLabel: '', currentMessage: '', hasError });
              if (files.length === 0) {
                setTimeout(() => usePipelineStore.getState().setRunProgress(null), 3000);
              }
            }
          } catch { /* skip malformed lines */ }
        }
      }
    } catch (err) {
      console.error('Pipeline run error:', err);
      usePipelineStore.getState().setRunProgress(null);
    } finally {
      usePipelineStore.getState().setIsRunning(false);
    }
  };

  return { handleSave, handleRun };
}
