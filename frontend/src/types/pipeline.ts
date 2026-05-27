export interface Pipeline {
  id: string;
  name: string;
  description: string;
  nodes: PipelineNode[];
  edges: PipelineEdge[];
  created_at?: string;
  updated_at?: string;
}

export interface PipelineNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: {
    label: string;
    config: Record<string, any>;
    status?: 'idle' | 'running' | 'success' | 'error' | 'skipped';
    message?: string;
    error?: string;
  };
}

export interface PipelineEdge {
  id: string;
  source: string;
  sourceHandle: string;
  target: string;
  targetHandle: string;
}

export interface PortDefinition {
  name: string;
  label: string;
  type: string;
  multiple: boolean;
}

export interface ConfigField {
  name: string;
  label: string;
  type: string;
  required: boolean;
  default: any;
  options: string[];
  description: string;
  placeholder: string;
}

export interface NodeDefinition {
  type: string;
  label: string;
  category: string;
  icon: string;
  color: string;
  description: string;
  inputs: PortDefinition[];
  outputs: PortDefinition[];
  config_fields: ConfigField[];
  plugin?: string;
}
