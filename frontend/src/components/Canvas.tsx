import { useCallback, useRef } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { usePipelineStore, getNextNodeId } from '../store/pipelineStore';
import FlowNode from '../nodes/FlowNode';

const nodeTypes = { flowNode: FlowNode };

interface CanvasProps {
  onNodeDoubleClick: (nodeId: string) => void;
}

export default function Canvas({ onNodeDoubleClick }: CanvasProps) {
  const {
    nodes, edges, onNodesChange, onEdgesChange, onConnect, addNode,
    selectNode, nodeDefinitions,
  } = usePipelineStore();

  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const rfInstance = useRef<ReactFlowInstance | null>(null);

  const onInit = useCallback((instance: ReactFlowInstance) => {
    rfInstance.current = instance;
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const nodeType = event.dataTransfer.getData('application/reactflow-type');
      if (!nodeType || !rfInstance.current) return;

      const defn = nodeDefinitions.find((d) => d.type === nodeType);
      if (!defn) return;

      const position = rfInstance.current.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const newNode = {
        id: getNextNodeId(),
        type: 'flowNode',
        position,
        data: {
          label: defn.label,
          nodeType: defn.type,
          config: {},
          status: 'idle',
          message: '',
          error: '',
        },
      };

      addNode(newNode);
    },
    [nodeDefinitions, addNode],
  );

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const handleNodeClick = useCallback(
    (_: any, node: any) => {
      selectNode(node.id);
    },
    [selectNode],
  );

  const handleNodeDoubleClick = useCallback(
    (_: any, node: any) => {
      onNodeDoubleClick(node.id);
    },
    [onNodeDoubleClick],
  );

  const handlePaneClick = useCallback(() => {
    selectNode(null);
  }, [selectNode]);

  return (
    <div ref={reactFlowWrapper} className="flex-1 h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onInit={onInit}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeClick={handleNodeClick}
        onNodeDoubleClick={handleNodeDoubleClick}
        onPaneClick={handlePaneClick}
        nodeTypes={nodeTypes}
        fitView
        snapToGrid
        snapGrid={[16, 16]}
        defaultEdgeOptions={{
          type: 'smoothstep',
          animated: false,
          style: { stroke: '#475569', strokeWidth: 2 },
        }}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#1e293b" />
        <Controls position="bottom-left" />
        <MiniMap
          position="bottom-right"
          nodeColor={(n) => {
            const cat = n.data?.nodeType as string;
            if (cat?.startsWith('input')) return '#3b82f6';
            if (cat?.startsWith('transform')) return '#10b981';
            if (cat?.startsWith('ai')) return '#8b5cf6';
            if (cat?.startsWith('lookup')) return '#f59e0b';
            if (cat?.startsWith('output')) return '#ef4444';
            return '#6b7280';
          }}
          maskColor="#0f172a90"
        />
      </ReactFlow>
    </div>
  );
}
