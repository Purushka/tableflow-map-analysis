import { create } from 'zustand';
import {
  type Node,
  type Edge,
  type OnNodesChange,
  type OnEdgesChange,
  type OnConnect,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
} from '@xyflow/react';
import type { NodeDefinition } from '../types/pipeline';
import type { Locale } from '../i18n/locales';

interface PipelineState {
  // Pipeline
  pipelineId: string | null;
  pipelineName: string;
  nodes: Node[];
  edges: Edge[];
  nodeDefinitions: NodeDefinition[];
  selectedNodeId: string | null;
  isRunning: boolean;
  locale: Locale;
  runProgress: {
    totalNodes: number;
    completedNodes: number;
    currentNodeId: string | null;
    currentNodeLabel: string;
    currentMessage: string;
    hasError: boolean;
  } | null;
  livePreview: {
    columns: string[];
    new_columns: string[];
    rows: Record<string, string>[];
    total_rows: number;
    processed_rows: number | null;
    node_id: string;
    node_label: string;
    partial_file: string | null;
  } | null;
  outputFiles: { filename: string; node_label: string }[];
  aiDebugLogs: { ts: number; row: number; total: number; phase: string; text: string; image_path?: string; filename?: string; result?: Record<string, string>; raw?: Record<string, any> }[];

  // Actions
  setLocale: (locale: Locale) => void;
  setNodeDefinitions: (defs: NodeDefinition[]) => void;
  setPipeline: (id: string, name: string, nodes: Node[], edges: Edge[]) => void;
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  addNode: (node: Node) => void;
  selectNode: (nodeId: string | null) => void;
  updateNodeConfig: (nodeId: string, config: Record<string, any>) => void;
  updateNodeStatus: (nodeId: string, status: string, message?: string, error?: string) => void;
  setIsRunning: (running: boolean) => void;
  setRunProgress: (progress: PipelineState['runProgress']) => void;
  setLivePreview: (data: PipelineState['livePreview']) => void;
  setOutputFiles: (files: PipelineState['outputFiles']) => void;
  addAiDebugLog: (log: PipelineState['aiDebugLogs'][0]) => void;
  clearAiDebugLogs: () => void;
  resetStatuses: () => void;
  deleteSelected: () => void;
  getNodeDefinition: (type: string) => NodeDefinition | undefined;
}

let nodeCounter = 0;

export const usePipelineStore = create<PipelineState>((set, get) => ({
  pipelineId: null,
  pipelineName: 'Untitled Pipeline',
  nodes: [],
  edges: [],
  nodeDefinitions: [],
  selectedNodeId: null,
  isRunning: false,
  runProgress: null,
  livePreview: null,
  outputFiles: [],
  aiDebugLogs: [],
  locale: (typeof window !== 'undefined' && localStorage.getItem('tableflow-locale') as Locale) || 'en',

  setLocale: (locale) => {
    localStorage.setItem('tableflow-locale', locale);
    set({ locale });
  },
  setNodeDefinitions: (defs) => set({ nodeDefinitions: defs }),

  setPipeline: (id, name, nodes, edges) =>
    set({ pipelineId: id, pipelineName: name, nodes, edges }),

  onNodesChange: (changes) =>
    set({ nodes: applyNodeChanges(changes, get().nodes) }),

  onEdgesChange: (changes) =>
    set({ edges: applyEdgeChanges(changes, get().edges) }),

  onConnect: (connection) =>
    set({
      edges: addEdge(
        { ...connection, id: `e-${Date.now()}` },
        get().edges,
      ),
    }),

  addNode: (node) => set({ nodes: [...get().nodes, node] }),

  selectNode: (nodeId) => set({ selectedNodeId: nodeId }),

  updateNodeConfig: (nodeId, config) =>
    set({
      nodes: get().nodes.map((n) =>
        n.id === nodeId
          ? { ...n, data: { ...n.data, config: { ...(n.data.config || {}), ...config } } }
          : n,
      ),
    }),

  updateNodeStatus: (nodeId, status, message, error) =>
    set({
      nodes: get().nodes.map((n) =>
        n.id === nodeId
          ? { ...n, data: { ...n.data, status, message: message || '', error: error || '' } }
          : n,
      ),
    }),

  setIsRunning: (running) => set({ isRunning: running }),

  setRunProgress: (progress) => set({ runProgress: progress }),

  setLivePreview: (data) => set({ livePreview: data }),

  setOutputFiles: (files) => set({ outputFiles: files }),

  addAiDebugLog: (log) => set({ aiDebugLogs: [...get().aiDebugLogs.slice(-199), log] }),
  clearAiDebugLogs: () => set({ aiDebugLogs: [] }),

  resetStatuses: () =>
    set({
      nodes: get().nodes.map((n) => ({
        ...n,
        data: { ...n.data, status: 'idle', message: '', error: '' },
      })),
    }),

  deleteSelected: () => {
    const { selectedNodeId, nodes, edges } = get();
    if (!selectedNodeId) return;
    set({
      nodes: nodes.filter((n) => n.id !== selectedNodeId),
      edges: edges.filter(
        (e) => e.source !== selectedNodeId && e.target !== selectedNodeId,
      ),
      selectedNodeId: null,
    });
  },

  getNodeDefinition: (type) =>
    get().nodeDefinitions.find((d) => d.type === type),
}));

export const getNextNodeId = () => `node-${++nodeCounter}-${Date.now()}`;
