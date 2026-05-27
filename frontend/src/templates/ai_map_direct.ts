import type { Template } from './index';

export const AI_MAP_DIRECT_TEMPLATE: Template = {
  id: 'ai_map_direct',
  name: 'AI Map Analysis (Direct)',
  description: 'Load map scans → single high-res pass extracts all metadata → optional supplement crops for unclear areas → Excel',
  category: 'ai',
  nodes: [
    {
      id: 'n1', type: 'input_images',
      position: { x: 50, y: 300 },
      data: { label: 'Map Scans', config: { max_images: 0 } },
    },
    {
      id: 'n2', type: 'ai_map_analysis',
      position: { x: 350, y: 300 },
      data: {
        label: 'AI Map Analysis (Direct)',
        config: {
          mode: 'direct',
          model: '',
          image_column: 'file_path',
          max_tokens: 50000,
          concurrency: 0,
        },
      },
    },
    {
      id: 'n3', type: 'output_xlsx',
      position: { x: 650, y: 300 },
      data: { label: 'Excel Output', config: { filename: 'map_analysis.xlsx' } },
    },
  ],
  edges: [
    { id: 'e1', source: 'n1', sourceHandle: 'output', target: 'n2', targetHandle: 'input' },
    { id: 'e2', source: 'n2', sourceHandle: 'output', target: 'n3', targetHandle: 'input' },
  ],
};
