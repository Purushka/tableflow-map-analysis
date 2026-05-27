import { useState, useEffect, Component, type ReactNode } from 'react';
import { ReactFlowProvider } from '@xyflow/react';
import { usePipelineStore } from './store/pipelineStore';
import { useSettingsStore } from './store/settingsStore';
import { getNodeTypes, getProviders, createPipeline } from './api/client';
import Toolbar from './components/Toolbar';
import RunProgressBar from './components/RunProgressBar';
import NodePalette from './components/NodePalette';
import Canvas from './components/Canvas';
import ConfigPanel from './components/ConfigPanel';
import DataPreview from './components/DataPreview';
import TemplateChooser from './components/TemplateChooser';
import BottomPanelManager from './components/BottomPanelManager';
import type { Template } from './templates/index';

// Error boundary to prevent white screen crashes
class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null; retryCount: number }
> {
  state = { error: null as Error | null, retryCount: 0 };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: any) { console.error('React Error Boundary:', error, info); }
  componentDidUpdate(_: any, prevState: { error: Error | null; retryCount: number }) {
    // Auto-retry once on first error (handles HMR / StrictMode race conditions)
    if (this.state.error && !prevState.error && this.state.retryCount === 0) {
      this.setState({ error: null, retryCount: 1 });
    }
  }
  render() {
    if (this.state.error) {
      return (
        <div className="h-screen w-screen bg-[#0f172a] flex items-center justify-center p-8">
          <div className="max-w-lg bg-[#1e293b] border border-red-500/50 rounded-lg p-6">
            <h2 className="text-red-400 text-lg font-bold mb-2">UI Error</h2>
            <pre className="text-xs text-[#94a3b8] whitespace-pre-wrap break-all mb-4">{this.state.error.message}</pre>
            {this.state.error.stack && (
              <pre className="text-[10px] text-[#64748b] whitespace-pre-wrap break-all mb-4 max-h-[200px] overflow-y-auto">
                {this.state.error.stack}
              </pre>
            )}
            <button onClick={() => this.setState({ error: null })} className="px-4 py-2 bg-blue-600 text-white rounded text-sm">
              Retry
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function App() {
  const setNodeDefinitions = usePipelineStore((s) => s.setNodeDefinitions);
  const setPipeline = usePipelineStore((s) => s.setPipeline);
  const setProviders = useSettingsStore((s) => s.setProviders);
  const [previewNodeId, setPreviewNodeId] = useState<string | null>(null);
  const [showTemplates, setShowTemplates] = useState(false);

  useEffect(() => {
    getNodeTypes()
      .then((types) => setNodeDefinitions(types))
      .catch(console.error);

    getProviders()
      .then((providers) => setProviders(providers))
      .catch(console.error);
  }, [setNodeDefinitions, setProviders]);

  const handleSelectTemplate = async (template: Template) => {
    setShowTemplates(false);
    const result = await createPipeline({
      name: template.name,
      description: template.description,
      nodes: template.nodes,
      edges: template.edges,
    });

    const rfNodes = template.nodes.map((n: any) => ({
      id: n.id,
      type: 'flowNode',
      position: n.position,
      data: {
        label: n.data.label,
        nodeType: n.type,
        config: n.data.config || {},
        status: 'idle',
        message: '',
        error: '',
      },
    }));

    const rfEdges = template.edges.map((e: any) => ({
      id: e.id,
      source: e.source,
      sourceHandle: e.sourceHandle,
      target: e.target,
      targetHandle: e.targetHandle,
      type: 'smoothstep',
      style: { stroke: '#475569', strokeWidth: 2 },
    }));

    setPipeline(result.id, result.name, rfNodes, rfEdges);
  };

  const handleNodeDoubleClick = (nodeId: string) => {
    setPreviewNodeId(nodeId);
  };

  return (
    <ErrorBoundary>
      <ReactFlowProvider>
        <div className="h-screen w-screen flex flex-col overflow-hidden">
          <Toolbar onLoadTemplate={() => setShowTemplates(true)} />
          <RunProgressBar />
          <div className="flex flex-1 overflow-hidden">
            <NodePalette />
            <Canvas onNodeDoubleClick={handleNodeDoubleClick} />
            <ConfigPanel />
          </div>
          <BottomPanelManager />
        </div>
        {previewNodeId && (
          <DataPreview nodeId={previewNodeId} onClose={() => setPreviewNodeId(null)} />
        )}
        {showTemplates && (
          <TemplateChooser
            onSelect={handleSelectTemplate}
            onClose={() => setShowTemplates(false)}
          />
        )}
      </ReactFlowProvider>
    </ErrorBoundary>
  );
}

export default App;
